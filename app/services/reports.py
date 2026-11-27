"""Date-range reports (Phase 8-E). Read-only aggregations served from the read replica."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BankAccount, ExpenseItem, User
from app.schemas.reports import (
    DeliveryLedgerOut,
    DeliveryLedgerRow,
    DeliveryReportRow,
    DepositLedgerOut,
    DepositLedgerRow,
    DepositReportRow,
    ExpenseItemEntry,
    ExpenseItemLedgerOut,
    ExpenseReportRow,
    StockReportRow,
)
from app.services.sales import SALE_CHARGE_NOTE

# Per cylinder type and condition. Sales and their cancellations ('reversal') together are
# the issue of full cylinders and the empties received; ac4 (and legacy intake) is the full
# received; erv the empties issued; anything else (damaged / lost returns, adjustments) is other.
_STOCK = text(
    """
    SELECT ct.id AS cylinder_type_id, ct.code, ct.label, c.condition,
      COALESCE(SUM(sl.delta) FILTER (WHERE sl.business_date < :start), 0) AS opening,
      COALESCE(SUM(sl.delta) FILTER (
        WHERE sl.business_date BETWEEN :start AND :end AND (
          (c.condition = 'full' AND sl.reason IN ('ac4', 'intake')) OR
          (c.condition = 'empty' AND sl.reason IN ('sale', 'reversal')))), 0) AS received,
      COALESCE(-SUM(sl.delta) FILTER (
        WHERE sl.business_date BETWEEN :start AND :end AND (
          (c.condition = 'full' AND sl.reason IN ('sale', 'reversal')) OR
          (c.condition = 'empty' AND sl.reason = 'erv'))), 0) AS issue,
      COALESCE(SUM(sl.delta) FILTER (WHERE sl.business_date <= :end), 0) AS closing
    FROM cylinder_types ct
    CROSS JOIN (VALUES ('full'), ('empty')) AS c(condition)
    LEFT JOIN stock_ledger sl
      ON sl.cylinder_type_id = ct.id AND sl.condition = c.condition
    WHERE ct.is_active
    GROUP BY ct.id, ct.code, ct.label, c.condition
    ORDER BY ct.code, c.condition DESC
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
                FROM cash_denominations WHERE sale_id = s.id), 0) AS cash,
      COALESCE((SELECT SUM(amount) FROM expenses WHERE sale_id = s.id), 0) AS expenses
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


