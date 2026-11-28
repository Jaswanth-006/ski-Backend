"""Sale invoice numbers may repeat

The unique index on sales.invoice_no is replaced by a plain index (still used to find a sale
by its invoice number).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sales_invoice_no")
    op.execute(
        "CREATE INDEX idx_sales_invoice_no ON sales(invoice_no) WHERE invoice_no IS NOT NULL"
    )


def downgrade() -> None:
    # Fails if two live sales share an invoice number — rename one first.
    op.execute("DROP INDEX IF EXISTS idx_sales_invoice_no")
    op.execute(
        "CREATE UNIQUE INDEX uq_sales_invoice_no ON sales(invoice_no) "
        "WHERE invoice_no IS NOT NULL AND status <> 'cancelled'"
    )
