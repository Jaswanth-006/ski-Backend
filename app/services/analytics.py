"""EOD analytics service (Phase 4-E). Aggregation over a business date; reads route to the
read replica (00-MAIN-PRD §4.1). No ML — plain SQL sums."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analytics import EodOut

_CYL = text(
    "SELECT COALESCE(SUM(sl.qty), 0) FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id "
    "WHERE s.business_date = :d AND s.status = 'approved'"
)
_CASH = text(
    "SELECT COALESCE(SUM(cl.amount), 0) FROM cash_ledger cl JOIN sales s ON s.id = cl.sale_id "
    "WHERE s.business_date = :d AND cl.kind = 'cash'"
)
_UPI = text(
    "SELECT COALESCE(SUM(upi_total), 0) FROM sales WHERE business_date = :d AND status = 'approved'"
)
_EXP = text("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE business_date = :d")


async def eod(db: AsyncSession, on_date: dt.date, include_net_profit: bool) -> EodOut:
    params = {"d": on_date}
    cylinders = int(await db.scalar(_CYL, params) or 0)
    gross_cash = Decimal(await db.scalar(_CASH, params) or 0)
    upi_total = Decimal(await db.scalar(_UPI, params) or 0)
    expenses_total = Decimal(await db.scalar(_EXP, params) or 0)
    net_profit = gross_cash + upi_total - expenses_total

    return EodOut(
        business_date=on_date,
        cylinders_sold=cylinders,
        gross_cash=gross_cash,
        upi_total=upi_total,
        expenses_total=expenses_total,
        net_profit=net_profit if include_net_profit else None,
    )
