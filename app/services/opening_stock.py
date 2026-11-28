"""Opening stock (Master Catalog).

Saved as ``stock_ledger`` rows with reason 'opening', dated the day *before* ``as_of`` so they
are the stock at the start of ``as_of`` — every opening figure, report and stock check then
includes them like any other stock. Saving again replaces them. Full cylinders also move the
live ``inventory`` count that sales check.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Inventory, StockLedger, User
from app.schemas.opening_stock import OpeningStockLine, OpeningStockOut, OpeningStockRow
from app.services import audit, stock


class OpeningWouldGoNegative(Exception):
    def __init__(self, what: str) -> None:
        super().__init__(
            f"lowering the opening {what} would leave stock below zero on a later day — "
            "the sales and erv already entered need it"
        )


class InvalidItem(Exception):
    pass


_ROWS = text(
    """
    SELECT ct.id AS cylinder_type_id, NULL::uuid AS accessory_id, c.condition, ct.label,
           ct.code AS sort, COALESCE(SUM(sl.delta), 0) AS qty
    FROM cylinder_types ct
    CROSS JOIN (VALUES ('full'), ('empty')) AS c(condition)
    LEFT JOIN stock_ledger sl ON sl.reason = 'opening' AND sl.cylinder_type_id = ct.id
                              AND sl.condition = c.condition
    WHERE ct.is_active
    GROUP BY ct.id, ct.label, ct.code, c.condition
    UNION ALL
    SELECT NULL::uuid, a.id, NULL, a.name, '~' || a.name, COALESCE(SUM(sl.delta), 0)
    FROM accessories a
    LEFT JOIN stock_ledger sl ON sl.reason = 'opening' AND sl.accessory_id = a.id
    WHERE a.is_active
    GROUP BY a.id, a.name
    ORDER BY sort, condition DESC
    """
)
_AS_OF = text("SELECT MAX(business_date) FROM stock_ledger WHERE reason = 'opening'")
_VALID_CYL = text("SELECT id FROM cylinder_types")
_VALID_ACC = text("SELECT id FROM accessories")


async def get_opening(db: AsyncSession) -> OpeningStockOut:
    stored = await db.scalar(_AS_OF)
    rows = [
        OpeningStockRow(
            cylinder_type_id=r["cylinder_type_id"],
            accessory_id=r["accessory_id"],
            condition=r["condition"],
            label=r["label"],
            qty=int(r["qty"]),
        )
        for r in (await db.execute(_ROWS)).mappings().all()
    ]
    return OpeningStockOut(as_of=stored + dt.timedelta(days=1) if stored else None, rows=rows)


def _key(line: OpeningStockLine) -> stock.StockKey:
    return (line.cylinder_type_id, line.accessory_id, line.condition)


async def set_opening(
    db: AsyncSession,
    as_of: dt.date,
    lines: Sequence[OpeningStockLine],
    actor: User,
    reason: str | None = None,
) -> OpeningStockOut:
    cyl_ids = set((await db.scalars(_VALID_CYL)).all())
    acc_ids = set((await db.scalars(_VALID_ACC)).all())
    for line in lines:
        if line.cylinder_type_id is not None and line.cylinder_type_id not in cyl_ids:
            raise InvalidItem("unknown cylinder type")
        if line.accessory_id is not None and line.accessory_id not in acc_ids:
            raise InvalidItem("unknown accessory")

    old_rows = list(await db.scalars(select(StockLedger).where(StockLedger.reason == "opening")))
    old: dict[stock.StockKey, int] = defaultdict(int)
    for r in old_rows:
        old[(r.cylinder_type_id, r.accessory_id, r.condition)] += r.delta
    new: dict[stock.StockKey, int] = defaultdict(int)
    for line in lines:
        new[_key(line)] += line.qty

    touched = set(old) | set(new)
    before = await stock.lock_stock(db, touched)

    await db.execute(delete(StockLedger).where(StockLedger.reason == "opening"))
    day = as_of - dt.timedelta(days=1)
    for key, qty in new.items():
        if qty > 0:
            db.add(
                StockLedger(
                    cylinder_type_id=key[0],
                    accessory_id=key[1],
                    condition=key[2],
                    delta=qty,
                    reason="opening",
                    business_date=day,
                    note="opening stock",
                    created_by=actor.id,
                )
            )

    # Full cylinders: keep the live count that sales check in step.
    for key in touched:
        cyl, _acc, cond = key
        change = new.get(key, 0) - old.get(key, 0)
        if cyl is None or cond != "full" or change == 0:
            continue
        inv = await db.scalar(
            select(Inventory).where(Inventory.cylinder_type_id == cyl).with_for_update()
        )
        current = inv.quantity if inv is not None else 0
        if current + change < 0:
            raise OpeningWouldGoNegative("full cylinders")
        if inv is None:
            db.add(Inventory(cylinder_type_id=cyl, quantity=change, version=0))
        else:
            inv.quantity = current + change
            inv.version += 1

    try:
        await stock.ensure_no_day_negative(db, before, {})
    except stock.InsufficientStock as exc:
        raise OpeningWouldGoNegative(exc.what) from exc

    await audit.write(
        db,
        actor.id,
        "stock.opening",
        "stock",
        "opening",
        old={"items": {str(k): v for k, v in old.items() if v}},
        new={
            "as_of": str(as_of),
            "items": {str(k): v for k, v in new.items() if v},
            "reason": reason,
        },
    )
    await db.commit()
    return await get_opening(db)
