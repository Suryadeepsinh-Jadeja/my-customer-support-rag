"""Async SQLAlchemy engine and session management."""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        kwargs = {}
        if settings.database_backend == "postgresql":
            kwargs = {"pool_size": 10, "max_overflow": 10, "pool_pre_ping": True}
        _engine = create_async_engine(settings.DATABASE_URL, echo=settings.DATABASE_ECHO, **kwargs)
        if settings.database_backend == "sqlite":
            # SQLite ignores foreign keys (and so ON DELETE CASCADE) unless asked.
            @event.listens_for(_engine.sync_engine, "connect")
            def _enable_foreign_keys(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    if _sessionmaker is None:  # pragma: no cover
        raise RuntimeError("Database engine failed to initialise")
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """Request-scoped session. Routes commit explicitly; anything uncommitted is rolled back."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
