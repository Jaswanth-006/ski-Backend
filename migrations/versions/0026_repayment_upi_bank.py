"""UPI repayments into a bank account

transfers.balance_entry_id links the cashier box → bank deposit made for a repayment paid by
UPI (a delivery_balances or customer_balances row) so editing / deleting the repayment keeps
it in step.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE transfers ADD COLUMN balance_entry_id UUID")
    op.execute(
        "CREATE INDEX idx_transfers_balance_entry ON transfers(balance_entry_id) "
        "WHERE balance_entry_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transfers_balance_entry")
    op.execute("ALTER TABLE transfers DROP COLUMN balance_entry_id")
