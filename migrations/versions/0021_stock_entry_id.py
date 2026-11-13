"""stock entry id — group the lines of one purchase entry so it can be edited or deleted

Each ac4 / erv / return / intake call writes one ledger row per line. entry_id ties those rows
together. Existing rows are grouped by what they share: reason, date, who and when (all rows of
one call are written in the same transaction, so they have the same created_at).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stock_ledger ADD COLUMN entry_id UUID")
    op.execute(
        """
        WITH groups AS (
            SELECT reason, business_date, created_by, created_at, gen_random_uuid() AS eid
            FROM (
                SELECT DISTINCT reason, business_date, created_by, created_at
                FROM stock_ledger
                WHERE reason IN ('ac4', 'erv', 'return', 'intake')
            ) d
        )
        UPDATE stock_ledger sl SET entry_id = g.eid
        FROM groups g
        WHERE sl.reason = g.reason AND sl.business_date = g.business_date
          AND sl.created_by = g.created_by AND sl.created_at = g.created_at
        """
    )
    op.execute(
        "CREATE INDEX idx_stock_ledger_entry ON stock_ledger(entry_id) WHERE entry_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stock_ledger_entry")
    op.execute("ALTER TABLE stock_ledger DROP COLUMN entry_id")
