"""Nearest chunks of an organization for a question.

The question is embedded with the same model and the query prefix the chunks
were built with (ingestion/application/embedding_service.py), then ranked by
cosine distance through the HNSW index on ContentChunk.embedding.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import RETRIEVAL_TOP_K
from influx.crawler.domain.models import Page
from influx.ingestion.application.embedding_service import embed_query
from influx.ingestion.domain.models import ContentChunk


@dataclass(frozen=True)
class Passage:
    content: str
    url: str
    title: str | None
    similarity: float  # cosine, -1..1; 1 is identical


async def search_passages(
    session: AsyncSession, organization_id: int, question: str, *, k: int = RETRIEVAL_TOP_K
) -> list[Passage]:
    """The `k` chunks of the organization closest to `question`, best first."""
    vector = await embed_query(question)
    distance = ContentChunk.embedding.cosine_distance(vector)

    # The index is shared by every tenant, and an HNSW scan stops after
    # `ef_search` candidates *before* the organization filter applies: a small
    # tenant next to a big one would get back fewer than k rows, or none.
    # Iterative scans keep pulling candidates until the LIMIT is met
    # (pgvector >= 0.8). Transaction-local, like the RLS role switch.
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = await session.exec(
        select(ContentChunk.content, Page.url, Page.title, distance)
        .join(Page, Page.id == ContentChunk.page_id)
        .where(ContentChunk.organization_id == organization_id)
        .order_by(distance)
        .limit(k)
    )
    return [Passage(content, url, title, 1.0 - float(d)) for content, url, title, d in rows]
