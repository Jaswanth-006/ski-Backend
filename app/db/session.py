"""Async engines and session factories.

Two engines per 00-MAIN-PRD §4.1 / D4: the **primary** for live OLTP writes and a
**read replica** for analytics/LLM reads. When no replica is configured the replica
factory points at the primary (single-DB dev). Engines connect lazily, so importing
this module never opens a connection.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
replica_engine = create_async_engine(settings.replica_url, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
ReplicaSessionLocal = async_sessionmaker(
    replica_engine, class_=AsyncSession, expire_on_commit=False
)
