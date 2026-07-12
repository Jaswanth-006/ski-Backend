"""delivery other sales

A per-delivery-boy extra charged on top of the fixed cylinder price (boy1 ₹20/cyl,
boy2 ₹10/cyl …). It is agency money the boy must settle, so a sale line total becomes
(base_price + boy_extra) × qty. The extra is snapshotted onto each sale line.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE delivery_other_sales (
            delivery_id         UUID PRIMARY KEY REFERENCES users(id),
            amount_per_cylinder NUMERIC(10,2) NOT NULL DEFAULT 0
                CHECK (amount_per_cylinder >= 0)
        )
        """
    )
    op.execute(
        "ALTER TABLE sale_lines ADD COLUMN other_sales_per_unit NUMERIC(10,2) NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sale_lines DROP COLUMN other_sales_per_unit")
    op.execute("DROP TABLE delivery_other_sales")
