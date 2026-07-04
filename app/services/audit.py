"""Immutable audit log writer (00-MAIN-PRD §6.1). Every mutation records who/what/old/new.

Called inside the caller's transaction (no commit here) so the audit row and the change
it describes land atomically together.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User
from app.schemas.audit import AuditOut


async def write(
    db: AsyncSession,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: str | uuid.UUID | None = None,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_value=old,
            new_value=new,
        )
    )


async def list_entries(
    db: AsyncSession,
    entity: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
) -> list[AuditOut]:
    stmt = select(AuditLog, User.name).outerjoin(User, User.id == AuditLog.actor_id)
    if entity is not None:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit))).all()
    return [
        AuditOut(
            id=log.id,
            actor_id=log.actor_id,
            actor_name=actor_name,
            action=log.action,
            entity=log.entity,
            entity_id=log.entity_id,
            old_value=log.old_value,
            new_value=log.new_value,
            created_at=log.created_at,
        )
        for log, actor_name in rows
    ]
