"""sale invoice number + customer balances

Each sale now carries an invoice number, unique across sales (older sales have none).
Customers get a balance ledger like delivery boys: an uncollected sale amount is a charge,
and repayments bring it down.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sales ADD COLUMN invoice_no TEXT")
    op.execute(
        "CREATE UNIQUE INDEX uq_sales_invoice_no ON sales(invoice_no) WHERE invoice_no IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE customer_balances (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES customers(id),
            amount      NUMERIC(12,2) NOT NULL CHECK (amount > 0),
            entry_date  DATE NOT NULL,
            kind        TEXT NOT NULL CHECK (kind IN ('charge','repayment')),
            note        TEXT,
            created_by  UUID NOT NULL REFERENCES users(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_customer_balances_customer ON customer_balances(customer_id)")
    op.execute("CREATE INDEX idx_customer_balances_date ON customer_balances(entry_date)")


def downgrade() -> None:
    op.execute("DROP TABLE customer_balances")
    op.execute("DROP INDEX IF EXISTS uq_sales_invoice_no")
    op.execute("ALTER TABLE sales DROP COLUMN invoice_no")
