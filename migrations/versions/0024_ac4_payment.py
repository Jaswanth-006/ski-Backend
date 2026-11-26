"""ac4 payment: a deposit to the vendor recorded with the purchase

transfers.stock_entry_id links the payment to the ac4 entry it paid for, so the purchase list
shows it and deleting the purchase removes its payment.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE transfers ADD COLUMN stock_entry_id UUID")
    op.execute(
        "CREATE INDEX idx_transfers_stock_entry ON transfers(stock_entry_id) "
        "WHERE stock_entry_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transfers_stock_entry")
    op.execute("ALTER TABLE transfers DROP COLUMN stock_entry_id")
