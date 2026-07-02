"""Declarative base for all ORM models.

Import `Base` here and every model in `app.db.models` so `Base.metadata` sees the
full schema (used by Alembic and tests).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
