from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import DATABASE_URL

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
        if connection.dialect.name == "postgresql":
            # ContentChunk.embedding needs pgvector; the Docker image ships it.
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
