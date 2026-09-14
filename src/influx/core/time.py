"""Timezone-aware timestamps for every model.

Column type + default factory shared by all modules, so no domain package has
to import another one just to get a consistent `created_at`.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, TypeDecorator
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Timezone-aware datetimes, normalised to UTC on both sides.

    Postgres stores `timestamptz` in UTC already; the decorator makes the
    Python side strict (naive values are rejected instead of being guessed)
    and returns aware values even if a driver hands back naive ones.
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


def timestamp_field(*, nullable: bool = False, default_now: bool = True):
    """`Field()` for a UtcDateTime column; `default_now=False` leaves it NULL."""
    if default_now:
        return Field(default_factory=utcnow, sa_column=Column(UtcDateTime, nullable=nullable))
    return Field(default=None, sa_column=Column(UtcDateTime, nullable=nullable))
