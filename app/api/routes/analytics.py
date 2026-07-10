"""EOD analytics route (Phase 4-E). Reads from the replica; net profit is owner-only."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_replica_db
from app.db.models import User
from app.schemas.analytics import CollectionsTrendOut, CylinderMovementOut, EodOut
from app.services import analytics as analytics_service

router = APIRouter(tags=["analytics"])


@router.get("/analytics/eod", response_model=EodOut)
async def eod(
    date: dt.date | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_replica_db),
) -> EodOut:
    on_date = date or dt.date.today()
    include_net = current_user.role == "super_admin"
    return await analytics_service.eod(db, on_date, include_net_profit=include_net)


@router.get("/analytics/collections", response_model=CollectionsTrendOut)
async def collections(
    date: dt.date | None = None,
    days: int = 7,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_replica_db),
) -> CollectionsTrendOut:
    """Daily cash + UPI collections for the `days`-day window ending on `date` (default today)."""
    end_date = date or dt.date.today()
    return await analytics_service.collections_trend(db, end_date, days=days)


@router.get("/analytics/cylinder-movement", response_model=CylinderMovementOut)
async def cylinder_movement(
    date: dt.date | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_replica_db),
) -> CylinderMovementOut:
    """Per-type cylinders loaded / sold / left in the warehouse for `date` (default today)."""
    on_date = date or dt.date.today()
    return await analytics_service.cylinder_movement(db, on_date)
