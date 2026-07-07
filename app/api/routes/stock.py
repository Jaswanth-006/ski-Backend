"""Stock & inventory routes (Phase 2). Intake and the live inventory view are available
to office + owner (delivery does not manage stock)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.inventory import InventoryAdjust, InventoryOut, StockIntake
from app.services import inventory as inventory_service

router = APIRouter(tags=["stock"])


@router.get("/inventory", response_model=list[InventoryOut])
async def get_inventory(
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[InventoryOut]:
    return await inventory_service.list_inventory(db)


@router.post("/stock/intake", response_model=list[InventoryOut])
async def stock_intake(
    body: StockIntake,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[InventoryOut]:
    try:
        await inventory_service.record_intake(db, body.lines, current_user.id)
    except inventory_service.InvalidCylinderType as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid cylinder type") from exc
    return await inventory_service.list_inventory(db)


@router.patch("/inventory/{cylinder_type_id}", response_model=InventoryOut)
async def adjust_inventory(
    cylinder_type_id: uuid.UUID,
    body: InventoryAdjust,
    if_match: str = Header(alias="If-Match", description="current inventory version"),
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> InventoryOut:
    """Correct a count. Send If-Match: <version>; a stale version is rejected with 409."""
    try:
        expected_version = int(if_match)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="If-Match must be an integer version"
        ) from exc

    try:
        row = await inventory_service.adjust_inventory(
            db, cylinder_type_id, body.quantity, expected_version, current_user.id
        )
    except inventory_service.StaleVersion as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"stale version — refresh and retry (current version is {exc.current})",
        ) from exc
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="no inventory for this type; record an intake first"
        )
    return row
