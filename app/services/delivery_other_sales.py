"""Per-delivery-boy 'other sales' service (Phase C).

The extra is dated like a price: each row applies from its ``effective_date`` until a later
row, so a back-dated or edited sale uses the extra of its own date.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import business_today
from app.db.models import DeliveryOtherSales
from app.schemas.delivery_other_sales import DeliveryOtherSalesOut

_LIST_SQL = text(
    """
    SELECT u.id AS delivery_id, u.name AS delivery_name,
           COALESCE(d.amount_per_cylinder, 0) AS amount_per_cylinder,
           d.effective_date
    FROM users u
    LEFT JOIN LATERAL (
        SELECT amount_per_cylinder, effective_date FROM delivery_other_sales
        WHERE delivery_id = u.id AND effective_date <= :d
        ORDER BY effective_date DESC LIMIT 1
    ) d ON TRUE
    WHERE u.role = 'delivery' AND (u.is_active = TRUE OR :all)
    ORDER BY u.name
    """
)

_AMOUNT_SQL = text(
    "SELECT amount_per_cylinder FROM delivery_other_sales "
    "WHERE delivery_id = :id AND effective_date <= :d "
    "ORDER BY effective_date DESC LIMIT 1"
)


async def list_all(
    db: AsyncSession, on_date: dt.date | None = None, include_inactive: bool = False
) -> list[DeliveryOtherSalesOut]:
    params = {"d": on_date or business_today(), "all": include_inactive}
    rows = (await db.execute(_LIST_SQL, params)).mappings().all()
    return [DeliveryOtherSalesOut(**row) for row in rows]


async def amount_for(db: AsyncSession, delivery_id: uuid.UUID, on_date: dt.date) -> Decimal:
    """The boy's extra per cylinder that applied on ``on_date``."""
    value = await db.scalar(_AMOUNT_SQL, {"id": delivery_id, "d": on_date})
    return Decimal(value) if value is not None else Decimal(0)


async def set_amount(
    db: AsyncSession,
    delivery_id: uuid.UUID,
    amount: Decimal,
    effective_date: dt.date | None = None,
) -> DeliveryOtherSalesOut:
    """Set the extra from ``effective_date`` (default today); earlier sales keep theirs."""
    day = effective_date or business_today()
    stmt = pg_insert(DeliveryOtherSales).values(
        delivery_id=delivery_id, effective_date=day, amount_per_cylinder=amount
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DeliveryOtherSales.delivery_id, DeliveryOtherSales.effective_date],
        set_={"amount_per_cylinder": amount},
    )
    await db.execute(stmt)
    await db.commit()
    name = await db.scalar(text("SELECT name FROM users WHERE id = :id"), {"id": delivery_id})
    return DeliveryOtherSalesOut(
        delivery_id=delivery_id,
        delivery_name=name or "—",
        amount_per_cylinder=amount,
        effective_date=day,
    )
