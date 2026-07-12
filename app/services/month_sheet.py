"""Month sheet service — aggregates approved sales + expenses by business date for a month.

Mirrors the day sheet (services/day_sheet.py) one level up: one row per day that had
activity, plus month totals. The web view links each day back to its full day sheet.
"""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.day_sheet import Denomination
from app.schemas.month_sheet import MonthSheetDay, MonthSheetOut, MonthSheetTotals

_SALES_BY_DAY = text(
    """
    SELECT s.business_date AS d,
           SUM(COALESCE((SELECT SUM(qty) FROM sale_lines WHERE sale_id = s.id), 0)) AS cylinders,
           SUM(COALESCE((SELECT SUM(amount) FROM cash_ledger
                         WHERE sale_id = s.id AND kind = 'cash'), 0))               AS cash,
           SUM(s.upi_total)                                                          AS upi,
           SUM(s.online_total)                                                       AS online
    FROM sales s
    WHERE s.business_date BETWEEN :start AND :end AND s.status = 'approved'
    GROUP BY s.business_date
    """
)
_EXP_BY_DAY = text(
    "SELECT business_date AS d, COALESCE(SUM(amount), 0) AS expenses FROM expenses "
    "WHERE business_date BETWEEN :start AND :end GROUP BY business_date"
)
# Empties sent back to the plant (erv) per day.
_ERV_BY_DAY = text(
    "SELECT business_date AS d, COALESCE(-SUM(delta), 0) AS erv FROM stock_ledger "
    "WHERE reason = 'erv' AND condition = 'empty' AND business_date BETWEEN :start AND :end "
    "GROUP BY business_date"
)
# Hand-cash denominations per day.
_DENOM_BY_DAY = text(
    """
    SELECT s.business_date AS d, cd.note_value, SUM(cd.note_count) AS note_count
    FROM cash_denominations cd
    JOIN sales s ON s.id = cd.sale_id
    WHERE s.business_date BETWEEN :start AND :end AND s.status = 'approved'
    GROUP BY s.business_date, cd.note_value
    HAVING SUM(cd.note_count) > 0
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
    expenses = {
        r["d"]: Decimal(r["expenses"])
        for r in (await db.execute(_EXP_BY_DAY, params)).mappings().all()
    }
    erv_by_day = {
        r["d"]: int(r["erv"]) for r in (await db.execute(_ERV_BY_DAY, params)).mappings().all()
    }
    denom_by_day: dict[dt.date, dict[int, int]] = {}
    for r in (await db.execute(_DENOM_BY_DAY, params)).mappings().all():
        denom_by_day.setdefault(r["d"], {})[int(r["note_value"])] = int(r["note_count"])
    closed = {r["d"] for r in (await db.execute(_CLOSED, params)).mappings().all()}

    days: list[MonthSheetDay] = []
    for d in sorted(set(sales) | set(expenses) | set(erv_by_day)):
        s = sales.get(d)
        cash = Decimal(s["cash"]) if s else Decimal(0)
        upi = Decimal(s["upi"]) if s else Decimal(0)
        online = Decimal(s["online"]) if s else Decimal(0)
        total = cash + upi
        exp = expenses.get(d, Decimal(0))
        notes = denom_by_day.get(d, {})
        days.append(
            MonthSheetDay(
                business_date=d,
                cylinders=int(s["cylinders"]) if s else 0,
                empty_returned=erv_by_day.get(d, 0),
                cash=cash,
                upi=upi,
                online=online,
                total=total,
                expenses=exp,
                net=total - exp,
                denominations=[
                    Denomination(note_value=v, note_count=notes[v])
                    for v in sorted(notes, reverse=True)
                ],
                is_closed=d in closed,
            )
        )

    totals = MonthSheetTotals(
        cylinders=sum(x.cylinders for x in days),
        empty_returned=sum(x.empty_returned for x in days),
        cash=sum((x.cash for x in days), Decimal(0)),
        upi=sum((x.upi for x in days), Decimal(0)),
        online=sum((x.online for x in days), Decimal(0)),
        total=sum((x.total for x in days), Decimal(0)),
        expenses=sum((x.expenses for x in days), Decimal(0)),
        net=sum((x.net for x in days), Decimal(0)),
    )
    return MonthSheetOut(year=year, month=month, days=days, totals=totals)
