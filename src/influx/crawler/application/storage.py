"""Batched persistence for crawl output.

Crawlee's own storage clients (dataset / key-value store / request queue) are
generic JSON stores, so instead of subclassing them the request handler pushes
domain rows here and this class writes them to Postgres/SQLite in bulk upserts
keyed on (organization_id, url). Flushes happen when a row or byte threshold is
hit, on a timer, and once more on exit.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import STORAGE_BATCH_BYTES, STORAGE_BATCH_ROWS, STORAGE_FLUSH_INTERVAL
from influx.core.db import async_session
from influx.core.logging import get_logger
from influx.crawler.domain.models import Document, Link, Page, sha256

log = get_logger(__name__)

_INSERT_BY_DIALECT: dict[str, Callable[[Table], Any]] = {
    "postgresql": postgresql.insert,
    "sqlite": sqlite.insert,
}


class CrawlStorage:
    def __init__(
        self,
        organization_id: int,
        *,
        session_factory: async_sessionmaker[AsyncSession] = async_session,
        batch_rows: int = STORAGE_BATCH_ROWS,
        batch_bytes: int = STORAGE_BATCH_BYTES,
        flush_interval: float = STORAGE_FLUSH_INTERVAL,
    ) -> None:
        self._organization_id = organization_id
        self._session_factory = session_factory
        self._batch_rows = batch_rows
        self._batch_bytes = batch_bytes
        self._flush_interval = flush_interval

        # Keyed by url so a batch never carries the same row twice: Postgres
        # rejects ON CONFLICT DO UPDATE statements that touch a row twice.
        self._pages: dict[str, dict[str, Any]] = {}
        self._documents: dict[str, dict[str, Any]] = {}
        self._links: dict[str, dict[str, Any]] = {}
        self._pending_bytes = 0

        self._flush_lock = asyncio.Lock()
        self._flusher: asyncio.Task[None] | None = None
        self.pages_written = 0
        self.documents_written = 0
        self.links_written = 0

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> "CrawlStorage":
        self._flusher = asyncio.create_task(self._flush_periodically())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._flusher is not None:
            self._flusher.cancel()
            try:
                await self._flusher
            except asyncio.CancelledError:
                pass
            self._flusher = None
        # Let the final flush raise: losing the tail of a crawl silently is worse
        # than marking the crawl as failed.
        await self.flush()

    async def _flush_periodically(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception:
                log.error("periodic flush failed for organization %s; rows kept for retry", self._organization_id)

    # -- producers ---------------------------------------------------------

    async def add_page(self, url: str, content: str) -> None:
        encoded = content.encode("utf-8")
        self._pages[url] = {
            "organization_id": self._organization_id,
            "url": url,
            "content": content,
            "hash": sha256(encoded),
            "last_seen_at": _utcnow(),
        }
        self._pending_bytes += len(encoded)
        await self._flush_if_full()

    async def add_document(self, url: str, blob: bytes) -> None:
        self._documents[url] = {
            "organization_id": self._organization_id,
            "url": url,
            "blob": blob,
            "hash": sha256(blob),
            "last_seen_at": _utcnow(),
        }
        self._pending_bytes += len(blob)
        await self._flush_if_full()

    async def add_link(self, url: str) -> None:
        self._links[url] = {"organization_id": self._organization_id, "url": url}
        await self._flush_if_full()

    # -- flushing ----------------------------------------------------------

    async def _flush_if_full(self) -> None:
        rows = len(self._pages) + len(self._documents) + len(self._links)
        if rows >= self._batch_rows or self._pending_bytes >= self._batch_bytes:
            await self.flush()

    async def flush(self) -> None:
        async with self._flush_lock:
            pages, documents, links = self._pages, self._documents, self._links
            if not (pages or documents or links):
                return
            self._pages, self._documents, self._links = {}, {}, {}
            self._pending_bytes = 0

            try:
                async with self._session_factory() as session:
                    insert = _INSERT_BY_DIALECT[session.get_bind().dialect.name]
                    if pages:
                        await self._upsert(session, insert, Page.__table__, list(pages.values()), ("content", "hash", "last_seen_at"))
                    if documents:
                        await self._upsert(session, insert, Document.__table__, list(documents.values()), ("blob", "hash", "last_seen_at"))
                    if links:
                        stmt = insert(Link.__table__).values(list(links.values()))
                        await session.execute(stmt.on_conflict_do_nothing(index_elements=["organization_id", "url"]))
                    await session.commit()
            except Exception:
                # Put the batch back, newer rows winning, so the next flush retries it.
                self._pages = pages | self._pages
                self._documents = documents | self._documents
                self._links = links | self._links
                self._pending_bytes += sum(len(p["content"]) for p in pages.values())
                self._pending_bytes += sum(len(d["blob"]) for d in documents.values())
                raise

            self.pages_written += len(pages)
            self.documents_written += len(documents)
            self.links_written += len(links)
            log.info(
                "flushed %d pages, %d documents, %d links for organization %s",
                len(pages), len(documents), len(links), self._organization_id,
            )

    @staticmethod
    async def _upsert(
        session: AsyncSession,
        insert: Callable[[Table], Any],
        table: Table,
        rows: list[dict[str, Any]],
        update_columns: tuple[str, ...],
    ) -> None:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["organization_id", "url"],
            set_={column: getattr(stmt.excluded, column) for column in update_columns},
        )
        await session.execute(stmt)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
