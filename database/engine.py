"""Async SQLAlchemy engine and session management.

Uses ``DATABASE_URL`` as configured (default: local SQLite via
``aiosqlite``). Swapping to PostgreSQL later is a connection-string
change only — the models avoid any PostgreSQL-only column types on
purpose (see Phase-2 architecture notes).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings
from database.base import Base

# (table, column, DDL type) for columns added to models *after* the table
# already existed in a deployed database. `create_all` only creates missing
# tables, never alters existing ones, so a column added to an ORM model
# needs an explicit, idempotent `ALTER TABLE` here instead of a full
# migration tool — deliberately kept to this one tiny mechanism rather than
# introducing Alembic, consistent with the project's no-migration-tool scale.
_NEW_COLUMNS: list[tuple[str, str, str]] = [
    ("news_items", "telegram_message_id", "INTEGER"),
]


def _add_missing_columns(conn: Connection) -> None:
    inspector = inspect(conn)
    for table, column, ddl_type in _NEW_COLUMNS:
        existing = {col["name"] for col in inspector.get_columns(table)}
        if column in existing:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        logger.info("Added missing column {}.{}", table, column)


# (Postgres enum type name, value) for enum members added to a Python enum
# *after* Postgres already created a native enum type from it. Unlike SQLite
# (enums are just VARCHAR there), Postgres bakes the allowed values into a
# real type at CREATE TYPE time — `create_all` never alters an existing
# type, so `ItemStatus.DELETED` (added for the admin panel) needs its own
# explicit `ALTER TYPE ... ADD VALUE` here, or every query touching it fails
# with "invalid input value for enum itemstatus" (confirmed in production).
_NEW_ENUM_VALUES: list[tuple[str, str]] = [
    ("itemstatus", "DELETED"),
    ("sourcetype", "FACEBOOK_SELENIUM"),
]


async def _add_missing_enum_values() -> None:
    """Add new enum labels to already-existing Postgres enum types.

    `ALTER TYPE ... ADD VALUE` cannot run inside a multi-statement
    transaction, so this runs on its own autocommit connection rather than
    inside init_db()'s `engine.begin()` block. No-op on SQLite.
    """
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return

    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit_engine.connect() as conn:
        for enum_name, value in _NEW_ENUM_VALUES:
            exists = await conn.scalar(
                text(
                    "SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                    "WHERE t.typname = :enum_name AND e.enumlabel = :value"
                ),
                {"enum_name": enum_name, "value": value},
            )
            if exists:
                continue
            await conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE '{value}'"))
            logger.info("Added enum value '{}' to Postgres type '{}'", value, enum_name)


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
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
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
        await conn.run_sync(_add_missing_columns)
    await _add_missing_enum_values()


async def dispose_engine() -> None:
    """Dispose of the engine's connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
