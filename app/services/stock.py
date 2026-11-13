"""Stock v2 service — ac4 (received), erv (empty return), return (damaged/lost), overview.

Everything is derived from the append-only ``stock_ledger``. Per day D:
opening = Σ delta before D; closing = Σ delta up to and including D — same pattern as the
cashier box. ``condition`` splits cylinders into full/empty; accessories carry no condition.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import business_today
from app.db.models import Inventory, StockLedger
from app.schemas.stock import (
    Ac4AccessoryLine,
    Ac4CylinderLine,
    AccessoryStockRow,
    CylinderStockRow,
    ErvLine,
    ReturnLine,
    StockOverview,
)
from app.services import audit


class InvalidReference(Exception):
    """A referenced cylinder type or accessory does not exist."""


class InsufficientStock(Exception):
    """An erv or return asks to take out more than is in stock."""

    def __init__(self, what: str, available: int, requested: int) -> None:
        super().__init__(f"not enough {what} in stock: {available} available, {requested} asked")


_AVAILABLE = text(
    """
    SELECT COALESCE(SUM(delta), 0) FROM stock_ledger
    WHERE (CAST(:cyl AS uuid) IS NULL OR cylinder_type_id = CAST(:cyl AS uuid))
      AND (CAST(:acc AS uuid) IS NULL OR accessory_id = CAST(:acc AS uuid))
      AND (CAST(:cond AS text) IS NULL OR condition = CAST(:cond AS text))
    """
)
_NAME = text(
    "SELECT COALESCE((SELECT label FROM cylinder_types WHERE id = CAST(:cyl AS uuid)), "
    "(SELECT name FROM accessories WHERE id = CAST(:acc AS uuid)), 'item')"
)


async def _ensure_available(
    db: AsyncSession,
    wanted: dict[tuple[uuid.UUID | None, uuid.UUID | None, str | None], int],
) -> None:
    """Empties and accessories must be on hand (all dates) before they leave stock."""
    for (cyl, acc, cond), qty in wanted.items():
        params = {
            "cyl": str(cyl) if cyl else None,
            "acc": str(acc) if acc else None,
            "cond": cond,
        }
        available = int(await db.scalar(_AVAILABLE, params) or 0)
        if available < qty:
            name = await db.scalar(_NAME, params) or "item"
            what = f"{name} ({cond})" if cond else str(name)
            raise InsufficientStock(what, available, qty)


async def record_ac4(
    db: AsyncSession,
    *,
    cylinders: Sequence[Ac4CylinderLine],
    accessories: Sequence[Ac4AccessoryLine],
    created_by: uuid.UUID,
    business_date: dt.date | None = None,
) -> None:
    """Stock received from the plant: full cylinders and/or accessories added to stock."""
    bd = business_date or business_today()
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
                    business_date=bd,
                    created_by=created_by,
                )
            )
        await audit.write(
            db,
            created_by,
            "stock.ac4",
            "stock",
            str(bd),
            new={
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
    wanted: dict[tuple[uuid.UUID | None, uuid.UUID | None, str | None], int] = {}
    for line in lines:
        key = (line.cylinder_type_id, None, "empty")
        wanted[key] = wanted.get(key, 0) + line.qty
    await _ensure_available(db, wanted)
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
    wanted: dict[tuple[uuid.UUID | None, uuid.UUID | None, str | None], int] = {}
    for line in lines:
        if line.cylinder_type_id is not None and line.condition == "full":
            continue  # full cylinders are checked against the live inventory below
        key = (line.cylinder_type_id, line.accessory_id, line.condition)
        wanted[key] = wanted.get(key, 0) + line.qty
    await _ensure_available(db, wanted)
    try:
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
