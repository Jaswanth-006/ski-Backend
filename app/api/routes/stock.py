"""Stock & inventory routes (Phase 2). Intake and the live inventory view are available
to office + owner (delivery does not manage stock)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.inventory import InventoryOut, StockIntake
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
