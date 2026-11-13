"""Edit or delete recorded entries: purchase (stock), expenses, deposits, balance entries,
credits. (Sales are corrected through services/sales.py: cancel / edit.)

Rules for every correction:
- a reason is required and the old and new values go to the audit log;
- on a closed day only the owner can change it (both the old and the new date);
- entries a sale created (its balance charge, its route expenses) are changed by editing
  that invoice, so the sale and its parts never disagree.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Credit,
    CustomerBalance,
    DeliveryBalance,
    Expense,
    ExpenseItem,
    Inventory,
    Sale,
    StockLedger,
    Transfer,
    User,
)
from app.schemas.corrections import (
    BalanceEntryEdit,
    BalanceEntryOut,
    CreditEdit,
    ExpenseEdit,
    StockEntryEdit,
    StockEntryLine,
    StockEntryLineOut,
    StockEntryOut,
    TransferEdit,
)
from app.services import audit, day_lock

STOCK_KINDS = ("ac4", "erv", "return", "intake")


class EntryNotFound(Exception):
    pass


class EntryOwnedBySale(Exception):
    """The entry was created by a sale; edit that invoice instead."""

    def __init__(self, invoice_no: str | None) -> None:
        self.invoice_no = invoice_no
        super().__init__(
            f"this was created by invoice {invoice_no or '—'}; edit that invoice instead"
        )


class InvalidEntry(Exception):
    pass


class StockWouldGoNegative(Exception):
    def __init__(self, what: str, available: int) -> None:
        super().__init__(f"not enough {what} in stock for this change ({available} would be left)")


async def _guard_dates(db: AsyncSession, actor: User, *dates: dt.date) -> None:
    for d in set(dates):
        await day_lock.ensure_open(db, d, actor)


async def _invoice_of(db: AsyncSession, sale_id: uuid.UUID | None) -> str | None:
    if sale_id is None:
        return None
    return await db.scalar(select(Sale.invoice_no).where(Sale.id == sale_id))


def _money(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


# ---------------------------------------------------------------- purchase (stock) entries

_ENTRY_ROWS = text(
    """
    SELECT sl.entry_id, sl.reason, sl.business_date, sl.cylinder_type_id, sl.accessory_id,
           sl.condition, sl.delta, sl.note, sl.created_at, u.name AS created_by_name,
           COALESCE(ct.label, a.name, 'item') AS label
    FROM stock_ledger sl
    LEFT JOIN users u ON u.id = sl.created_by
    LEFT JOIN cylinder_types ct ON ct.id = sl.cylinder_type_id
    LEFT JOIN accessories a ON a.id = sl.accessory_id
    WHERE sl.entry_id IS NOT NULL AND sl.reason IN ('ac4', 'erv', 'return', 'intake')
      AND (CAST(:d AS date) IS NULL OR sl.business_date = CAST(:d AS date))
      AND (CAST(:e AS uuid) IS NULL OR sl.entry_id = CAST(:e AS uuid))
    ORDER BY sl.created_at DESC, sl.id
    """
)


def _group(rows: list[Any]) -> list[StockEntryOut]:
    out: dict[uuid.UUID, StockEntryOut] = {}
    for r in rows:
        entry = out.get(r["entry_id"])
        if entry is None:
            entry = StockEntryOut(
                entry_id=r["entry_id"],
                kind=r["reason"],
                business_date=r["business_date"],
                lines=[],
                created_at=r["created_at"],
                created_by_name=r["created_by_name"],
            )
            out[r["entry_id"]] = entry
        entry.lines.append(
            StockEntryLineOut(
                cylinder_type_id=r["cylinder_type_id"],
                accessory_id=r["accessory_id"],
                condition=r["condition"],
                qty=abs(int(r["delta"])),
                note=r["note"],
                label=r["label"],
            )
        )
    return list(out.values())


async def list_stock_entries(db: AsyncSession, on_date: dt.date) -> list[StockEntryOut]:
    rows = (await db.execute(_ENTRY_ROWS, {"d": on_date, "e": None})).mappings().all()
    return _group(list(rows))


async def _get_stock_entry(db: AsyncSession, entry_id: uuid.UUID) -> StockEntryOut:
    rows = (await db.execute(_ENTRY_ROWS, {"d": None, "e": str(entry_id)})).mappings().all()
    entries = _group(list(rows))
    if not entries:
        raise EntryNotFound()
    return entries[0]


def _check_lines(kind: str, lines: list[StockEntryLine]) -> None:
    for line in lines:
        if kind in ("ac4", "intake"):
            if line.cylinder_type_id is not None and line.condition != "full":
                raise InvalidEntry(f"{kind} receives full cylinders")
            if kind == "intake" and line.accessory_id is not None:
                raise InvalidEntry("intake has no accessories")
        elif kind == "erv" and (line.cylinder_type_id is None or line.condition != "empty"):
            raise InvalidEntry("erv sends back empty cylinders only")


def _key(line: Any) -> tuple[Any, Any, Any]:
    return (line.cylinder_type_id, line.accessory_id, line.condition)


_ON_HAND = text(
    """
    SELECT COALESCE(SUM(delta), 0) FROM stock_ledger
    WHERE (CAST(:cyl AS uuid) IS NULL OR cylinder_type_id = CAST(:cyl AS uuid))
      AND (CAST(:acc AS uuid) IS NULL OR accessory_id = CAST(:acc AS uuid))
      AND (CAST(:cond AS text) IS NULL OR condition = CAST(:cond AS text))
    """
)


async def _replace_stock_entry(
    db: AsyncSession,
    entry: StockEntryOut,
    business_date: dt.date | None,
    lines: list[StockEntryLine],
    actor: User,
) -> None:
    """Swap an entry's rows for `lines` (none = delete), keeping stock non-negative."""
    sign = 1 if entry.kind in ("ac4", "intake") else -1
    touched = {_key(line) for line in entry.lines} | {_key(line) for line in lines}
    labels = {_key(x): x.label for x in entry.lines}

    def what(key: tuple[Any, Any, Any]) -> str:
        name = labels.get(key, "item")
        return f"{name} ({key[2]})" if key[2] else name

    # Live full-cylinder inventory (what sales draw from): apply the net change once, and
    # refuse it if it would go below zero (e.g. shrinking an ac4 whose cylinders were sold).
    net: dict[uuid.UUID, int] = {}
    for old in entry.lines:
        if old.cylinder_type_id is not None and old.condition == "full":
            net[old.cylinder_type_id] = net.get(old.cylinder_type_id, 0) - sign * old.qty
    for line in lines:
        if line.cylinder_type_id is not None and line.condition == "full":
            net[line.cylinder_type_id] = net.get(line.cylinder_type_id, 0) + sign * line.qty
    for cyl, change in net.items():
        if change == 0:
            continue
        inv = await db.scalar(
            select(Inventory).where(Inventory.cylinder_type_id == cyl).with_for_update()
        )
        current = inv.quantity if inv is not None else 0
        if current + change < 0:
            raise StockWouldGoNegative(what((cyl, None, "full")), current + change)
        if inv is None:
            db.add(Inventory(cylinder_type_id=cyl, quantity=change, version=0))
        else:
            inv.quantity = current + change
            inv.version += 1

    await db.execute(delete(StockLedger).where(StockLedger.entry_id == entry.entry_id))
    for line in lines:
        db.add(
            StockLedger(
                cylinder_type_id=line.cylinder_type_id,
                accessory_id=line.accessory_id,
                condition=line.condition,
                delta=sign * line.qty,
                reason=entry.kind,
                business_date=business_date or entry.business_date,
                note=line.note,
                entry_id=entry.entry_id,
                created_by=actor.id,
            )
        )
    await db.flush()

    # The ledger (empties, accessories, full) must not end up below zero either.
    for key in touched:
        cyl, acc, cond = key
        params = {"cyl": str(cyl) if cyl else None, "acc": str(acc) if acc else None, "cond": cond}
        on_hand = int(await db.scalar(_ON_HAND, params) or 0)
        if on_hand < 0:
            raise StockWouldGoNegative(what(key), on_hand)


