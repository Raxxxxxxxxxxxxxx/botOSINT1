"""Async SQLAlchemy engine and session management.

Uses ``DATABASE_URL`` as configured (default: local SQLite via
``aiosqlite``). Swapping to PostgreSQL later is a connection-string
change only — the models avoid any PostgreSQL-only column types on
purpose (see Phase-2 architecture notes).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings
from database.base import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a short-lived :class:`AsyncSession` for a single unit of work.

    Usage::

        async with get_session() as session:
            session.add(item)
            await session.commit()
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables that don't already exist.

    Safe to call on every startup: existing tables/data are left alone.
    A schema-migration tool (e.g. Alembic) is out of scope for this
    project's size — plain ``create_all`` is sufficient here.
    """
    # Import models so their tables are registered on Base.metadata
    # before create_all is called.
    import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose of the engine's connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
