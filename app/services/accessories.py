"""Accessory catalog service (stock v2)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Accessory
from app.schemas.accessory import AccessoryOut


class DuplicateAccessory(Exception):
    """An accessory with this name already exists."""


async def list_accessories(db: AsyncSession, *, active_only: bool = True) -> list[AccessoryOut]:
    stmt = select(Accessory).order_by(Accessory.name)
    if active_only:
        stmt = stmt.where(Accessory.is_active.is_(True))
    rows = (await db.scalars(stmt)).all()
    return [AccessoryOut(id=a.id, name=a.name, is_active=a.is_active) for a in rows]


async def create_accessory(db: AsyncSession, name: str) -> AccessoryOut:
    accessory = Accessory(name=name.strip())
    db.add(accessory)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateAccessory(name) from exc
    await db.refresh(accessory)
    return AccessoryOut(id=accessory.id, name=accessory.name, is_active=accessory.is_active)
