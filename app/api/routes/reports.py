"""Date-range report routes (Phase 8-E). Reads route to the analytics replica."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_replica_db, require_roles
from app.db.models import User
from app.schemas.reports import (
    DeliveryLedgerOut,
    DeliveryReportRow,
    DepositLedgerOut,
    DepositReportRow,
    ExpenseItemLedgerOut,
    ExpenseReportRow,
    PartyKind,
    PurchaseReportOut,
    SalesReportOut,
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


@router.get("/reports/delivery/{delivery_id}", response_model=DeliveryLedgerOut)
async def delivery_ledger(
    delivery_id: uuid.UUID,
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> DeliveryLedgerOut:
    try:
        return await reports_service.delivery_ledger(db, delivery_id, start, end)
    except reports_service.DeliveryNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="delivery person not found") from exc


@router.get("/reports/expenses", response_model=list[ExpenseReportRow])
async def expense_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> list[ExpenseReportRow]:
    return await reports_service.expense_report(db, start, end)


@router.get("/reports/expenses/{item_id}", response_model=ExpenseItemLedgerOut)
async def expense_item_ledger(
    item_id: uuid.UUID,
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> ExpenseItemLedgerOut:
    """One expense item: each entry in the range with its day, who and how much."""
    try:
        return await reports_service.expense_item_ledger(db, item_id, start, end)
    except reports_service.ExpenseItemNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="expense item not found") from exc


@router.get("/reports/deposits", response_model=list[DepositReportRow])
async def deposit_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> list[DepositReportRow]:
    return await reports_service.deposit_report(db, start, end)


@router.get("/reports/deposits/{kind}/{ref}", response_model=DepositLedgerOut)
async def deposit_ledger(
    kind: PartyKind,
    ref: str,
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> DepositLedgerOut:
    """Every deposit into / out of one place: the cashier box (``ref`` = "box"), a bank account,
    a vendor or a person — when, how much, from where to where."""
    ref_id: uuid.UUID | None = None
    if kind != "cashier_box":
        try:
            ref_id = uuid.UUID(ref)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found") from exc
    try:
        return await reports_service.deposit_ledger(db, kind, ref_id, start, end)
    except reports_service.PlaceNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found") from exc


@router.get("/reports/purchases", response_model=PurchaseReportOut)
async def purchase_report(
    start: dt.date,
    end: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> PurchaseReportOut:
    """Every ac4 purchase in the range: invoice, what came, what it cost."""
    return await reports_service.purchase_report(db, start, end)


@router.get("/reports/sales", response_model=SalesReportOut)
async def sales_report(
    start: dt.date,
    end: dt.date,
    current_user: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_replica_db),
) -> SalesReportOut:
    """Sales per day; the owner also gets profit / loss (sales − purchases − expenses)."""
    with_profit = current_user.role == "super_admin"
    return await reports_service.sales_report(db, start, end, with_profit)
