from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, LargeBinary, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from influx.organization.domain.models import Organization

# Long enough for any realistic URL, short enough to index on every backend.
URL_LENGTH = 2048


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Timezone-aware datetimes that survive backends without a native tz type.

    SQLite drops the offset, so DateTime(timezone=True) alone hands back naive
    values that blow up when compared against an aware datetime. Normalising to
    UTC on write and re-attaching it on read keeps both ends aware everywhere.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to a UtcDateTime column")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CrawlStatus(str, Enum):
    PENDING = "PENDING"
    ONGOING = "ONGOING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Document(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("organization_id", "url", name="uq_document_org_url"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    last_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(UtcDateTime, nullable=False),
    )

    organization_id: int = Field(foreign_key="organization.id", nullable=False)
    organization: "Organization" = Relationship(back_populates="documents")


class Page(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("organization_id", "url", name="uq_page_org_url"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    last_seen_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(UtcDateTime, nullable=False),
    )

    organization_id: int = Field(foreign_key="organization.id", nullable=False)
    organization: "Organization" = Relationship(back_populates="pages")


class Link(SQLModel, table=True):
    """A host discovered under the organization's domain (e.g. a subdomain).

    `url` is the origin (scheme://host) so an enabled link can be handed to the
    crawler as a root_url as-is.
    """

    __table_args__ = (UniqueConstraint("organization_id", "url", name="uq_link_org_url"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    enabled: bool = Field(default=False, nullable=False)

    organization_id: int = Field(foreign_key="organization.id", nullable=False)
    organization: "Organization" = Relationship(back_populates="links")


class Crawl(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    root_url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    automated: bool = Field(default=True, nullable=False)
    status: CrawlStatus = Field(
        default=CrawlStatus.PENDING,
        sa_column=Column(SAEnum(CrawlStatus), nullable=False),
    )
    started_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(UtcDateTime, nullable=False),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(UtcDateTime),
    )

    organization_id: int = Field(foreign_key="organization.id", nullable=False)
    organization: "Organization" = Relationship(back_populates="crawls")
