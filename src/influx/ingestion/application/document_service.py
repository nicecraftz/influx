"""Turn crawled documents (PDF, DOCX, ...) into text.

Runs on its own, after the crawler and before `embed`: for every document of
an organization it runs MarkItDown on the blob and stores the Markdown next
to it. A document is skipped when its text was extracted from the blob the
crawler last stored (same hash), so re-running the command only costs the
documents that were added or re-crawled. A document whose conversion failed
keeps the error and is not retried until `--force`.

Conversion is CPU-bound, so it happens in a pool of CONVERT_WORKERS processes;
the event loop only loads blobs and writes results, one document per
transaction, so an interruption loses at most the documents in flight.
"""

import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import partial
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import CONVERT_TASKS_PER_WORKER, CONVERT_TIMEOUT, CONVERT_WORKERS
from influx.core.db import async_session
from influx.core.logging import get_logger
from influx.core.time import utcnow
from influx.crawler.domain.models import Document
from influx.ingestion.application.conversion_service import ConversionTimeout, convert_blob

log = get_logger(__name__)

# Enough of a stacktrace-free message to tell a broken PDF from a timeout.
_ERROR_LENGTH = 500


@dataclass
class ConvertStats:
    converted: int = 0
    skipped: int = 0  # text already extracted from this blob
    empty: int = 0  # converted, but no text came out (scanned PDF, image-only)
    failed: int = 0


async def convert_documents(
    organization_id: int,
    *,
    force: bool = False,
    workers: int = CONVERT_WORKERS,
    session_factory: async_sessionmaker[AsyncSession] = async_session,
) -> ConvertStats:
    stats = ConvertStats()

    async with session_factory() as session:
        pending = await _pending_document_ids(session, organization_id, force=force, stats=stats)

    log.info("organization %d: %d documents to convert, %d unchanged", organization_id, len(pending), stats.skipped)
    if not pending:
        return stats

    # `spawn`, never `fork`: the parent holds an event loop and Postgres
    # connections, neither of which survives a fork. The per-child task cap
    # needs a non-fork context anyway.
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        max_tasks_per_child=CONVERT_TASKS_PER_WORKER,
    )
    slots = asyncio.Semaphore(workers)

    async def convert(index: int, document_id: int) -> None:
        async with slots:
            await _convert_one(pool, session_factory, document_id, index, len(pending), stats)

    try:
        await asyncio.gather(*(convert(index, document_id) for index, document_id in enumerate(pending, start=1)))
    finally:
        # No waiting: on Ctrl+C a worker mid-document would otherwise hold the
        # exit for as long as CONVERT_TIMEOUT allows.
        pool.shutdown(wait=False, cancel_futures=True)
    return stats


async def _convert_one(
    pool: ProcessPoolExecutor,
    session_factory: async_sessionmaker[AsyncSession],
    document_id: int,
    index: int,
    total: int,
    stats: ConvertStats,
) -> None:
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return  # deleted between the two queries
        url, blob, blob_hash, content_type = document.url, document.blob, document.hash, document.content_type
    # The session is closed here on purpose: a big PDF takes minutes, and a
    # connection idling that long would starve the other workers.

    text: str | None = None
    error: str | None = None
    job = partial(convert_blob, blob, extension=_extension(url), content_type=content_type, timeout=CONVERT_TIMEOUT)
    try:
        text = _storable(await asyncio.get_running_loop().run_in_executor(pool, job))
    except BrokenProcessPool:
        # A worker died (out of memory, a crash inside pdfium): every later
        # document would fail the same way, so stop the run instead of marking
        # them all failed. They stay pending for the next one.
        raise
    except (ConversionTimeout, Exception) as exc:
        error = f"{type(exc).__name__}: {exc}"[:_ERROR_LENGTH]

    async with session_factory() as session:
        # A plain UPDATE, not the ORM: the before_update hook would rehash the
        # blob, and `hash` is exactly what must stay as the crawler wrote it.
        await session.exec(
            update(Document)
            .where(Document.id == document_id)
            .values(text=text or None, text_hash=blob_hash, converted_at=utcnow(), conversion_error=error)
        )
        await session.commit()

    if error is not None:
        stats.failed += 1
        log.warning("[%d/%d] %s: %s", index, total, url, error)
    elif text:
        stats.converted += 1
        log.info("[%d/%d] %s: %d characters", index, total, url, len(text))
    else:
        stats.empty += 1
        log.warning("[%d/%d] %s: no text (scanned or image-only?)", index, total, url)


async def _pending_document_ids(
    session: AsyncSession, organization_id: int, *, force: bool, stats: ConvertStats
) -> list[int]:
    """Ids of the organization's documents whose text is missing or stale.

    Only ids and hashes are pulled here: blobs are loaded one at a time while
    converting, so a site with gigabytes of PDFs never has to fit in memory.
    """
    rows = await session.exec(
        select(Document.id, Document.hash, Document.text_hash)
        .where(Document.organization_id == organization_id)
        .order_by(Document.id)
    )

    pending: list[int] = []
    for document_id, blob_hash, text_hash in rows:
        if force or text_hash is None or text_hash != blob_hash:
            pending.append(document_id)
        else:
            stats.skipped += 1
    return pending


def _extension(url: str) -> str | None:
    """`.pdf` for `https://x/y/z.pdf?v=2`, None when the path has no suffix."""
    return PurePosixPath(urlsplit(url).path).suffix.lower() or None


def _storable(text: str) -> str:
    # Postgres rejects NUL in TEXT (pdfminer emits it for some broken fonts)
    # and asyncpg cannot encode the lone surrogates bad CMaps produce.
    return text.replace("\x00", "").encode("utf-8", errors="replace").decode("utf-8").strip()
