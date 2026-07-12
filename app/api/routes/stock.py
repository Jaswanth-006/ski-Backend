"""Stock & inventory routes (Phase 2). Intake and the live inventory view are available
to office + owner (delivery does not manage stock)."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.inventory import InventoryAdjust, InventoryOut, StockIntake
from app.schemas.stock import Ac4Request, ErvRequest, StockOverview
from app.schemas.stock_loads import StockLoadOut, StockLoadUpsert
from app.services import inventory as inventory_service
from app.services import stock as stock_service
from app.services import stock_loads as stock_loads_service

router = APIRouter(tags=["stock"])


@router.get("/stock/overview", response_model=StockOverview)
async def stock_overview(
    date: dt.date | None = None,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> StockOverview:
    """Per-day full/empty cylinder + accessory opening, movement, and closing."""
    return await stock_service.overview(db, date or dt.date.today())


@router.post("/stock/ac4", response_model=StockOverview, status_code=status.HTTP_201_CREATED)
async def stock_ac4(
    body: Ac4Request,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> StockOverview:
    """ac4 — stock received from the plant (full cylinders + accessories)."""
    try:
        await stock_service.record_ac4(
            db,
            cylinders=body.cylinders,
            accessories=body.accessories,
            created_by=current_user.id,
            business_date=body.business_date,
        )
    except stock_service.InvalidReference as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await stock_service.overview(db, body.business_date or dt.date.today())


@router.post("/stock/erv", response_model=StockOverview, status_code=status.HTTP_201_CREATED)
async def stock_erv(
    body: ErvRequest,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> StockOverview:
    """erv — empty cylinders returned to the plant."""
    try:
        await stock_service.record_erv(
            db,
            lines=body.lines,
            created_by=current_user.id,
            business_date=body.business_date,
        )
    except stock_service.InvalidReference as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await stock_service.overview(db, body.business_date or dt.date.today())


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
        await inventory_service.record_intake(db, body.lines, current_user.id, body.business_date)
    except inventory_service.InvalidCylinderType as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid cylinder type") from exc
    return await inventory_service.list_inventory(db)


@router.post("/stock/loads", response_model=StockLoadOut, status_code=status.HTTP_201_CREATED)
async def upsert_stock_load(
    body: StockLoadUpsert,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> StockLoadOut:
    """Record how many cylinders a driver loaded out (and returned) for a date."""
    try:
        return await stock_loads_service.upsert_load(db, body, current_user.id)
    except stock_loads_service.InvalidReference as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid {exc}") from exc


@router.get("/stock/loads", response_model=list[StockLoadOut])
async def list_stock_loads(
    date: dt.date,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[StockLoadOut]:
    return await stock_loads_service.list_loads(db, date)


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
