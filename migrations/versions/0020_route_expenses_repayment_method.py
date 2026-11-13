"""route expenses belong to their sale; repayments say how they were paid

- expenses.sale_id: a delivery boy's route expense entered with a sale. It settles part of
  that sale (he spent it from the collection), never passed through the cashier box, and is
  removed when the sale is cancelled.
- delivery_balances.method / customer_balances.method: 'cash' or 'upi' for repayments, so
  repaid money is counted in the cashier box (and cash repayments in hand cash).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE expenses ADD COLUMN sale_id UUID REFERENCES sales(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX idx_expenses_sale ON expenses(sale_id) WHERE sale_id IS NOT NULL")
    for table in ("delivery_balances", "customer_balances"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN method TEXT")
        # Repayments recorded so far were taken in cash at the office.
        op.execute(f"UPDATE {table} SET method = 'cash' WHERE kind = 'repayment'")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_method "
            "CHECK (method IS NULL OR method IN ('cash','upi'))"
        )


def downgrade() -> None:
    for table in ("delivery_balances", "customer_balances"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_method")
        op.execute(f"ALTER TABLE {table} DROP COLUMN method")
    op.execute("DROP INDEX IF EXISTS idx_expenses_sale")
    op.execute("ALTER TABLE expenses DROP COLUMN sale_id")
