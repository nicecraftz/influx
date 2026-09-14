from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel, LargeBinary, Column

if TYPE_CHECKING:
    from influx.organization.domain.models import Organization, Participation


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    last_name: str = Field(nullable=False)
    email: str = Field(nullable=False, unique=True)
    hashed_password: bytes = Field(sa_column=Column(LargeBinary, nullable=True))

    participations: list["Participation"] = Relationship(back_populates="user")
    administered_organizations: list["Organization"] = Relationship(
        back_populates="administrator"
    )
