from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlmodel import Column, Field, Relationship, SQLModel, Text

from influx.core.time import timestamp_field
from influx.crawler.domain.models import Crawl, CrawlRule, Document, Link, Page

if TYPE_CHECKING:
    from influx.user.domain.models import User


class Role(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


# Children are removed by the database (ondelete="CASCADE" on their FK), so
# SQLAlchemy must not load them and null their FK first.
_CASCADE = {"cascade": "all, delete-orphan", "passive_deletes": True}


class Organization(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, unique=True, max_length=30)
    # Registrable domain (e.g. "esempio.it"): every crawl root and every Link
    # must fall under it. Set at creation, validated with tldextract.
    domain: str = Field(nullable=False, unique=True, max_length=253)
    # Never read yet (AUDIT 5.15): login, crawl and retrieval should refuse an
    # inactive organization.
    active: bool = Field(nullable=False, default=True)
    created_at: datetime = timestamp_field()

    # Who administers the organization is `Participation.role` alone; the
    # service layer guarantees at least one ADMIN/SUPER_ADMIN row per org.
    participants: list["Participation"] = Relationship(back_populates="organization", sa_relationship_kwargs=_CASCADE)
    deactivations: list["OrganizationDeactivation"] = Relationship(
        back_populates="organization", sa_relationship_kwargs=_CASCADE
    )
    rules: list[CrawlRule] = Relationship(back_populates="organization", sa_relationship_kwargs=_CASCADE)
    crawls: list[Crawl] = Relationship(back_populates="organization", sa_relationship_kwargs=_CASCADE)
    links: list[Link] = Relationship(back_populates="organization", sa_relationship_kwargs=_CASCADE)
    pages: list[Page] = Relationship(back_populates="organization", sa_relationship_kwargs=_CASCADE)
    documents: list[Document] = Relationship(back_populates="organization", sa_relationship_kwargs=_CASCADE)


class OrganizationDeactivation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    # Kept if the requesting user is deleted: the request itself still stands.
    requested_by_user_id: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    requested_at: datetime = timestamp_field()
    processed_at: datetime | None = timestamp_field(nullable=True, default_now=False)
    comment: str = Field(sa_column=Column(Text, nullable=False))

    organization: Organization = Relationship(back_populates="deactivations")


class Participation(SQLModel, table=True):
    organization_id: int = Field(foreign_key="organization.id", primary_key=True, ondelete="CASCADE")
    user_id: int = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")
    role: Role = Field(
        default=Role.VIEWER,
        sa_column=Column(SAEnum(Role), nullable=False),
    )
    created_at: datetime = timestamp_field()

    organization: Organization = Relationship(back_populates="participants")
    user: "User" = Relationship(back_populates="participations")
