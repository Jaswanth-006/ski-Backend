"""Month sheet service — each day sheet's final totals for a calendar month.

One row per day that had sales or balance charges, with the same columns as the day sheet's
totals row (services/day_sheet.py), plus month totals. The web view links each day back to its
full day sheet.
"""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.month_sheet import MonthSheetDay, MonthSheetOut, MonthSheetTotals

_SALES_BY_DAY = text(
    """
    SELECT s.business_date AS d,
           SUM(COALESCE((SELECT SUM(qty) FROM sale_lines WHERE sale_id = s.id), 0)) AS cylinders,
           SUM(COALESCE((SELECT SUM(empty_qty) FROM sale_lines WHERE sale_id = s.id), 0))
               AS empties,
           SUM(COALESCE((SELECT SUM(damaged_qty) FROM sale_lines WHERE sale_id = s.id), 0))
               AS damaged,
           SUM(COALESCE((SELECT SUM((unit_price + other_sales_per_unit) * qty)
                         FROM sale_lines WHERE sale_id = s.id), 0))                 AS amount,
           SUM(COALESCE((SELECT SUM(amount) FROM cash_ledger
                         WHERE sale_id = s.id AND kind = 'cash'), 0))               AS cash,
           SUM(s.upi_total)                                                          AS upi,
           SUM(s.online_total)                                                       AS online
    FROM sales s
    WHERE s.business_date BETWEEN :start AND :end AND s.status = 'approved'
    GROUP BY s.business_date
    """
)
# Balance charged that day to delivery boys and customers (the day sheet's Balance total).
_BALANCE_BY_DAY = text(
    """
    SELECT entry_date AS d, SUM(amount) AS balance FROM (
        SELECT entry_date, amount FROM delivery_balances
        WHERE kind = 'charge' AND entry_date BETWEEN :start AND :end
        UNION ALL
        SELECT entry_date, amount FROM customer_balances
        WHERE kind = 'charge' AND entry_date BETWEEN :start AND :end
    ) charges
    GROUP BY entry_date
    """
)
_CLOSED = text(
    "SELECT business_date AS d FROM day_sheet_status "
    "WHERE is_closed = TRUE AND business_date BETWEEN :start AND :end"
)


async def month_sheet(db: AsyncSession, year: int, month: int) -> MonthSheetOut:
    start = dt.date(year, month, 1)
    end = dt.date(year, month, calendar.monthrange(year, month)[1])
    params = {"start": start, "end": end}

    sales = {r["d"]: r for r in (await db.execute(_SALES_BY_DAY, params)).mappings().all()}
    balance_by_day = {
        r["d"]: Decimal(r["balance"])
        for r in (await db.execute(_BALANCE_BY_DAY, params)).mappings().all()
    }
    closed = {r["d"] for r in (await db.execute(_CLOSED, params)).mappings().all()}

    days: list[MonthSheetDay] = []
    for d in sorted(set(sales) | set(balance_by_day)):
        s = sales.get(d)
        days.append(
            MonthSheetDay(
                business_date=d,
                cylinders=int(s["cylinders"]) if s else 0,
                empties=int(s["empties"]) if s else 0,
                damaged=int(s["damaged"]) if s else 0,
                amount=Decimal(s["amount"]) if s else Decimal(0),
                upi=Decimal(s["upi"]) if s else Decimal(0),
                cash=Decimal(s["cash"]) if s else Decimal(0),
                online=Decimal(s["online"]) if s else Decimal(0),
                balance=balance_by_day.get(d, Decimal(0)),
                is_closed=d in closed,
            )
        )

    totals = MonthSheetTotals(
        cylinders=sum(x.cylinders for x in days),
        empties=sum(x.empties for x in days),
        damaged=sum(x.damaged for x in days),
        amount=sum((x.amount for x in days), Decimal(0)),
        upi=sum((x.upi for x in days), Decimal(0)),
        cash=sum((x.cash for x in days), Decimal(0)),
        online=sum((x.online for x in days), Decimal(0)),
        balance=sum((x.balance for x in days), Decimal(0)),
    )
    return MonthSheetOut(year=year, month=month, days=days, totals=totals)
