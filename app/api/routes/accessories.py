"""Accessory catalog routes (stock v2). Owner manages; office+owner read."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.db.models import User
from app.schemas.accessory import AccessoryCreate, AccessoryOut, AccessoryUpdate
from app.services import accessories as accessories_service
from app.services import audit

router = APIRouter(tags=["accessories"])


@router.get("/accessories", response_model=list[AccessoryOut])
async def list_accessories(
    active_only: bool = True,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AccessoryOut]:
    return await accessories_service.list_accessories(db, active_only=active_only)


@router.post("/accessories", response_model=AccessoryOut, status_code=status.HTTP_201_CREATED)
async def create_accessory(
    body: AccessoryCreate,
    actor: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> AccessoryOut:
    try:
        result = await accessories_service.create_accessory(db, body.name)
    except accessories_service.DuplicateAccessory as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="accessory already exists") from exc
    await audit.record(
        db,
        actor.id,
        "accessory.create",
        "accessory",
        result.id,
        new=body.model_dump(mode="json", exclude_unset=True),
    )
    return result


@router.patch("/accessories/{accessory_id}", response_model=AccessoryOut)
async def update_accessory(
    accessory_id: uuid.UUID,
    body: AccessoryUpdate,
    actor: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> AccessoryOut:
    try:
        result = await accessories_service.update_accessory(db, accessory_id, body)
    except accessories_service.AccessoryNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="accessory not found") from exc
    except accessories_service.DuplicateAccessory as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="accessory already exists") from exc
    await audit.record(
        db,
        actor.id,
        "accessory.update",
        "accessory",
        accessory_id,
        new=body.model_dump(mode="json", exclude_unset=True),
    )
    return result


@router.delete("/accessories/{accessory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_accessory(
    accessory_id: uuid.UUID,
    actor: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await accessories_service.delete_accessory(db, accessory_id)
    except accessories_service.AccessoryNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="accessory not found") from exc
    except accessories_service.AccessoryInUse as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="this accessory has stock history — deactivate it instead",
        ) from exc
    await audit.record(db, actor.id, "accessory.delete", "accessory", accessory_id)
