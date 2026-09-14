from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlmodel import Column, Field, LargeBinary, Relationship, SQLModel

from influx.core.time import timestamp_field

if TYPE_CHECKING:
    from influx.organization.domain.models import Participation


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    last_name: str = Field(nullable=False)
    # Stored lower-cased (see _normalise_email) so the unique index is
    # effectively case-insensitive: Mario@x.it and mario@x.it are one user.
    email: str = Field(nullable=False, unique=True)
    # NULL for invited users who have not chosen a password yet; login treats
    # it as a wrong password (auth/application/password.py).
    hashed_password: bytes | None = Field(default=None, sa_column=Column(LargeBinary, nullable=True))
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = timestamp_field()

    participations: list["Participation"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "passive_deletes": True},
    )


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _normalise_email(mapper, connection, target: User) -> None:
    target.email = target.email.strip().lower()
