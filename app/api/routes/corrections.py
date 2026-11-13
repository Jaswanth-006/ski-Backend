"""Correction routes: edit or delete purchase entries, expenses, deposits, balance entries and
credits. A reason is required; closed days are owner-only (day_lock → 409)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Awaitable

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.corrections import (
    BalanceEntryEdit,
    BalanceEntryOut,
    CreditEdit,
    ExpenseEdit,
    Reason,
    StockEntryEdit,
    StockEntryOut,
    TransferEdit,
)
from app.services import corrections as service

router = APIRouter(tags=["corrections"])

_OFFICE = ("super_admin", "office_admin")


async def _run[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except service.EntryNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="entry not found") from exc
    except (service.EntryOwnedBySale, service.StockWouldGoNegative) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.InvalidEntry as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _done() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- Purchase (stock) entries ----
@router.get("/stock/entries", response_model=list[StockEntryOut])
async def list_stock_entries(
    date: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> list[StockEntryOut]:
    return await service.list_stock_entries(db, date)


@router.put("/stock/entries/{entry_id}", response_model=StockEntryOut)
async def edit_stock_entry(
    entry_id: uuid.UUID,
    body: StockEntryEdit,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> StockEntryOut:
    return await _run(service.edit_stock_entry(db, entry_id, body, actor))


@router.post("/stock/entries/{entry_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stock_entry(
    entry_id: uuid.UUID,
    body: Reason,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.delete_stock_entry(db, entry_id, body.reason, actor))
    return _done()


# ---- Expenses ----
@router.put("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def edit_expense(
    expense_id: uuid.UUID,
    body: ExpenseEdit,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.edit_expense(db, expense_id, body, actor))
    return _done()


@router.post("/expenses/{expense_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID,
    body: Reason,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.delete_expense(db, expense_id, body.reason, actor))
    return _done()


# ---- Deposits ----
@router.put("/transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def edit_transfer(
    transfer_id: uuid.UUID,
    body: TransferEdit,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.edit_transfer(db, transfer_id, body, actor))
    return _done()


@router.post("/transfers/{transfer_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transfer(
    transfer_id: uuid.UUID,
    body: Reason,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.delete_transfer(db, transfer_id, body.reason, actor))
    return _done()


# ---- Balance entries ----
@router.get("/balance-entries", response_model=list[BalanceEntryOut])
async def list_balance_entries(
    date: dt.date,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> list[BalanceEntryOut]:
    return await service.list_balance_entries(db, date)


@router.put("/delivery-balances/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def edit_delivery_balance(
    entry_id: uuid.UUID,
    body: BalanceEntryEdit,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.edit_balance_entry(db, "delivery", entry_id, body, actor))
    return _done()


@router.post("/delivery-balances/{entry_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_delivery_balance(
    entry_id: uuid.UUID,
    body: Reason,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.delete_balance_entry(db, "delivery", entry_id, body.reason, actor))
    return _done()


@router.put("/customer-balances/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def edit_customer_balance(
    entry_id: uuid.UUID,
    body: BalanceEntryEdit,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.edit_balance_entry(db, "customer", entry_id, body, actor))
    return _done()


@router.post("/customer-balances/{entry_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_balance(
    entry_id: uuid.UUID,
    body: Reason,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.delete_balance_entry(db, "customer", entry_id, body.reason, actor))
    return _done()


# ---- Credits ----
@router.put("/credits/{credit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def edit_credit(
    credit_id: uuid.UUID,
    body: CreditEdit,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.edit_credit(db, credit_id, body, actor))
    return _done()


@router.post("/credits/{credit_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credit(
    credit_id: uuid.UUID,
    body: Reason,
    actor: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _run(service.delete_credit(db, credit_id, body.reason, actor))
    return _done()