async def stock_report(db: AsyncSession, start: dt.date, end: dt.date) -> list[StockReportRow]:
    rows = (await db.execute(_STOCK, {"start": start, "end": end})).mappings().all()
    return [
        StockReportRow(
            cylinder_type_id=r["cylinder_type_id"],
            code=r["code"],
            label=r["label"],
            condition=r["condition"],
            opening=int(r["opening"]),
            received=int(r["received"]),
            issue=int(r["issue"]),
            # Whatever moved stock besides A + B − C (damaged / lost, adjustments).
            other=int(r["closing"]) - (int(r["opening"]) + int(r["received"]) - int(r["issue"])),
            closing=int(r["closing"]),
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
            expenses=Decimal(r["expenses"]),
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
        total_expenses=sum((r.expenses for r in rows), Decimal(0)),
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


class ExpenseItemNotFound(Exception):
    """No expense item with that id."""


_EXPENSE_ENTRIES = text(
    """
    SELECT e.id, e.business_date, e.amount, e.method, e.note, e.created_at,
           d.name AS delivery_name, s.invoice_no, u.name AS entered_by
    FROM expenses e
    LEFT JOIN users d ON d.id = e.delivery_id
    LEFT JOIN sales s ON s.id = e.sale_id
    LEFT JOIN users u ON u.id = e.created_by
    WHERE e.item_id = :item AND e.business_date BETWEEN :start AND :end
    ORDER BY e.business_date DESC, e.created_at DESC
    """
)


async def expense_item_ledger(
    db: AsyncSession, item_id: uuid.UUID, start: dt.date, end: dt.date
) -> ExpenseItemLedgerOut:
    """Every entry of one expense item in the range: day, who, how much."""
    item = await db.get(ExpenseItem, item_id)
    if item is None:
        raise ExpenseItemNotFound()
    params = {"item": item_id, "start": start, "end": end}
    rows = [
        ExpenseItemEntry(**r) for r in (await db.execute(_EXPENSE_ENTRIES, params)).mappings().all()
    ]
    return ExpenseItemLedgerOut(
        item_id=item.id,
        item_name=item.name,
        start=start,
        end=end,
        rows=rows,
        total=sum((r.amount for r in rows), Decimal(0)),
        count=len(rows),
    )


# ---------------------------------------------------------------- deposits

# Each deposit touches two places: its source (money out) and its destination (money in).
_DEPOSIT_SIDES = """
    SELECT t.id, t.business_date, t.amount, t.created_at,
           t.dest_kind AS kind,
           COALESCE(t.dest_vendor_id, t.dest_bank_account_id, t.dest_person_id) AS ref_id,
           'in' AS direction
    FROM transfers t
    UNION ALL
    SELECT t.id, t.business_date, t.amount, t.created_at,
           t.source_kind, COALESCE(t.source_bank_account_id, t.source_person_id), 'out'
    FROM transfers t
    WHERE t.source_kind <> 'online'
"""

_PLACE_NAMES = """
    CASE s.kind
      WHEN 'cashier_box' THEN 'Cashier box'
      WHEN 'vendor' THEN v.name
      WHEN 'person' THEN p.name
      ELSE b.name || ' · ' || ba.account_type || COALESCE(' (' || ba.label || ')', '')
    END
"""

_PLACE_JOINS = """
    LEFT JOIN vendors v ON s.kind = 'vendor' AND v.id = s.ref_id
    LEFT JOIN people p ON s.kind = 'person' AND p.id = s.ref_id
    LEFT JOIN bank_accounts ba ON s.kind = 'bank_account' AND ba.id = s.ref_id
    LEFT JOIN banks b ON b.id = ba.bank_id
"""

_DEPOSITS = text(
    f"""
    SELECT s.kind, s.ref_id, {_PLACE_NAMES} AS name,
           COALESCE(SUM(s.amount) FILTER (WHERE s.direction = 'in'), 0) AS money_in,
           COALESCE(SUM(s.amount) FILTER (WHERE s.direction = 'out'), 0) AS money_out,
           COUNT(*) AS cnt
    FROM ({_DEPOSIT_SIDES}) s
    {_PLACE_JOINS}
    WHERE s.business_date BETWEEN :start AND :end
    GROUP BY s.kind, s.ref_id, v.name, p.name, b.name, ba.account_type, ba.label
    ORDER BY CASE s.kind WHEN 'cashier_box' THEN 0 WHEN 'bank_account' THEN 1
                         WHEN 'vendor' THEN 2 ELSE 3 END, name
    """
)

_LEDGER = text(
    f"""
    SELECT t.id, t.business_date, t.amount, t.method, t.note, t.created_at, s.direction,
      CASE t.source_kind
        WHEN 'cashier_box' THEN 'Cashier box'
        WHEN 'online' THEN 'Customers (online)'
        WHEN 'person' THEN sp.name
        ELSE sb.name || ' · ' || sba.account_type || COALESCE(' (' || sba.label || ')', '')
      END AS from_label,
      CASE t.dest_kind
        WHEN 'cashier_box' THEN 'Cashier box'
        WHEN 'vendor' THEN dv.name
        WHEN 'person' THEN COALESCE(dp.name, t.dest_person_name)
        ELSE db.name || ' · ' || dba.account_type || COALESCE(' (' || dba.label || ')', '')
      END AS to_label
    FROM ({_DEPOSIT_SIDES}) s
    JOIN transfers t ON t.id = s.id
    LEFT JOIN people sp ON sp.id = t.source_person_id
    LEFT JOIN bank_accounts sba ON sba.id = t.source_bank_account_id
    LEFT JOIN banks sb ON sb.id = sba.bank_id
    LEFT JOIN vendors dv ON dv.id = t.dest_vendor_id
    LEFT JOIN people dp ON dp.id = t.dest_person_id
    LEFT JOIN bank_accounts dba ON dba.id = t.dest_bank_account_id
    LEFT JOIN banks db ON db.id = dba.bank_id
    WHERE s.kind = :kind
      AND (CAST(:ref AS uuid) IS NULL OR s.ref_id = CAST(:ref AS uuid))
      AND s.business_date BETWEEN :start AND :end
    ORDER BY t.business_date, t.created_at
    """
)

_NET_BEFORE = text(
    """
    SELECT COALESCE(SUM(CASE WHEN dest_bank_account_id = :ref THEN amount ELSE -amount END), 0)
    FROM transfers
    WHERE business_date < :start
      AND (dest_bank_account_id = :ref OR source_bank_account_id = :ref)
    """
)

_PLACE_NAME = text(
    f"""
    SELECT {_PLACE_NAMES} AS name
    FROM (SELECT CAST(:kind AS text) AS kind, CAST(:ref AS uuid) AS ref_id) s
    {_PLACE_JOINS}
    """
)


class PlaceNotFound(Exception):
    """No bank account / vendor / person with that id."""


async def deposit_report(db: AsyncSession, start: dt.date, end: dt.date) -> list[DepositReportRow]:
    rows = (await db.execute(_DEPOSITS, {"start": start, "end": end})).mappings().all()
    return [
        DepositReportRow(
            kind=r["kind"],
            ref_id=r["ref_id"],
            name=r["name"] or "—",
            money_in=Decimal(r["money_in"]),
            money_out=Decimal(r["money_out"]),
            count=int(r["cnt"]),
        )
        for r in rows
    ]


async def deposit_ledger(
    db: AsyncSession, kind: str, ref_id: uuid.UUID | None, start: dt.date, end: dt.date
) -> DepositLedgerOut:
    """Every deposit into / out of one place, oldest first. Bank accounts also get the balance
    before ``start`` (opening balance + earlier deposits) and a running balance."""
    if kind == "cashier_box":
        ref_id = None
    elif ref_id is None:
        raise PlaceNotFound()
    ref = str(ref_id) if ref_id else None
    name = await db.scalar(_PLACE_NAME, {"kind": kind, "ref": ref})
    if name is None:
        raise PlaceNotFound()

    opening: Decimal | None = None
    if kind == "bank_account":
        acc = await db.get(BankAccount, ref_id)
        if acc is None:
            raise PlaceNotFound()
        net = await db.scalar(_NET_BEFORE, {"ref": ref_id, "start": start})
        opening = acc.opening_balance + Decimal(net or 0)

    params = {"kind": kind, "ref": ref, "start": start, "end": end}
    rows: list[DepositLedgerRow] = []
    running = opening
    for r in (await db.execute(_LEDGER, params)).mappings().all():
        amount = Decimal(r["amount"])
        if running is not None:
            running += amount if r["direction"] == "in" else -amount
        rows.append(
            DepositLedgerRow(
                id=r["id"],
                business_date=r["business_date"],
                from_label=r["from_label"] or "—",
                to_label=r["to_label"] or "—",
                direction=r["direction"],
                amount=amount,
                method=r["method"],
                note=r["note"],
                balance=running,
                created_at=r["created_at"],
            )
        )
    total_in = sum((x.amount for x in rows if x.direction == "in"), Decimal(0))
    total_out = sum((x.amount for x in rows if x.direction == "out"), Decimal(0))
    return DepositLedgerOut(
        kind=kind,
        ref_id=ref_id,
        name=name,
        start=start,
        end=end,
        opening=opening,
        rows=rows,
        total_in=total_in,
        total_out=total_out,
        closing=None if opening is None else opening + total_in - total_out,
    )
