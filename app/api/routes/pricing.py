"""Temporal pricing routes (Phase 1-E).

GET resolves the effective price per active variety for a date (any authenticated user —
sales entry needs it). Setting prices (single or bulk) is owner-only.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.db.models import User
from app.schemas.pricing import PriceBulkSet, PriceOut, PriceSet
from app.services import pricing as pricing_service

router = APIRouter(tags=["pricing"])


@router.get("/prices", response_model=list[PriceOut])
async def get_prices(
    date: dt.date | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PriceOut]:
    on_date = date or dt.date.today()
    return await pricing_service.prices_for_date(db, on_date)


@router.put("/prices", status_code=status.HTTP_204_NO_CONTENT)
async def set_price(
    body: PriceSet,
    current_user: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await pricing_service.set_price(
            db, body.cylinder_type_id, body.unit_price, body.effective_date, current_user.id
        )
    except pricing_service.InvalidCylinderType as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid cylinder type") from exc


@router.put("/prices/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def set_prices_bulk(
    body: PriceBulkSet,
    current_user: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await pricing_service.set_prices_bulk(db, body.effective_date, body.prices, current_user.id)
    except pricing_service.InvalidCylinderType as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid cylinder type") from exc
