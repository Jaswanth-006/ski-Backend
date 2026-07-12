"""Accessory catalog routes (stock v2). Owner manages; office+owner read."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.db.models import User
from app.schemas.accessory import AccessoryCreate, AccessoryOut
from app.services import accessories as accessories_service

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
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> AccessoryOut:
    try:
        return await accessories_service.create_accessory(db, body.name)
    except accessories_service.DuplicateAccessory as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="accessory already exists") from exc
