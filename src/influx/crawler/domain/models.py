import hashlib
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, LargeBinary, String, Text, UniqueConstraint, event
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from influx.core.time import timestamp_field

if TYPE_CHECKING:
    from influx.ingestion.domain.models import ContentChunk
    from influx.organization.domain.models import Organization

# Long enough for any realistic URL, short enough to index on every backend.
URL_LENGTH = 2048


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


class CrawlStatus(str, Enum):
    PENDING = "PENDING"
    ONGOING = "ONGOING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Document(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("organization_id", "url", name="uq_document_org_url"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    content_type: str | None = Field(default=None, sa_column=Column(String(255)))
    size: int = Field(nullable=False)
    hash: bytes = Field(default=b"", sa_column=Column(LargeBinary(32), nullable=False))
    # Up to MAX_DOCUMENT_BYTES per row. SQLModel cannot mark a Field as
    # deferred, so listings must `select(...).options(defer(Document.blob))`
    # or pick columns explicitly; `size` and `content_type` exist for that.
    blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    last_seen_at: datetime = timestamp_field()

    # Markdown extracted from `blob` by the `convert` command
    # (ingestion/application/document_service.py). `text_hash` is the blob's
    # hash at extraction time: when it no longer matches `hash` the document
    # was re-crawled and the text is stale. A NULL `text` with a `text_hash`
    # is a conversion that failed (`conversion_error` says why) or a blob with
    # no text layer, e.g. a scanned PDF.
    text: str | None = Field(default=None, sa_column=Column(Text))
    text_hash: bytes | None = Field(default=None, sa_column=Column(LargeBinary(32)))
    converted_at: datetime | None = timestamp_field(nullable=True, default_now=False)
    conversion_error: str | None = Field(default=None, sa_column=Column(Text))

    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    organization: "Organization" = Relationship(back_populates="documents")


class Page(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("organization_id", "url", name="uq_page_org_url"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    # `<title>` of the page, for citations in retrieval answers.
    title: str | None = Field(default=None, sa_column=Column(String(512)))
    content: str = Field(sa_column=Column(Text, nullable=False))
    hash: bytes = Field(default=b"", sa_column=Column(LargeBinary(32), nullable=False))
    last_seen_at: datetime = timestamp_field()

    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    organization: "Organization" = Relationship(back_populates="pages")
    chunks: list["ContentChunk"] = Relationship(
        back_populates="page",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "passive_deletes": True},
    )


class Link(SQLModel, table=True):
    """A host under the organization's domain: its own site, created enabled
    together with the organization, and every subdomain a crawl discovers,
    disabled until an admin switches it on. Enabled links are what a crawl of
    the organization covers (application/policy.py).

    `url` is the origin (scheme://host) so an enabled link can be handed to the
    crawler as a root_url as-is.
    """

    __table_args__ = (UniqueConstraint("organization_id", "url", name="uq_link_org_url"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    enabled: bool = Field(default=False, nullable=False)
    created_at: datetime = timestamp_field()

    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    organization: "Organization" = Relationship(back_populates="links")


class Crawl(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    root_url: str = Field(sa_column=Column(String(URL_LENGTH), nullable=False))
    # True when created by the periodic sweep, False for CLI/API requests.
    automated: bool = Field(default=False, nullable=False)
    status: CrawlStatus = Field(
        default=CrawlStatus.PENDING,
        sa_column=Column(SAEnum(CrawlStatus), nullable=False),
    )
    created_at: datetime = timestamp_field()
    started_at: datetime | None = timestamp_field(nullable=True, default_now=False)
    finished_at: datetime | None = timestamp_field(nullable=True, default_now=False)

    # Outcome, filled in when the crawl closes (see application/scheduler.py).
    requests_finished: int = Field(default=0, nullable=False)
    requests_failed: int = Field(default=0, nullable=False)
    pages: int = Field(default=0, nullable=False)
    documents: int = Field(default=0, nullable=False)
    links: int = Field(default=0, nullable=False)
    # Why it FAILED (exception type + message), NULL otherwise.
    error: str | None = Field(default=None, sa_column=Column(Text))

    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    organization: "Organization" = Relationship(back_populates="crawls")
    # The Link this crawl was started from, when it was (the CLI passes URLs).
    link_id: int | None = Field(default=None, foreign_key="link.id", ondelete="SET NULL")
    requested_by_user_id: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")


class CrawlRule(SQLModel, table=True):
    """URL exclusion pattern of an organization, merged with the CLI ones by the crawler."""

    __table_args__ = (UniqueConstraint("organization_id", "regex", name="uq_crawlrule_org_regex"),)

    id: int | None = Field(default=None, primary_key=True)
    # Capped so a tenant cannot submit a pattern the matcher chokes on (AUDIT 2.11).
    regex: str = Field(sa_column=Column(String(200), nullable=False))
    created_at: datetime = timestamp_field()

    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    organization: "Organization" = Relationship(back_populates="rules")


# SQLModel bypasses instrumented attribute assignment in __init__, so an
# @validates hook would miss every freshly constructed row. Hashing at flush
# time keeps the digest correct however the instance was built. Bulk upserts
# skip ORM events entirely, so the crawler storage computes the same digest
# itself via sha256().
@event.listens_for(Document, "before_insert")
@event.listens_for(Document, "before_update")
def _hash_document(mapper, connection, target: Document) -> None:
    target.hash = sha256(target.blob)
    target.size = len(target.blob)


@event.listens_for(Page, "before_insert")
@event.listens_for(Page, "before_update")
def _hash_page(mapper, connection, target: Page) -> None:
    target.hash = sha256(target.content.encode("utf-8"))
