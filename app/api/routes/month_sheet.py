"""Month sheet route — per-day rollup for a calendar month (owner + office)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.month_sheet import MonthSheetOut
from app.services import month_sheet as month_sheet_service

router = APIRouter(tags=["month-sheet"])


@router.get("/month-sheet/{year}/{month}", response_model=MonthSheetOut)
async def get_month_sheet(
    year: int,
    month: int,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> MonthSheetOut:
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="month must be 1–12")
    return await month_sheet_service.month_sheet(db, year, month)
