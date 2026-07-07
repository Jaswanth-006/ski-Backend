"""Expenses service (Phase 4-C). A cash expense also posts to the append-only cash ledger."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CashLedger, Expense, ExpenseItem
from app.schemas.expenses import ExpenseCreate, ExpenseOut
from app.services import audit


class InvalidExpenseItem(Exception):
    """The referenced expense item does not exist."""


async def create_expense(
    db: AsyncSession, data: ExpenseCreate, created_by: uuid.UUID
) -> ExpenseOut:
    expense = Expense(
        business_date=data.business_date,
        item_id=data.item_id,
        amount=data.amount,
        method=data.method,
        note=data.note,
        created_by=created_by,
    )
    db.add(expense)
    # A cash expense reduces cash in hand → negative cash-ledger entry.
    if data.method == "cash":
        db.add(CashLedger(sale_id=None, amount=-data.amount, kind="expense"))
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidExpenseItem(str(data.item_id)) from exc

    await audit.write(
        db,
        created_by,
        "expense.create",
        "expense",
        expense.id,
        new={"amount": str(data.amount), "method": data.method},
    )
    await db.commit()

    item_name = await db.scalar(select(ExpenseItem.name).where(ExpenseItem.id == data.item_id))
    return ExpenseOut(
        id=expense.id,
        business_date=expense.business_date,
        item_id=expense.item_id,
        item_name=item_name or "—",
        amount=expense.amount,
        method=expense.method,
        note=expense.note,
        created_at=expense.created_at,
    )


async def list_expenses(db: AsyncSession, on_date: dt.date | None = None) -> list[ExpenseOut]:
    stmt = select(Expense, ExpenseItem.name).join(ExpenseItem, ExpenseItem.id == Expense.item_id)
    if on_date is not None:
        stmt = stmt.where(Expense.business_date == on_date)
    rows = (await db.execute(stmt.order_by(Expense.created_at.desc()))).all()
    return [
        ExpenseOut(
            id=e.id,
            business_date=e.business_date,
            item_id=e.item_id,
            item_name=name,
            amount=e.amount,
            method=e.method,
            note=e.note,
            created_at=e.created_at,
        )
        for e, name in rows
    ]
