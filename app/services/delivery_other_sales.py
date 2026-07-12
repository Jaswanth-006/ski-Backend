"""Per-delivery-boy 'other sales' service (Phase C)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeliveryOtherSales
from app.schemas.delivery_other_sales import DeliveryOtherSalesOut

_LIST_SQL = text(
    """
    SELECT u.id AS delivery_id, u.name AS delivery_name,
           COALESCE(d.amount_per_cylinder, 0) AS amount_per_cylinder
    FROM users u
    LEFT JOIN delivery_other_sales d ON d.delivery_id = u.id
    WHERE u.role = 'delivery' AND u.is_active = TRUE
    ORDER BY u.name
    """
)


async def list_all(db: AsyncSession) -> list[DeliveryOtherSalesOut]:
    rows = (await db.execute(_LIST_SQL)).mappings().all()
    return [DeliveryOtherSalesOut(**row) for row in rows]


async def amount_for(db: AsyncSession, delivery_id: uuid.UUID) -> Decimal:
    row = await db.get(DeliveryOtherSales, delivery_id)
    return row.amount_per_cylinder if row else Decimal(0)


async def set_amount(
    db: AsyncSession, delivery_id: uuid.UUID, amount: Decimal
) -> DeliveryOtherSalesOut:
    stmt = pg_insert(DeliveryOtherSales).values(delivery_id=delivery_id, amount_per_cylinder=amount)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DeliveryOtherSales.delivery_id],
        set_={"amount_per_cylinder": amount},
    )
    await db.execute(stmt)
    await db.commit()
    name = await db.scalar(text("SELECT name FROM users WHERE id = :id"), {"id": delivery_id})
    return DeliveryOtherSalesOut(
        delivery_id=delivery_id, delivery_name=name or "—", amount_per_cylinder=amount
    )
