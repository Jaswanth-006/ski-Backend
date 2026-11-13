"""Date-range reports (Phase 8-E). Read-only aggregations served from the read replica."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.schemas.reports import (
    DeliveryLedgerOut,
    DeliveryLedgerRow,
    DeliveryReportRow,
    DepositReportRow,
    ExpenseReportRow,
    StockReportRow,
)
from app.services.sales import SALE_CHARGE_NOTE

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
      COALESCE((SELECT SUM(sl.empty_qty) FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id
                WHERE s.delivery_id = u.id AND s.status = 'approved'
                  AND s.business_date BETWEEN :start AND :end), 0) AS empty_cylinders
    FROM users u WHERE u.role = 'delivery' ORDER BY u.name
    """
)

_LEDGER_SALES = text(
    """
    SELECT s.business_date, s.created_at, s.invoice_no, s.upi_total, s.online_total,
           s.balance_total,
      COALESCE((SELECT SUM(qty) FROM sale_lines WHERE sale_id = s.id), 0) AS qty,
      COALESCE((SELECT SUM(empty_qty) FROM sale_lines WHERE sale_id = s.id), 0) AS empty_qty,
      COALESCE((SELECT SUM((unit_price + other_sales_per_unit) * qty)
                FROM sale_lines WHERE sale_id = s.id), 0) AS amount,
      COALESCE((SELECT SUM(note_value * note_count)
                FROM cash_denominations WHERE sale_id = s.id), 0) AS cash
    FROM sales s
    WHERE s.delivery_id = :d AND s.status = 'approved'
      AND s.business_date BETWEEN :start AND :end
    """
)

_LEDGER_ENTRIES = text(
    """
    SELECT entry_date, created_at, kind, amount, note
    FROM delivery_balances
    WHERE delivery_id = :d AND entry_date BETWEEN :start AND :end
      AND NOT (kind = 'charge' AND (sale_id IS NOT NULL OR COALESCE(note, '') LIKE :sale_note))
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


class DeliveryNotFound(Exception):
    pass


async def delivery_ledger(
    db: AsyncSession, delivery_id: uuid.UUID, start: dt.date, end: dt.date
) -> DeliveryLedgerOut:
    """One delivery boy's statement: each sale with what was left unpaid on it, plus repayments
    and manual charges. Only the range counts — nothing is carried in from earlier days."""
    user = await db.get(User, delivery_id)
    if user is None or user.role != "delivery":
        raise DeliveryNotFound()
    params = {"d": delivery_id, "start": start, "end": end}

    lines: list[tuple[tuple[dt.date, dt.datetime], DeliveryLedgerRow]] = []
    for r in (await db.execute(_LEDGER_SALES, params)).mappings().all():
        row = DeliveryLedgerRow(
            entry_date=r["business_date"],
            kind="sale",
            invoice_no=r["invoice_no"],
            qty=int(r["qty"]),
            empty_qty=int(r["empty_qty"]),
            amount=Decimal(r["amount"]),
            cash=Decimal(r["cash"]),
            upi=Decimal(r["upi_total"]),
            online=Decimal(r["online_total"]),
            balance=Decimal(r["balance_total"]),
        )
        lines.append(((r["business_date"], r["created_at"]), row))

    # A sale's own balance charge is already on its sale line, so it isn't listed twice.
    entries = await db.execute(_LEDGER_ENTRIES, {**params, "sale_note": f"{SALE_CHARGE_NOTE}%"})
    for r in entries.mappings().all():
        amount = Decimal(r["amount"])
        is_charge = r["kind"] == "charge"
        row = DeliveryLedgerRow(
            entry_date=r["entry_date"],
            kind="charge" if is_charge else "repayment",
            note=r["note"],
            amount=amount if is_charge else Decimal(0),
            repaid=Decimal(0) if is_charge else amount,
            balance=amount if is_charge else Decimal(0),
        )
        lines.append(((r["entry_date"], r["created_at"]), row))

    lines.sort(key=lambda line: line[0])
    rows = [row for _, row in lines]
    total_repaid = sum((r.repaid for r in rows), Decimal(0))

    return DeliveryLedgerOut(
        delivery_id=user.id,
        delivery_name=user.name,
        start=start,
        end=end,
        rows=rows,
        total_qty=sum(r.qty for r in rows),
        total_empty_qty=sum(r.empty_qty for r in rows),
        total_amount=sum((r.amount for r in rows), Decimal(0)),
        total_cash=sum((r.cash for r in rows), Decimal(0)),
        total_upi=sum((r.upi for r in rows), Decimal(0)),
        total_online=sum((r.online for r in rows), Decimal(0)),
        total_repaid=total_repaid,
        total_balance=sum((r.balance for r in rows), Decimal(0)) - total_repaid,
    )


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
