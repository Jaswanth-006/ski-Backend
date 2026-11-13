"""sale cancel — a posted sale can be cancelled (and so edited by cancel + re-post)

- sales.status gains 'cancelled', with who / when / why.
- The invoice number of a cancelled sale can be used again.
- Balance charges a sale creates now point at the sale (sale_id), so cancelling can remove
  them; existing charges are linked by their "sale balance (uncollected) · invoice …" note.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The original check was created unnamed, so Postgres called it sales_status_check.
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS sales_status_check")
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS ck_sales_status")
    op.execute(
        "ALTER TABLE sales ADD CONSTRAINT ck_sales_status "
        "CHECK (status IN ('pending','approved','rejected','cancelled'))"
    )
    op.execute("ALTER TABLE sales ADD COLUMN cancelled_at TIMESTAMPTZ")
    op.execute("ALTER TABLE sales ADD COLUMN cancelled_by UUID REFERENCES users(id)")
    op.execute("ALTER TABLE sales ADD COLUMN cancel_reason TEXT")

    op.execute("DROP INDEX IF EXISTS uq_sales_invoice_no")
    op.execute(
        "CREATE UNIQUE INDEX uq_sales_invoice_no ON sales(invoice_no) "
        "WHERE invoice_no IS NOT NULL AND status <> 'cancelled'"
    )

    for table, party in (("delivery_balances", "delivery_id"), ("customer_balances", "customer_id")):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN sale_id UUID REFERENCES sales(id) ON DELETE SET NULL"
        )
        op.execute(f"CREATE INDEX idx_{table}_sale ON {table}(sale_id) WHERE sale_id IS NOT NULL")
        op.execute(
            f"""
            UPDATE {table} b SET sale_id = s.id
            FROM sales s
            WHERE b.kind = 'charge' AND b.sale_id IS NULL
              AND s.{party} = b.{party}
              AND b.note = 'sale balance (uncollected) · invoice ' || s.invoice_no
            """
        )


def downgrade() -> None:
    for table in ("delivery_balances", "customer_balances"):
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_sale")
        op.execute(f"ALTER TABLE {table} DROP COLUMN sale_id")
    op.execute("UPDATE sales SET status = 'rejected' WHERE status = 'cancelled'")
    op.execute("DROP INDEX IF EXISTS uq_sales_invoice_no")
    op.execute(
        "CREATE UNIQUE INDEX uq_sales_invoice_no ON sales(invoice_no) WHERE invoice_no IS NOT NULL"
    )
    op.execute("ALTER TABLE sales DROP COLUMN cancel_reason")
    op.execute("ALTER TABLE sales DROP COLUMN cancelled_by")
    op.execute("ALTER TABLE sales DROP COLUMN cancelled_at")
    # The original check was created unnamed, so Postgres called it sales_status_check.
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS sales_status_check")
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS ck_sales_status")
    op.execute(
        "ALTER TABLE sales ADD CONSTRAINT ck_sales_status "
        "CHECK (status IN ('pending','approved','rejected'))"
    )
