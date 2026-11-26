"""purchase invoice — the IOC invoice number of each ac4 (stock received) entry

Every row of an ac4 entry carries the plant's invoice number. One invoice can be recorded only
once (checked in the service, case-insensitively). Entries recorded before this have none.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stock_ledger ADD COLUMN invoice_no TEXT")
    op.execute(
        "CREATE INDEX idx_stock_ledger_invoice ON stock_ledger(lower(invoice_no)) "
        "WHERE invoice_no IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stock_ledger_invoice")
    op.execute("ALTER TABLE stock_ledger DROP COLUMN invoice_no")
