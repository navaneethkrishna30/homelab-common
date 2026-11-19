"""The service database: one async engine, one session factory, the service schema on the path."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from homelab_common.config import CommonSettings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args(settings: CommonSettings) -> dict[str, dict[str, str]]:
    """asyncpg server settings: every new connection searches the service schema first."""
    return {"server_settings": {"search_path": settings.database_schema}}


def init(settings: CommonSettings) -> None:
    """Create the engine and session factory from settings; once per process."""
    global _engine, _sessionmaker
    if _engine is not None:
        raise RuntimeError("db.init() already called")
    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
        connect_args=_connect_args(settings),
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


@asynccontextmanager
async def session() -> AsyncGenerator[AsyncSession]:
    """One transaction: commit on clean exit, roll back when the block raises."""
    if _sessionmaker is None:
        raise RuntimeError("db.init() not called")
    async with _sessionmaker() as db_session:
        try:
            yield db_session
        except BaseException:
            await db_session.rollback()
            raise
        else:
            await db_session.commit()


async def dispose() -> None:
    """Close the engine and reset the module so init() can run again."""
    global _engine, _sessionmaker
    engine = _engine
    _engine = None
    _sessionmaker = None
    if engine is not None:
        await engine.dispose()


async def ping() -> bool:
    """True when the database answers SELECT 1; False on any failure."""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
