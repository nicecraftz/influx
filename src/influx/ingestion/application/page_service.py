"""Turn crawled pages into embedded chunks.

Runs on its own, after the crawler: for every page of an organization it
chunks the text, asks Ollama for the embeddings and replaces the page's
ContentChunk rows. A page is skipped when its chunks were built from the same
content hash the crawler stored, so re-running the command only costs the
pages that actually changed. Each page is committed on its own, so an
interruption loses at most the page in flight.
"""

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.db import async_session
from influx.core.logging import get_logger
from influx.crawler.domain.models import Page, sha256
from influx.ingestion.application.chunk_service import chunkify_text
from influx.ingestion.application.embedding_service import embed_chunks
from influx.ingestion.domain.models import ContentChunk

log = get_logger(__name__)

@dataclass
class EmbedStats:
    embedded: int = 0
    skipped: int = 0  # unchanged since the last run
    empty: int = 0  # no text to chunk
    chunks: int = 0


async def embed_pages(
    organization_id: int,
    *,
    force: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = async_session,
) -> EmbedStats:
    stats = EmbedStats()

    async with session_factory() as session:
        pending = await _pending_page_ids(session, organization_id, force=force, stats=stats)

    log.info("organization %d: %d pages to embed, %d unchanged", organization_id, len(pending), stats.skipped)

    for index, page_id in enumerate(pending, start=1):
        async with session_factory() as session:
            page = await session.get(Page, page_id)
            if page is None:
                continue  # deleted between the two queries

            chunks = chunkify_text(page.content)
            vectors = await embed_chunks(chunks) if chunks else []
            source_hash = page.hash or sha256(page.content.encode("utf-8"))

            await session.execute(delete(ContentChunk).where(ContentChunk.page_id == page_id))
            session.add_all(
                ContentChunk(
                    page_id=page_id,
                    position=position,
                    content=content,
                    embedding=vector,
                    source_hash=source_hash,
                )
                for position, (content, vector) in enumerate(zip(chunks, vectors, strict=True))
            )
            await session.commit()

        if chunks:
            stats.embedded += 1
            stats.chunks += len(chunks)
        else:
            stats.empty += 1
        log.info("[%d/%d] %s: %d chunks", index, len(pending), page.url, len(chunks))

    return stats


async def _pending_page_ids(
    session: AsyncSession, organization_id: int, *, force: bool, stats: EmbedStats
) -> list[int]:
    """Ids of the organization's pages whose chunks are missing or stale.

    Only ids and hashes are pulled here: page bodies are loaded one at a time
    while embedding so a large site never has to fit in memory at once.
    """
    # Every chunk of a page carries the same source_hash, so position 0 stands
    # for the whole page.
    first_chunk = select(ContentChunk.page_id, ContentChunk.source_hash).where(ContentChunk.position == 0).subquery()
    rows = await session.exec(
        select(Page.id, Page.hash, first_chunk.c.source_hash)
        .outerjoin(first_chunk, first_chunk.c.page_id == Page.id)
        .where(Page.organization_id == organization_id)
        .order_by(Page.id)
    )

    pending: list[int] = []
    for page_id, page_hash, embedded_hash in rows:
        if force or embedded_hash is None or embedded_hash != page_hash:
            pending.append(page_id)
        else:
            stats.skipped += 1
    return pending
