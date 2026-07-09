"""Cashier box route (Phase 8-A)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.cashier_box import CashierBoxOut
from app.services import cashier_box as cashier_box_service

router = APIRouter(tags=["cashier-box"])


@router.get("/cashier-box/{on_date}", response_model=CashierBoxOut)
async def get_cashier_box(
    on_date: dt.date,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> CashierBoxOut:
    return await cashier_box_service.cashier_box(db, on_date)
