"""Stock & inventory service (Phase 2).

Morning intake is one transaction: for each line, append an immutable `stock_ledger`
row (reason=intake) and upsert live `inventory` (quantity += qty, version += 1). The
ledger is append-only (01-BACKEND-PRD §6.1); inventory carries a `version` for
optimistic locking (Phase 2-B).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CylinderType, Inventory, StockLedger
from app.schemas.inventory import InventoryOut, StockIntakeLine


class InvalidCylinderType(Exception):
    """A referenced cylinder type does not exist."""


class StaleVersion(Exception):
    """The submitted inventory version is stale (someone else changed it first)."""

    def __init__(self, current: int) -> None:
        self.current = current
        super().__init__(f"stale version; current is {current}")


_LIST_SQL = text(
    """
    SELECT ct.id AS cylinder_type_id, ct.code, ct.label,
           COALESCE(i.quantity, 0) AS quantity,
           COALESCE(i.version, 0)  AS version
    FROM cylinder_types ct
    LEFT JOIN inventory i ON i.cylinder_type_id = ct.id
    WHERE ct.is_active = TRUE
    ORDER BY ct.code
    """
)


async def list_inventory(db: AsyncSession) -> list[InventoryOut]:
    rows = (await db.execute(_LIST_SQL)).mappings().all()
    return [InventoryOut(**row) for row in rows]


async def record_intake(
    db: AsyncSession, lines: Sequence[StockIntakeLine], created_by: uuid.UUID
) -> None:
    try:
        for line in lines:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    delta=line.qty,
                    reason="intake",
                    created_by=created_by,
                )
            )
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
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidCylinderType("one or more cylinder types are invalid") from exc


async def adjust_inventory(
    db: AsyncSession,
    cylinder_type_id: uuid.UUID,
    new_quantity: int,
    expected_version: int,
    created_by: uuid.UUID,
) -> InventoryOut | None:
    """Correct a count with optimistic locking (Phase 2-B). Returns None if there is no
    inventory row yet; raises StaleVersion if the submitted version is out of date."""
    inv = await db.get(Inventory, cylinder_type_id)
    if inv is None:
        return None
    if inv.version != expected_version:
        raise StaleVersion(inv.version)

    delta = new_quantity - inv.quantity
    inv.quantity = new_quantity
    inv.version = expected_version + 1
    db.add(
        StockLedger(
            cylinder_type_id=cylinder_type_id,
            delta=delta,
            reason="adjust",
            created_by=created_by,
        )
    )
    await db.commit()

    ct = await db.get(CylinderType, cylinder_type_id)
    assert ct is not None
    return InventoryOut(
        cylinder_type_id=cylinder_type_id,
        code=ct.code,
        label=ct.label,
        quantity=inv.quantity,
        version=inv.version,
    )
