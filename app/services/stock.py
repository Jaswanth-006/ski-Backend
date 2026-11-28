"""Stock v2 service — ac4 (received), erv (empty return), return (damaged/lost), overview.

Everything is derived from the append-only ``stock_ledger``. Per day D:
opening = Σ delta before D; closing = Σ delta up to and including D — same pattern as the
cashier box. ``condition`` splits cylinders into full/empty; accessories carry no condition.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import business_today
from app.db.models import Inventory, StockLedger, Transfer, Vendor
from app.schemas.stock import (
    Ac4AccessoryLine,
    Ac4CylinderLine,
    Ac4Purchase,
    AccessoryStockRow,
    CylinderStockRow,
    ErvLine,
    ReturnLine,
    StockOverview,
)
from app.services import audit


class InvalidReference(Exception):
    """A referenced cylinder type or accessory does not exist."""


def purchase_transfer(
    business_date: dt.date,
    amount: Decimal,
    vendor_id: uuid.UUID,
    invoice_no: str | None,
    entry_id: uuid.UUID,
    created_by: uuid.UUID,
) -> Transfer:
    """An ac4 purchase's cost, taken out of the vendor's balance."""
    return Transfer(
        business_date=business_date,
        amount=amount,
        source_kind="vendor",
        source_vendor_id=vendor_id,
        dest_kind="purchase",
        method="balance",
        note=f"ac4 invoice {invoice_no or '—'}",
        stock_entry_id=entry_id,
        created_by=created_by,
    )


class InsufficientStock(Exception):
    """An erv or return asks to take out more than is in stock (on its date or any later)."""

    def __init__(self, what: str, available: int, requested: int, lowest: int = 0) -> None:
        self.what = what
        self.lowest = lowest  # the lowest a day would reach (negative)
        super().__init__(
            f"not enough {what} in stock on that date: {available} available, {requested} asked"
        )


# The lowest stock any day reaches for one item (running total of the ledger by date).
_LOWEST = text(
    """
    WITH daily AS (
        SELECT business_date AS d, SUM(delta) AS s FROM stock_ledger
        WHERE (CAST(:cyl AS uuid) IS NULL OR cylinder_type_id = CAST(:cyl AS uuid))
          AND (CAST(:acc AS uuid) IS NULL OR accessory_id = CAST(:acc AS uuid))
          AND (CAST(:cond AS text) IS NULL OR condition = CAST(:cond AS text))
        GROUP BY business_date
    )
    SELECT COALESCE(MIN(c), 0) FROM (SELECT SUM(s) OVER (ORDER BY d) AS c FROM daily) r
    """
)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtext(:k))")
_NAME = text(
    "SELECT COALESCE((SELECT label FROM cylinder_types WHERE id = CAST(:cyl AS uuid)), "
    "(SELECT name FROM accessories WHERE id = CAST(:acc AS uuid)), 'item')"
)

StockKey = tuple[uuid.UUID | None, uuid.UUID | None, str | None]


def _params(key: StockKey) -> dict[str, str | None]:
    cyl, acc, cond = key
    return {"cyl": str(cyl) if cyl else None, "acc": str(acc) if acc else None, "cond": cond}


async def lock_stock(db: AsyncSession, keys: set[StockKey]) -> dict[StockKey, int]:
    """Lock each item's stock for this transaction (so two entries can't both take the last
    empties) and return the lowest level any day reaches now, to compare after the change."""
    lowest: dict[StockKey, int] = {}
    for key in sorted(keys, key=str):  # one order everywhere: no deadlocks
        await db.execute(_LOCK, {"k": f"stock:{key[0]}:{key[1]}:{key[2]}"})
        lowest[key] = int(await db.scalar(_LOWEST, _params(key)) or 0)
    return lowest


async def ensure_no_day_negative(
    db: AsyncSession, before: dict[StockKey, int], asked: dict[StockKey, int]
) -> None:
    """After writing an entry's rows: no day may drop below zero because of it.

    Checks every date, not just the entry's own: an erv back-dated to before the empties came
    in, or one that takes empties a later erv already sent, is refused.
    """
    await db.flush()
    for key, low_before in before.items():
        low = int(await db.scalar(_LOWEST, _params(key)) or 0)
        if low < 0 and low < low_before:
            name = await db.scalar(_NAME, _params(key)) or "item"
            what = f"{name} ({key[2]})" if key[2] else str(name)
            qty = asked.get(key, 0)
            raise InsufficientStock(what, max(qty + low, 0), qty, low)


async def record_ac4(
    db: AsyncSession,
    *,
    cylinders: Sequence[Ac4CylinderLine],
    accessories: Sequence[Ac4AccessoryLine],
    created_by: uuid.UUID,
    invoice_no: str,
    business_date: dt.date | None = None,
    purchase: Ac4Purchase | None = None,
) -> None:
    """Stock received from the plant: full cylinders and/or accessories added to stock.

    With ``purchase`` its cost is taken from the money already deposited with the vendor
    (a transfer vendor → purchase, linked to this entry). The balance may go below zero —
    the page warns first. The same invoice number may be used on more than one entry.
    """
    bd = business_date or business_today()
    if purchase is not None and await db.get(Vendor, purchase.vendor_id) is None:
        raise InvalidReference("invalid vendor")
    entry_id = uuid.uuid4()  # groups this entry's rows for later edit / delete
    try:
        for line in cylinders:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    condition="full",
                    delta=line.qty,
                    reason="ac4",
                    entry_id=entry_id,
                    invoice_no=invoice_no,
                    business_date=bd,
                    created_by=created_by,
                )
            )
            # Keep the live full-cylinder inventory in step for the /inventory view.
            stmt = pg_insert(Inventory).values(
                cylinder_type_id=line.cylinder_type_id, quantity=line.qty, version=0
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[Inventory.cylinder_type_id],
                set_={
                    "quantity": Inventory.quantity + line.qty,
                    "version": Inventory.version + 1,
                },
            )
            await db.execute(stmt)
        for acc in accessories:
            db.add(
                StockLedger(
                    accessory_id=acc.accessory_id,
                    delta=acc.qty,
                    reason="ac4",
                    entry_id=entry_id,
                    invoice_no=invoice_no,
                    business_date=bd,
                    created_by=created_by,
                )
            )
        if purchase is not None:
            db.add(
                purchase_transfer(
                    bd, purchase.amount, purchase.vendor_id, invoice_no, entry_id, created_by
                )
            )
        await audit.write(
            db,
            created_by,
            "stock.ac4",
            "stock",
            str(bd),
            new={
                "invoice_no": invoice_no,
                "purchase": purchase.model_dump(mode="json") if purchase else None,
                "cylinders": [
                    {"cylinder_type_id": str(x.cylinder_type_id), "qty": x.qty} for x in cylinders
                ],
                "accessories": [
                    {"accessory_id": str(x.accessory_id), "qty": x.qty} for x in accessories
                ],
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidReference("one or more cylinder types or accessories are invalid") from exc


async def record_erv(
    db: AsyncSession,
    *,
    lines: Sequence[ErvLine],
    created_by: uuid.UUID,
    business_date: dt.date | None = None,
) -> None:
    """Empty cylinders returned to the plant: reduces empty stock."""
    bd = business_date or business_today()
    entry_id = uuid.uuid4()  # groups this entry's rows for later edit / delete
    wanted: dict[StockKey, int] = {}
    for line in lines:
        key: StockKey = (line.cylinder_type_id, None, "empty")
        wanted[key] = wanted.get(key, 0) + line.qty
    before = await lock_stock(db, set(wanted))
    try:
        for line in lines:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    condition="empty",
                    delta=-line.qty,
                    reason="erv",
                    entry_id=entry_id,
                    business_date=bd,
                    created_by=created_by,
                )
            )
        await ensure_no_day_negative(db, before, wanted)
        await audit.write(
            db,
            created_by,
            "stock.erv",
            "stock",
            str(bd),
            new={
                "lines": [
                    {"cylinder_type_id": str(x.cylinder_type_id), "qty": x.qty} for x in lines
                ]
            },
        )
        await db.commit()
    except InsufficientStock:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidReference("one or more cylinder types are invalid") from exc


async def record_return(
    db: AsyncSession,
    *,
    lines: Sequence[ReturnLine],
    created_by: uuid.UUID,
    business_date: dt.date | None = None,
) -> None:
    """Damaged or lost items written out of stock (cylinders full/empty, or accessories)."""
    bd = business_date or business_today()
    entry_id = uuid.uuid4()  # groups this entry's rows for later edit / delete
    wanted: dict[StockKey, int] = {}
    for line in lines:
        key: StockKey = (line.cylinder_type_id, line.accessory_id, line.condition)
        wanted[key] = wanted.get(key, 0) + line.qty
    try:
        # Lock these items' stock; full cylinders are also checked against the live
        # inventory (what sales draw from) below.
        before = await lock_stock(db, set(wanted))
        for line in lines:
            if line.cylinder_type_id is not None and line.condition == "full":
                # Full cylinders also live in the inventory table that sales draw from.
                inv = await db.scalar(
                    select(Inventory)
                    .where(Inventory.cylinder_type_id == line.cylinder_type_id)
                    .with_for_update()
                )
                if inv is None or inv.quantity < line.qty:
                    name = await db.scalar(_NAME, {"cyl": str(line.cylinder_type_id), "acc": None})
                    raise InsufficientStock(f"{name} (full)", inv.quantity if inv else 0, line.qty)
                inv.quantity -= line.qty
                inv.version += 1
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    accessory_id=line.accessory_id,
                    condition=line.condition,
                    delta=-line.qty,
                    reason="return",
                    entry_id=entry_id,
                    business_date=bd,
                    note=line.note,
                    created_by=created_by,
                )
            )
        await ensure_no_day_negative(db, before, wanted)
        await audit.write(
            db,
            created_by,
            "stock.return",
            "stock",
            str(bd),
            new={
                "lines": [
                    {
                        "cylinder_type_id": str(x.cylinder_type_id) if x.cylinder_type_id else None,
                        "accessory_id": str(x.accessory_id) if x.accessory_id else None,
                        "condition": x.condition,
                        "qty": x.qty,
                        "note": x.note,
                    }
                    for x in lines
                ]
            },
        )
        await db.commit()
    except InsufficientStock:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidReference("one or more cylinder types or accessories are invalid") from exc


_CYL_OVERVIEW = text(
    """
    SELECT ct.id AS cylinder_type_id, ct.code, ct.label,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.condition = 'full' AND sl.business_date < :d), 0) AS full_opening,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.condition = 'full' AND sl.business_date <= :d), 0) AS full_closing,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.condition = 'full' AND sl.business_date = :d AND sl.reason = 'ac4'), 0)
            AS full_received,
        COALESCE(-SUM(sl.delta) FILTER (
            WHERE sl.condition = 'full' AND sl.business_date = :d AND sl.reason = 'sale'), 0)
            AS full_sold,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.condition = 'empty' AND sl.business_date < :d), 0) AS empty_opening,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.condition = 'empty' AND sl.business_date <= :d), 0) AS empty_closing,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.condition = 'empty' AND sl.business_date = :d AND sl.reason = 'sale'), 0)
            AS empty_returned_by_customers,
        COALESCE(-SUM(sl.delta) FILTER (
            WHERE sl.condition = 'empty' AND sl.business_date = :d AND sl.reason = 'erv'), 0)
            AS empty_sent_to_plant
    FROM cylinder_types ct
    LEFT JOIN stock_ledger sl ON sl.cylinder_type_id = ct.id
    WHERE ct.is_active = TRUE
    GROUP BY ct.id, ct.code, ct.label
    ORDER BY ct.code
    """
)

_ACC_OVERVIEW = text(
    """
    SELECT a.id AS accessory_id, a.name,
        COALESCE(SUM(sl.delta) FILTER (WHERE sl.business_date < :d), 0) AS opening,
        COALESCE(SUM(sl.delta) FILTER (WHERE sl.business_date <= :d), 0) AS closing,
        COALESCE(SUM(sl.delta) FILTER (
            WHERE sl.business_date = :d AND sl.reason = 'ac4'), 0) AS received,
        COALESCE(-SUM(sl.delta) FILTER (
            WHERE sl.business_date = :d AND sl.reason = 'sale'), 0) AS sold
    FROM accessories a
    LEFT JOIN stock_ledger sl ON sl.accessory_id = a.id
    WHERE a.is_active = TRUE
    GROUP BY a.id, a.name
    ORDER BY a.name
    """
)


async def overview(db: AsyncSession, on_date: dt.date) -> StockOverview:
    params = {"d": on_date}
    cyl_rows = (await db.execute(_CYL_OVERVIEW, params)).mappings().all()
    acc_rows = (await db.execute(_ACC_OVERVIEW, params)).mappings().all()
    return StockOverview(
        business_date=on_date,
        cylinders=[CylinderStockRow(**row) for row in cyl_rows],
        accessories=[AccessoryStockRow(**row) for row in acc_rows],
    )
