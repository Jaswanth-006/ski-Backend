"""Accessory catalog service (stock v2)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Accessory
from app.schemas.accessory import AccessoryOut, AccessoryUpdate


class DuplicateAccessory(Exception):
    """An accessory with this name already exists."""


class AccessoryNotFound(Exception):
    """No accessory with that id."""


class AccessoryInUse(Exception):
    """The accessory is referenced by stock — cannot delete."""


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


async def update_accessory(
    db: AsyncSession, accessory_id: uuid.UUID, data: AccessoryUpdate
) -> AccessoryOut:
    accessory = await db.get(Accessory, accessory_id)
    if accessory is None:
        raise AccessoryNotFound(str(accessory_id))
    if data.name is not None:
        accessory.name = data.name.strip()
    if data.is_active is not None:
        accessory.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateAccessory(data.name or "") from exc
    await db.refresh(accessory)
    return AccessoryOut(id=accessory.id, name=accessory.name, is_active=accessory.is_active)


async def delete_accessory(db: AsyncSession, accessory_id: uuid.UUID) -> None:
    accessory = await db.get(Accessory, accessory_id)
    if accessory is None:
        raise AccessoryNotFound(str(accessory_id))
    await db.delete(accessory)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AccessoryInUse(str(accessory_id)) from exc
