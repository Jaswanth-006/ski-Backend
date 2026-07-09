"""Date-range report routes (Phase 8-E). Reads route to the analytics replica."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_replica_db, require_roles
from app.db.models import User
from app.schemas.reports import (
    DeliveryReportRow,
    DepositReportRow,
    ExpenseReportRow,
    StockReportRow,
)
from app.services import reports as reports_service

router = APIRouter(tags=["reports"])

_OFFICE = ("super_admin", "office_admin")


@router.get("/reports/stock", response_model=list[StockReportRow])
async def stock_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> list[StockReportRow]:
    return await reports_service.stock_report(db, start, end)


@router.get("/reports/delivery", response_model=list[DeliveryReportRow])
async def delivery_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> list[DeliveryReportRow]:
    return await reports_service.delivery_report(db, start, end)


@router.get("/reports/expenses", response_model=list[ExpenseReportRow])
async def expense_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> list[ExpenseReportRow]:
    return await reports_service.expense_report(db, start, end)


@router.get("/reports/deposits", response_model=list[DepositReportRow])
async def deposit_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> list[DepositReportRow]:
    return await reports_service.deposit_report(db, start, end)
