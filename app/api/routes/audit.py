"""Audit log viewer (Phase 3-E) — owner-only, read-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.audit import AuditOut
from app.services import audit as audit_service

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditOut])
async def list_audit(
    entity: str | None = None,
    entity_id: str | None = None,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[AuditOut]:
    return await audit_service.list_entries(db, entity=entity, entity_id=entity_id)
