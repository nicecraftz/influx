from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index, LargeBinary, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from influx.core.config import EMBEDDING_DIMENSIONS
from influx.core.time import timestamp_field

if TYPE_CHECKING:
    from influx.crawler.domain.models import Page


class ContentChunk(SQLModel, table=True):
    """A window of a page's text together with its embedding.

    `source_hash` is the page's content hash at the time of embedding: when it
    no longer matches `Page.hash` the page has changed and its chunks are stale.
    """

    __table_args__ = (
        UniqueConstraint("page_id", "position", name="uq_contentchunk_page_position"),
        # Approximate nearest-neighbour index for the retrieval query
        # (`embedding <=> query`, cosine). Without it every query is a
        # sequential scan over the chunks of every tenant.
        Index(
            "ix_contentchunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    position: int = Field(nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(sa_column=Column(Vector(EMBEDDING_DIMENSIONS), nullable=False))
    source_hash: bytes = Field(sa_column=Column(LargeBinary(32), nullable=False))
    created_at: datetime = timestamp_field()

    page_id: int = Field(foreign_key="page.id", nullable=False, ondelete="CASCADE")
    page: "Page" = Relationship(back_populates="chunks")
    # Denormalised from Page so retrieval and row-level security can filter by
    # tenant without a join; the ingestion job copies it from the page.
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True, ondelete="CASCADE")
