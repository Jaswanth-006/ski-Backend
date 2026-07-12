"""Stock v2 service — ac4 (received), erv (empty return), and the daily overview.

Everything is derived from the append-only ``stock_ledger``. Per day D:
opening = Σ delta before D; closing = Σ delta up to and including D — same pattern as the
cashier box. ``condition`` splits cylinders into full/empty; accessories carry no condition.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Inventory, StockLedger
from app.schemas.stock import (
    Ac4AccessoryLine,
    Ac4CylinderLine,
    AccessoryStockRow,
    CylinderStockRow,
    ErvLine,
    StockOverview,
)


class InvalidReference(Exception):
    """A referenced cylinder type or accessory does not exist."""


async def record_ac4(
    db: AsyncSession,
    *,
    cylinders: Sequence[Ac4CylinderLine],
    accessories: Sequence[Ac4AccessoryLine],
    created_by: uuid.UUID,
    business_date: dt.date | None = None,
) -> None:
    """Stock received from the plant: full cylinders and/or accessories added to stock."""
    bd = business_date or dt.date.today()
    try:
        for line in cylinders:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    condition="full",
                    delta=line.qty,
                    reason="ac4",
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
                    business_date=bd,
                    created_by=created_by,
                )
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
    bd = business_date or dt.date.today()
    try:
        for line in lines:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    condition="empty",
                    delta=-line.qty,
                    reason="erv",
                    business_date=bd,
                    created_by=created_by,
                )
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidReference("one or more cylinder types are invalid") from exc


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
