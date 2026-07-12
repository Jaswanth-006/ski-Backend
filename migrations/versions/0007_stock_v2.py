"""stock v2 — full/empty cylinders, accessories, ac4/erv

Reshapes stock to match how the agency really works: cylinders are tracked as **full**
and **empty** separately, accessories (stove/pipe/wire/regulator) are stocked too, and the
two daily operations are `ac4` (stock received from plant → stock up) and `erv` (empties
returned to plant → empty stock down). Opening/closing per day is derived from the ledger.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Accessories catalog — stocked like cylinders (received via ac4, sold on a sale).
    op.execute(
        """
        CREATE TABLE accessories (
            id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name      TEXT NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """
    )

    # Stock ledger v2: a row references either a cylinder (with full/empty condition) or an
    # accessory, and reasons gain ac4 (received) + erv (empty returned to plant).
    op.execute("ALTER TABLE stock_ledger ADD COLUMN condition TEXT")
    op.execute("ALTER TABLE stock_ledger ADD COLUMN accessory_id UUID REFERENCES accessories(id)")
    op.execute("ALTER TABLE stock_ledger ALTER COLUMN cylinder_type_id DROP NOT NULL")
    # Every existing movement was a full-cylinder movement.
    op.execute("UPDATE stock_ledger SET condition = 'full' WHERE cylinder_type_id IS NOT NULL")

    # The initial schema declared reason as an inline (auto-named) column check.
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS stock_ledger_reason_check")
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason")
    op.execute(
        """
        ALTER TABLE stock_ledger ADD CONSTRAINT ck_stock_ledger_reason
        CHECK (reason IN ('intake','ac4','erv','sale','reversal','adjust'))
        """
    )
    # Exactly one item kind per row; condition only applies to cylinders.
    op.execute(
        """
        ALTER TABLE stock_ledger ADD CONSTRAINT ck_stock_ledger_item CHECK (
            (cylinder_type_id IS NOT NULL AND accessory_id IS NULL
                AND condition IN ('full','empty'))
            OR
            (cylinder_type_id IS NULL AND accessory_id IS NOT NULL AND condition IS NULL)
        )
        """
    )
    op.execute("CREATE INDEX idx_stock_ledger_accessory ON stock_ledger(accessory_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stock_ledger_accessory")
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS ck_stock_ledger_item")
    op.execute("DELETE FROM stock_ledger WHERE accessory_id IS NOT NULL OR condition = 'empty'")
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason")
    op.execute(
        """
        ALTER TABLE stock_ledger ADD CONSTRAINT stock_ledger_reason_check
        CHECK (reason IN ('intake','sale','reversal','adjust'))
        """
    )
    op.execute("ALTER TABLE stock_ledger DROP COLUMN accessory_id")
    op.execute("ALTER TABLE stock_ledger DROP COLUMN condition")
    op.execute("ALTER TABLE stock_ledger ALTER COLUMN cylinder_type_id SET NOT NULL")
    op.execute("DROP TABLE accessories")
