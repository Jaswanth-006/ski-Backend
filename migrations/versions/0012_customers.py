"""customers — corporate buyers who take directly from the warehouse

A sale is now attributed to EITHER a delivery boy OR a customer (corporate buyer with
no delivery boy). Customers are master data like vendors.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE customers (
            id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name      TEXT NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """
    )
    op.execute("ALTER TABLE sales ALTER COLUMN delivery_id DROP NOT NULL")
    op.execute("ALTER TABLE sales ADD COLUMN customer_id UUID REFERENCES customers(id)")
    # Exactly one party per sale.
    op.execute(
        """
        ALTER TABLE sales ADD CONSTRAINT ck_sales_party CHECK (
            (delivery_id IS NOT NULL AND customer_id IS NULL)
            OR (delivery_id IS NULL AND customer_id IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX idx_sales_customer ON sales(customer_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sales_customer")
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS ck_sales_party")
    op.execute("DELETE FROM sales WHERE customer_id IS NOT NULL")
    op.execute("ALTER TABLE sales DROP COLUMN customer_id")
    op.execute("ALTER TABLE sales ALTER COLUMN delivery_id SET NOT NULL")
    op.execute("DROP TABLE customers")
