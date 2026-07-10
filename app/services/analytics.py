"""EOD analytics service (Phase 4-E). Aggregation over a business date; reads route to the
read replica (00-MAIN-PRD §4.1). No ML — plain SQL sums."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analytics import (
    CollectionPoint,
    CollectionsTrendOut,
    CylinderMovementOut,
    CylinderMovementRow,
    EodOut,
)

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


# Daily collections (cash + UPI) grouped by business date, over a window.
_CASH_BY_DAY = text(
    "SELECT s.business_date AS d, COALESCE(SUM(cl.amount), 0) AS amt "
    "FROM cash_ledger cl JOIN sales s ON s.id = cl.sale_id "
    "WHERE cl.kind = 'cash' AND s.business_date BETWEEN :start AND :end "
    "GROUP BY s.business_date"
)
_UPI_BY_DAY = text(
    "SELECT business_date AS d, COALESCE(SUM(upi_total), 0) AS amt "
    "FROM sales WHERE status = 'approved' AND business_date BETWEEN :start AND :end "
    "GROUP BY business_date"
)


async def collections_trend(db: AsyncSession, end_date: dt.date, days: int) -> CollectionsTrendOut:
    """Cash + UPI collected per day for the `days`-day window ending on `end_date`."""
    span = max(1, days)
    start_date = end_date - dt.timedelta(days=span - 1)
    params = {"start": start_date, "end": end_date}

    totals: dict[dt.date, Decimal] = {}
    for query in (_CASH_BY_DAY, _UPI_BY_DAY):
        for day, amount in (await db.execute(query, params)).all():
            totals[day] = totals.get(day, Decimal(0)) + Decimal(amount or 0)

    points = [
        CollectionPoint(
            business_date=start_date + dt.timedelta(days=i),
            total=totals.get(start_date + dt.timedelta(days=i), Decimal(0)),
        )
        for i in range(span)
    ]
    return CollectionsTrendOut(points=points)


# Per-type movement for a day: loaded out, sold, and warehouse cylinders still on hand.
_MOVEMENT = text(
    "SELECT ct.code, ct.label, "
    "COALESCE(ld.loaded, 0) AS loaded, "
    "COALESCE(so.sold, 0) AS sold, "
    "COALESCE(oh.on_hand, 0) AS left_qty "
    "FROM cylinder_types ct "
    "LEFT JOIN ("
    "  SELECT cylinder_type_id, SUM(loaded_qty) AS loaded FROM stock_loads "
    "  WHERE business_date = :d GROUP BY cylinder_type_id"
    ") ld ON ld.cylinder_type_id = ct.id "
    "LEFT JOIN ("
    "  SELECT sl.cylinder_type_id, SUM(sl.qty) AS sold FROM sale_lines sl "
    "  JOIN sales s ON s.id = sl.sale_id "
    "  WHERE s.business_date = :d AND s.status = 'approved' GROUP BY sl.cylinder_type_id"
    ") so ON so.cylinder_type_id = ct.id "
    "LEFT JOIN ("
    "  SELECT cylinder_type_id, SUM(delta) AS on_hand FROM stock_ledger "
    "  WHERE business_date <= :d GROUP BY cylinder_type_id"
    ") oh ON oh.cylinder_type_id = ct.id "
    "WHERE ct.is_active = TRUE "
    "ORDER BY ct.label"
)


async def cylinder_movement(db: AsyncSession, on_date: dt.date) -> CylinderMovementOut:
    """Per active cylinder type: loaded out to drivers, sold, and warehouse stock on hand."""
    rows = [
        CylinderMovementRow(
            code=code, label=label, loaded=int(loaded), sold=int(sold), left=int(left_qty)
        )
        for code, label, loaded, sold, left_qty in (
            await db.execute(_MOVEMENT, {"d": on_date})
        ).all()
    ]
    return CylinderMovementOut(business_date=on_date, rows=rows)
