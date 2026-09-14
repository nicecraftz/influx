from enum import Enum
from typing import TYPE_CHECKING
from datetime import datetime, timezone

from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel, Text, Column

from influx.crawler.domain.models import Crawl, Document, Link, Page

if TYPE_CHECKING:
    from influx.user.domain.models import User


def _utcnow():
    return datetime.now(timezone.utc)

class Role(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"

class OrganizationDeactivation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    requested_at: datetime = Field(nullable=False, default_factory=_utcnow)
    comment: str = Field(sa_column=Column(Text, nullable=False))

class Organization(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, unique=True, max_length=30)
    administrator_id: int = Field(foreign_key="user.id", nullable=False)
    active: bool = Field(nullable=False, default=True)

    administrator: "User" = Relationship(back_populates="administered_organizations")
    participants: list["Participation"] = Relationship(back_populates="organization")
    crawls: list[Crawl] = Relationship(back_populates="organization")
    links: list[Link] = Relationship(back_populates="organization")
    pages: list[Page] = Relationship(back_populates="organization")
    documents: list[Document] = Relationship(back_populates="organization")


class Participation(SQLModel, table=True):
    organization_id: int = Field(foreign_key="organization.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    role: Role = Field(
        default=Role.VIEWER,
        sa_column=Column(SAEnum(Role), nullable=False),
    )

    organization: Organization = Relationship(back_populates="participants")
    user: "User" = Relationship(back_populates="participations")
