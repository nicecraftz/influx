from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, LargeBinary, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from influx.core.config import EMBEDDING_DIMENSIONS

if TYPE_CHECKING:
    from influx.crawler.domain.models import Page


class ContentChunk(SQLModel, table=True):
    """A window of a page's text together with its embedding.

    `source_hash` is the page's content hash at the time of embedding: when it
    no longer matches `Page.hash` the page has changed and its chunks are stale.
    """

    __table_args__ = (UniqueConstraint("page_id", "position", name="uq_contentchunk_page_position"),)

    id: int | None = Field(default=None, primary_key=True)
    position: int = Field(nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(sa_column=Column(Vector(EMBEDDING_DIMENSIONS), nullable=False))
    source_hash: bytes = Field(sa_column=Column(LargeBinary(32), nullable=False))

    page_id: int = Field(foreign_key="page.id", nullable=False, ondelete="CASCADE")
    page: "Page" = Relationship(back_populates="chunks")
