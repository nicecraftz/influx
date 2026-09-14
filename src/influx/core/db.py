from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import DATABASE_URL
from influx.core.rls import apply_row_level_security, mark_api_session

# Imported for their side effects: every model has to be registered on
# SQLModel.metadata before create_all() or mapper configuration runs.
import influx.crawler.domain.models  # noqa: F401
import influx.ingestion.domain.models  # noqa: F401
import influx.organization.domain.models  # noqa: F401
import influx.user.domain.models  # noqa: F401

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(SQLModel.metadata.create_all)
        await apply_row_level_security(connection)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        mark_api_session(session)
        yield session


async def get_system_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session


# Route parameter type: `session: SessionDep` injects one AsyncSession per
# request, subject to row-level security (see core/rls.py): it sees nothing
# until `get_current_user` has run and only the caller's organizations after.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Unscoped session (table owner, RLS bypassed). Only for routes that must read
# before anyone is authenticated, i.e. login. Never use it for tenant data.
SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]


async def close_db() -> None:
    await engine.dispose()
