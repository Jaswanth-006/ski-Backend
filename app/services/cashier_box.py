"""Cashier box service (Phase 8-A).

The cashier box is a single running cash-in-hand balance that carries across days:
    balance = (cash + UPI collected) − expenses − box-sourced deposits.
It is derived, so today's closing is automatically tomorrow's opening. Sales records stay
immutable; the box only reflects them plus deposits out.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.cashier_box import CashierBoxOut

# Collected (cash + UPI) attributed to a sale's business date.
_COLLECTED = text(
    "SELECT COALESCE(SUM(cl.amount), 0) FROM cash_ledger cl JOIN sales s ON s.id = cl.sale_id "
    "WHERE cl.kind IN ('cash','upi') AND s.status = 'approved' AND s.business_date <= :bound"
)
_EXPENSES = text("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE business_date <= :bound")
_DEPOSITS = text(
    "SELECT COALESCE(SUM(amount), 0) FROM transfers "
    "WHERE source_kind = 'cashier_box' AND business_date <= :bound"
)
# Hand cash only — physical notes: cash collected, cash-method expenses, box deposits out.
_CASH_ONLY = text(
    "SELECT COALESCE(SUM(cl.amount), 0) FROM cash_ledger cl JOIN sales s ON s.id = cl.sale_id "
    "WHERE cl.kind = 'cash' AND s.status = 'approved' AND s.business_date <= :bound"
)
_CASH_EXPENSES = text(
    "SELECT COALESCE(SUM(amount), 0) FROM expenses "
    "WHERE method = 'cash' AND business_date <= :bound"
)


async def _cumulative(db: AsyncSession, bound: dt.date) -> dict[str, Decimal]:
    """Totals for every business date up to and including ``bound``."""
    params = {"bound": bound}
    collected = Decimal(await db.scalar(_COLLECTED, params) or 0)
    expenses = Decimal(await db.scalar(_EXPENSES, params) or 0)
    deposits = Decimal(await db.scalar(_DEPOSITS, params) or 0)
    cash_collected = Decimal(await db.scalar(_CASH_ONLY, params) or 0)
    cash_expenses = Decimal(await db.scalar(_CASH_EXPENSES, params) or 0)
    return {
        "collected": collected,
        "expenses": expenses,
        "deposits": deposits,
        "closing": collected - expenses - deposits,
        "cash_collected": cash_collected,
        "hand_cash_closing": cash_collected - cash_expenses - deposits,
    }


async def cashier_box(db: AsyncSession, on_date: dt.date) -> CashierBoxOut:
    prev = await _cumulative(db, on_date - dt.timedelta(days=1))
    cur = await _cumulative(db, on_date)
    return CashierBoxOut(
        business_date=on_date,
        opening=prev["closing"],
        collected=cur["collected"] - prev["collected"],
        expenses=cur["expenses"] - prev["expenses"],
        deposited=cur["deposits"] - prev["deposits"],
        closing=cur["closing"],
        hand_cash_opening=prev["hand_cash_closing"],
        hand_cash_collected=cur["cash_collected"] - prev["cash_collected"],
        hand_cash_closing=cur["hand_cash_closing"],
    )


async def opening_closing(db: AsyncSession, on_date: dt.date) -> tuple[Decimal, Decimal]:
    """Just the (opening, closing) balances for a date — used by the day sheet."""
    box = await cashier_box(db, on_date)
    return box.opening, box.closing