async def edit_stock_entry(
    db: AsyncSession, entry_id: uuid.UUID, data: StockEntryEdit, actor: User
) -> StockEntryOut:
    entry = await _get_stock_entry(db, entry_id)
    await _guard_dates(db, actor, entry.business_date, data.business_date)
    _check_lines(entry.kind, data.lines)
    await _replace_stock_entry(db, entry, data.business_date, data.lines, actor)
    await audit.write(
        db,
        actor.id,
        f"stock.{entry.kind}.edit",
        "stock",
        entry_id,
        old=entry.model_dump(mode="json", include={"business_date", "lines"}),
        new={**data.model_dump(mode="json", exclude={"reason"}), "reason": data.reason},
    )
    await db.commit()
    return await _get_stock_entry(db, entry_id)


async def delete_stock_entry(
    db: AsyncSession, entry_id: uuid.UUID, reason: str, actor: User
) -> None:
    entry = await _get_stock_entry(db, entry_id)
    await _guard_dates(db, actor, entry.business_date)
    await _replace_stock_entry(db, entry, None, [], actor)
    await audit.write(
        db,
        actor.id,
        f"stock.{entry.kind}.delete",
        "stock",
        entry_id,
        old=entry.model_dump(mode="json", include={"business_date", "lines"}),
        new={"reason": reason},
    )
    await db.commit()


