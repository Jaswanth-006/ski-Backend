"""Date-range reports (Phase 8-E). Read-only aggregations served from the read replica."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.reports import (
    DeliveryReportRow,
    DepositReportRow,
    ExpenseReportRow,
    StockReportRow,
)

_STOCK = text(
    """
    SELECT ct.id AS cylinder_type_id, ct.code, ct.label,
      COALESCE((SELECT SUM(delta) FROM stock_ledger
                WHERE cylinder_type_id = ct.id AND reason = 'ac4' AND condition = 'full'
                  AND business_date BETWEEN :start AND :end), 0) AS ac4,
      COALESCE((SELECT -SUM(delta) FROM stock_ledger
                WHERE cylinder_type_id = ct.id AND reason = 'erv' AND condition = 'empty'
                  AND business_date BETWEEN :start AND :end), 0) AS erv
    FROM cylinder_types ct
    ORDER BY ct.code
    """
)

_DELIVERY = text(
    """
    SELECT u.id AS delivery_id, u.name AS delivery_name,
      COALESCE((SELECT SUM((sl.unit_price + sl.other_sales_per_unit) * sl.qty)
                FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id
                WHERE s.delivery_id = u.id AND s.status = 'approved'
                  AND s.business_date BETWEEN :start AND :end), 0) AS sales,
      COALESCE((SELECT SUM(sl.qty) FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id
                WHERE s.delivery_id = u.id AND s.status = 'approved'
                  AND s.business_date BETWEEN :start AND :end), 0) AS full_cylinders,
      COALESCE((SELECT SUM(sl.qty) FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id
                WHERE s.delivery_id = u.id AND s.status = 'approved'
                  AND s.business_date BETWEEN :start AND :end), 0) AS empty_cylinders
    FROM users u WHERE u.role = 'delivery' ORDER BY u.name
    """
)

_EXPENSES = text(
    """
    SELECT ei.id AS item_id, ei.name AS item_name,
           COALESCE(SUM(e.amount), 0) AS total, COUNT(e.id) AS cnt
    FROM expense_items ei
    LEFT JOIN expenses e ON e.item_id = ei.id AND e.business_date BETWEEN :start AND :end
    GROUP BY ei.id, ei.name
    HAVING COUNT(e.id) > 0
    ORDER BY total DESC
    """
)

_DEPOSITS = text(
    """
    SELECT t.dest_kind AS kind,
           COALESCE(v.name, b.name || ' · ' || ba.account_type, t.dest_person_name) AS recipient,
           SUM(t.amount) AS total, COUNT(*) AS cnt
    FROM transfers t
    LEFT JOIN vendors v ON v.id = t.dest_vendor_id
    LEFT JOIN bank_accounts ba ON ba.id = t.dest_bank_account_id
    LEFT JOIN banks b ON b.id = ba.bank_id
    WHERE t.business_date BETWEEN :start AND :end
    GROUP BY t.dest_kind, recipient
    ORDER BY total DESC
    """
)


async def stock_report(db: AsyncSession, start: dt.date, end: dt.date) -> list[StockReportRow]:
    rows = (await db.execute(_STOCK, {"start": start, "end": end})).mappings().all()
    return [
        StockReportRow(
            cylinder_type_id=r["cylinder_type_id"],
            code=r["code"],
            label=r["label"],
            ac4=int(r["ac4"]),
            erv=int(r["erv"]),
        )
        for r in rows
    ]


async def delivery_report(
    db: AsyncSession, start: dt.date, end: dt.date
) -> list[DeliveryReportRow]:
    rows = (await db.execute(_DELIVERY, {"start": start, "end": end})).mappings().all()
    return [
        DeliveryReportRow(
            delivery_id=r["delivery_id"],
            delivery_name=r["delivery_name"],
            sales=Decimal(r["sales"]),
            full_cylinders=int(r["full_cylinders"]),
            empty_cylinders=int(r["empty_cylinders"]),
        )
        for r in rows
    ]


async def expense_report(db: AsyncSession, start: dt.date, end: dt.date) -> list[ExpenseReportRow]:
    rows = (await db.execute(_EXPENSES, {"start": start, "end": end})).mappings().all()
    return [
        ExpenseReportRow(
            item_id=r["item_id"],
            item_name=r["item_name"],
            total=Decimal(r["total"]),
            count=int(r["cnt"]),
        )
        for r in rows
    ]


async def deposit_report(db: AsyncSession, start: dt.date, end: dt.date) -> list[DepositReportRow]:
    rows = (await db.execute(_DEPOSITS, {"start": start, "end": end})).mappings().all()
    return [
        DepositReportRow(
            kind=r["kind"],
            recipient=r["recipient"] or "—",
            total=Decimal(r["total"]),
            count=int(r["cnt"]),
        )
        for r in rows
    ]
