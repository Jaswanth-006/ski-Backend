"""sale money moves: UPI to a bank account, online to the vendor, recorded with the sale

transfers.sale_id links a deposit to the sale that made it (removed when the sale is cancelled or
edited). New source 'online' = customers paid the vendor (IOC) online directly; it touches no
cashier box or bank balance, only what the vendor has been paid.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE transfers ADD COLUMN sale_id UUID REFERENCES sales(id)")
    op.execute(
        "CREATE INDEX idx_transfers_sale ON transfers(sale_id) WHERE sale_id IS NOT NULL"
    )
    op.execute("ALTER TABLE transfers DROP CONSTRAINT IF EXISTS ck_transfers_source_kind")
    op.execute(
        "ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source_kind "
        "CHECK (source_kind IN ('cashier_box', 'bank_account', 'person', 'online'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM transfers WHERE source_kind = 'online'")
    op.execute("ALTER TABLE transfers DROP CONSTRAINT IF EXISTS ck_transfers_source_kind")
    op.execute(
        "ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source_kind "
        "CHECK (source_kind IN ('cashier_box', 'bank_account', 'person'))"
    )
    op.execute("DROP INDEX IF EXISTS idx_transfers_sale")
    op.execute("ALTER TABLE transfers DROP COLUMN sale_id")
