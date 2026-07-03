"""Master-data catalog service — cylinder varieties (Phase 1-C).

Soft-delete only (00-MAIN-PRD D13 / 01-BACKEND-PRD §8.2): a variety referenced by
historical rows is never removed — deactivating hides it from dropdowns while keeping
history intact.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CylinderType
from app.schemas.catalog import CylinderTypeCreate, CylinderTypeUpdate


class CodeAlreadyExists(Exception):
    """A cylinder type with the given code already exists."""


async def list_cylinder_types(db: AsyncSession, active: str = "true") -> list[CylinderType]:
    """`active`: "true" (default, dropdown source) → active only; "all" → every row;
    "false" → inactive only."""
    stmt = select(CylinderType)
    if active == "all":
        pass
    elif active in ("false", "0"):
        stmt = stmt.where(CylinderType.is_active.is_(False))
    else:
        stmt = stmt.where(CylinderType.is_active.is_(True))
    result = await db.scalars(stmt.order_by(CylinderType.code))
    return list(result)


async def create_cylinder_type(db: AsyncSession, data: CylinderTypeCreate) -> CylinderType:
    row = CylinderType(code=data.code, label=data.label, is_active=True)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise CodeAlreadyExists(data.code) from exc
    await db.refresh(row)
    return row


async def update_cylinder_type(
    db: AsyncSession, type_id: uuid.UUID, data: CylinderTypeUpdate
) -> CylinderType | None:
    row = await db.get(CylinderType, type_id)
    if row is None:
        return None
    if data.label is not None:
        row.label = data.label
    if data.is_active is not None:
        row.is_active = data.is_active
    await db.commit()
    await db.refresh(row)
    return row
