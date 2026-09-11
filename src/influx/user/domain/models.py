from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from influx.organization.domain.models import Organization, Participation


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    last_name: str = Field(nullable=False)
    email: str = Field(nullable=False, unique=True)
    hashed_password: str = Field(nullable=False)

    participations: list["Participation"] = Relationship(back_populates="user")
    administered_organizations: list["Organization"] = Relationship(
        back_populates="administrator"
    )