# ---------------------------------------------------------------- expenses


async def _load_expense(db: AsyncSession, expense_id: uuid.UUID) -> Expense:
    row = await db.scalar(select(Expense).where(Expense.id == expense_id).with_for_update())
    if row is None:
        raise EntryNotFound()
    if row.sale_id is not None:
        raise EntryOwnedBySale(await _invoice_of(db, row.sale_id))
    return row


def _expense_snapshot(e: Expense) -> dict[str, Any]:
    return {
        "business_date": str(e.business_date),
        "item_id": str(e.item_id),
        "amount": str(e.amount),
        "method": e.method,
        "note": e.note,
        "delivery_id": str(e.delivery_id) if e.delivery_id else None,
    }


async def edit_expense(
    db: AsyncSession, expense_id: uuid.UUID, data: ExpenseEdit, actor: User
) -> uuid.UUID:
    row = await _load_expense(db, expense_id)
    await _guard_dates(db, actor, row.business_date, data.business_date)
    if await db.get(ExpenseItem, data.item_id) is None:
        raise InvalidEntry("expense item not found")
    if data.delivery_id is not None:
        person = await db.get(User, data.delivery_id)
        if person is None or person.role != "delivery":
            raise InvalidEntry("delivery person not found")
    old = _expense_snapshot(row)
    row.business_date = data.business_date
    row.item_id = data.item_id
    row.amount = data.amount
    row.method = data.method
    row.note = data.note
    row.delivery_id = data.delivery_id
    await audit.write(
        db,
        actor.id,
        "expense.edit",
        "expense",
        expense_id,
        old=old,
        new={**_expense_snapshot(row), "reason": data.reason},
    )
    await db.commit()
    return expense_id


async def delete_expense(db: AsyncSession, expense_id: uuid.UUID, reason: str, actor: User) -> None:
    row = await _load_expense(db, expense_id)
    await _guard_dates(db, actor, row.business_date)
    old = _expense_snapshot(row)
    await db.delete(row)
    await audit.write(
        db, actor.id, "expense.delete", "expense", expense_id, old=old, new={"reason": reason}
    )
    await db.commit()


# ---------------------------------------------------------------- deposits (transfers)


async def _load_transfer(db: AsyncSession, transfer_id: uuid.UUID) -> Transfer:
    row = await db.scalar(select(Transfer).where(Transfer.id == transfer_id).with_for_update())
    if row is None:
        raise EntryNotFound()
    return row


def _transfer_snapshot(t: Transfer) -> dict[str, Any]:
    return {
        "business_date": str(t.business_date),
        "amount": str(t.amount),
        "method": t.method,
        "note": t.note,
    }


async def edit_transfer(
    db: AsyncSession, transfer_id: uuid.UUID, data: TransferEdit, actor: User
) -> uuid.UUID:
    row = await _load_transfer(db, transfer_id)
    await _guard_dates(db, actor, row.business_date, data.business_date)
    old = _transfer_snapshot(row)
    row.business_date = data.business_date
    row.amount = data.amount
    row.method = data.method
    row.note = data.note
    await audit.write(
        db,
        actor.id,
        "transfer.edit",
        "transfer",
        transfer_id,
        old=old,
        new={**_transfer_snapshot(row), "reason": data.reason},
    )
    await db.commit()
    return transfer_id


async def delete_transfer(
    db: AsyncSession, transfer_id: uuid.UUID, reason: str, actor: User
) -> None:
    row = await _load_transfer(db, transfer_id)
    await _guard_dates(db, actor, row.business_date)
    old = _transfer_snapshot(row)
    await db.delete(row)
    await audit.write(
        db, actor.id, "transfer.delete", "transfer", transfer_id, old=old, new={"reason": reason}
    )
    await db.commit()


# ---------------------------------------------------------------- balance entries

