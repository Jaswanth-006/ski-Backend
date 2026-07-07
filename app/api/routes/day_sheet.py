"""Day sheet routes (Phase 4-A/B)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.day_sheet import DaySheetOut
from app.services import day_sheet as day_sheet_service

router = APIRouter(tags=["day-sheet"])


@router.get("/day-sheet/{on_date}", response_model=DaySheetOut)
async def get_day_sheet(
    on_date: dt.date,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> DaySheetOut:
    return await day_sheet_service.get_day_sheet(db, on_date)


@router.post("/day-sheet/{on_date}/close", response_model=DaySheetOut)
async def close_day(
    on_date: dt.date,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> DaySheetOut:
    try:
        return await day_sheet_service.close_day(db, on_date, current_user)
    except day_sheet_service.DayAlreadyClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="the day is already closed") from exc
