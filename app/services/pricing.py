"""Temporal pricing service (Phase 1-E; 01-BACKEND-PRD §5).

A price is effective-dated. Resolving a date returns the price whose `effective_date`
is the latest on/before that date — so a day sheet reopened later recomputes at *that
day's* price. Setting a price for a (type, date) upserts the row.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Price
from app.schemas.pricing import PriceBulkItem, PriceOut


class InvalidCylinderType(Exception):
    """A referenced cylinder type does not exist."""


_RESOLVE_SQL = text(
    """
    SELECT ct.id AS cylinder_type_id, ct.code, ct.label,
           p.unit_price, p.effective_date
    FROM cylinder_types ct
    LEFT JOIN LATERAL (
        SELECT unit_price, effective_date
        FROM prices
        WHERE cylinder_type_id = ct.id AND effective_date <= :on_date
        ORDER BY effective_date DESC
        LIMIT 1
    ) p ON TRUE
    WHERE ct.is_active = TRUE
    ORDER BY ct.code
    """
)


async def prices_for_date(db: AsyncSession, on_date: dt.date) -> list[PriceOut]:
    rows = (await db.execute(_RESOLVE_SQL, {"on_date": on_date})).mappings().all()
    return [PriceOut(**row) for row in rows]


async def _upsert(
    db: AsyncSession,
    cylinder_type_id: uuid.UUID,
    unit_price: object,
    effective_date: dt.date,
    created_by: uuid.UUID,
) -> None:
    stmt = pg_insert(Price).values(
        cylinder_type_id=cylinder_type_id,
        unit_price=unit_price,
        effective_date=effective_date,
        created_by=created_by,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Price.cylinder_type_id, Price.effective_date],
        set_={"unit_price": stmt.excluded.unit_price, "created_by": stmt.excluded.created_by},
    )
    await db.execute(stmt)


async def set_price(
    db: AsyncSession,
    cylinder_type_id: uuid.UUID,
    unit_price: object,
    effective_date: dt.date,
    created_by: uuid.UUID,
) -> None:
    try:
        await _upsert(db, cylinder_type_id, unit_price, effective_date, created_by)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidCylinderType(str(cylinder_type_id)) from exc


async def set_prices_bulk(
    db: AsyncSession,
    effective_date: dt.date,
    items: Sequence[PriceBulkItem],
    created_by: uuid.UUID,
) -> None:
    """Set every supplied variety's price for one date in a single transaction."""
    try:
        for item in items:
            await _upsert(db, item.cylinder_type_id, item.unit_price, effective_date, created_by)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidCylinderType("one or more cylinder types are invalid") from exc
