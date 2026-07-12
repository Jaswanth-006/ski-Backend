"""Per-driver stock load/return + warehouse opening/closing (Phase 8-D).

Warehouse on-hand still equals intake − sale (unchanged); the load/return log is a
reconciliation layer: each driver loads out cylinders, sells some, returns the rest.
Warehouse opening/closing per business date is derived from the (now date-stamped) stock
ledger, so today's closing is tomorrow's opening.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CylinderType, StockLoad, User
from app.schemas.stock_loads import StockLoadOut, StockLoadUpsert


class InvalidReference(Exception):
    """A referenced delivery person or cylinder type does not exist."""


async def upsert_load(
    db: AsyncSession, data: StockLoadUpsert, created_by: uuid.UUID
) -> StockLoadOut:
    stmt = (
        pg_insert(StockLoad)
        .values(
            business_date=data.business_date,
            delivery_id=data.delivery_id,
            cylinder_type_id=data.cylinder_type_id,
            loaded_qty=data.loaded_qty,
            returned_qty=data.returned_qty,
            created_by=created_by,
        )
        .on_conflict_do_update(
            constraint="uq_stock_loads_day",
            set_={"loaded_qty": data.loaded_qty, "returned_qty": data.returned_qty},
        )
        .returning(StockLoad.id)
    )
    try:
        load_id = (await db.execute(stmt)).scalar_one()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidReference("driver or cylinder type") from exc

    row = (
        await db.execute(
            select(StockLoad, User.name, CylinderType.code)
            .join(User, User.id == StockLoad.delivery_id)
            .join(CylinderType, CylinderType.id == StockLoad.cylinder_type_id)
            .where(StockLoad.id == load_id)
        )
    ).one()
    load, name, code = row
    return StockLoadOut(
        id=load.id,
        business_date=load.business_date,
        delivery_id=load.delivery_id,
        delivery_name=name,
        cylinder_type_id=load.cylinder_type_id,
        code=code,
        loaded_qty=load.loaded_qty,
        returned_qty=load.returned_qty,
    )


async def list_loads(db: AsyncSession, on_date: dt.date) -> list[StockLoadOut]:
    rows = (
        await db.execute(
            select(StockLoad, User.name, CylinderType.code)
            .join(User, User.id == StockLoad.delivery_id)
            .join(CylinderType, CylinderType.id == StockLoad.cylinder_type_id)
            .where(StockLoad.business_date == on_date)
            .order_by(User.name, CylinderType.code)
        )
    ).all()
    return [
        StockLoadOut(
            id=load.id,
            business_date=load.business_date,
            delivery_id=load.delivery_id,
            delivery_name=name,
            cylinder_type_id=load.cylinder_type_id,
            code=code,
            loaded_qty=load.loaded_qty,
            returned_qty=load.returned_qty,
        )
        for load, name, code in rows
    ]


_WAREHOUSE = text(
    "SELECT COALESCE(SUM(delta), 0) FROM stock_ledger "
    "WHERE business_date <= :bound AND condition = 'full'"
)
_INTAKE_ON = text(
    "SELECT COALESCE(SUM(delta), 0) FROM stock_ledger "
    "WHERE business_date = :d AND reason = 'intake'"
)


async def warehouse_opening_closing(db: AsyncSession, on_date: dt.date) -> tuple[int, int]:
    """(opening, closing) total warehouse cylinders across all types for a date."""
    opening = int(await db.scalar(_WAREHOUSE, {"bound": on_date - dt.timedelta(days=1)}) or 0)
    closing = int(await db.scalar(_WAREHOUSE, {"bound": on_date}) or 0)
    return opening, closing


async def intake_total(db: AsyncSession, on_date: dt.date) -> int:
    return int(await db.scalar(_INTAKE_ON, {"d": on_date}) or 0)


async def loads_by_driver(db: AsyncSession, on_date: dt.date) -> dict[uuid.UUID, tuple[int, int]]:
    """{delivery_id: (loaded, returned)} summed across cylinder types for a date."""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT delivery_id, COALESCE(SUM(loaded_qty),0) AS loaded, "
                    "COALESCE(SUM(returned_qty),0) AS returned FROM stock_loads "
                    "WHERE business_date = :d GROUP BY delivery_id"
                ),
                {"d": on_date},
            )
        )
        .mappings()
        .all()
    )
    return {r["delivery_id"]: (int(r["loaded"]), int(r["returned"])) for r in rows}
