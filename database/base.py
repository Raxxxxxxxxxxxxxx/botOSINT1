"""Declarative base shared by every SQLAlchemy model in the project."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models.

    Kept in its own module (instead of ``database/engine.py``) so that
    ``models/*.py`` can import it without triggering engine/session
    creation as a side effect.
    """