_BALANCE_ENTRIES = text(
    """
    SELECT db.id, 'delivery' AS party_kind, db.delivery_id AS party_id, u.name AS party_name,
           db.kind, db.amount, db.entry_date, db.method, db.note, s.invoice_no, db.created_at
    FROM delivery_balances db
    JOIN users u ON u.id = db.delivery_id
    LEFT JOIN sales s ON s.id = db.sale_id
    WHERE db.entry_date = :d
    UNION ALL
    SELECT cb.id, 'customer', cb.customer_id, c.name,
           cb.kind, cb.amount, cb.entry_date, cb.method, cb.note, s.invoice_no, cb.created_at
    FROM customer_balances cb
    JOIN customers c ON c.id = cb.customer_id
    LEFT JOIN sales s ON s.id = cb.sale_id
    WHERE cb.entry_date = :d
    ORDER BY created_at DESC
    """
)


async def list_balance_entries(db: AsyncSession, on_date: dt.date) -> list[BalanceEntryOut]:
    rows = (await db.execute(_BALANCE_ENTRIES, {"d": on_date})).mappings().all()
    return [BalanceEntryOut(**r) for r in rows]


async def _load_balance(
    db: AsyncSession, party: str, entry_id: uuid.UUID
) -> DeliveryBalance | CustomerBalance:
    row: DeliveryBalance | CustomerBalance | None
    if party == "delivery":
        row = await db.scalar(
            select(DeliveryBalance).where(DeliveryBalance.id == entry_id).with_for_update()
        )
    else:
        row = await db.scalar(
            select(CustomerBalance).where(CustomerBalance.id == entry_id).with_for_update()
        )
    if row is None:
        raise EntryNotFound()
    if row.sale_id is not None:
        raise EntryOwnedBySale(await _invoice_of(db, row.sale_id))
    return row


def _balance_snapshot(b: DeliveryBalance | CustomerBalance) -> dict[str, Any]:
    return {
        "kind": b.kind,
        "amount": str(b.amount),
        "entry_date": str(b.entry_date),
        "method": b.method,
        "note": b.note,
    }


async def edit_balance_entry(
    db: AsyncSession, party: str, entry_id: uuid.UUID, data: BalanceEntryEdit, actor: User
) -> uuid.UUID:
    row = await _load_balance(db, party, entry_id)
    await _guard_dates(db, actor, row.entry_date, data.entry_date)
    old = _balance_snapshot(row)
    row.entry_date = data.entry_date
    row.amount = data.amount
    row.method = (data.method or row.method or "cash") if row.kind == "repayment" else None
    row.note = data.note
    await audit.write(
        db,
        actor.id,
        f"{party}_balance.edit",
        f"{party}_balance",
        entry_id,
        old=old,
        new={**_balance_snapshot(row), "reason": data.reason},
    )
    await db.commit()
    return entry_id


async def delete_balance_entry(
    db: AsyncSession, party: str, entry_id: uuid.UUID, reason: str, actor: User
) -> None:
    row = await _load_balance(db, party, entry_id)
    await _guard_dates(db, actor, row.entry_date)
    old = _balance_snapshot(row)
    await db.delete(row)
    await audit.write(
        db,
        actor.id,
        f"{party}_balance.delete",
        f"{party}_balance",
        entry_id,
        old=old,
        new={"reason": reason},
    )
    await db.commit()


# ---------------------------------------------------------------- credits


async def _load_credit(db: AsyncSession, credit_id: uuid.UUID) -> Credit:
    row = await db.scalar(select(Credit).where(Credit.id == credit_id).with_for_update())
    if row is None:
        raise EntryNotFound()
    return row


def _credit_snapshot(c: Credit) -> dict[str, Any]:
    return {
        "person_name": c.person_name,
        "amount": _money(c.amount),
        "given_date": str(c.given_date),
        "note": c.note,
    }


async def edit_credit(
    db: AsyncSession, credit_id: uuid.UUID, data: CreditEdit, actor: User
) -> uuid.UUID:
    row = await _load_credit(db, credit_id)
    old = _credit_snapshot(row)
    row.person_name = data.person_name.strip()
    row.amount = data.amount
    row.given_date = data.given_date
    row.note = data.note
    await audit.write(
        db,
        actor.id,
        "credit.edit",
        "credit",
        credit_id,
        old=old,
        new={**_credit_snapshot(row), "reason": data.reason},
    )
    await db.commit()
    return credit_id


async def delete_credit(db: AsyncSession, credit_id: uuid.UUID, reason: str, actor: User) -> None:
    row = await _load_credit(db, credit_id)
    old = _credit_snapshot(row)
    await db.delete(row)
    await audit.write(
        db, actor.id, "credit.delete", "credit", credit_id, old=old, new={"reason": reason}
    )
    await db.commit()
