"""sales online payment

Adds a third payment channel: `online` (money paid directly to the company — the
delivery boy never handles it). A sale reconciles when cash + upi + online == revenue,
and the boy only settles cash + upi. Also lets the cash ledger record an `online` entry.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sales ADD COLUMN online_total NUMERIC(12,2) NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE sales ADD CONSTRAINT ck_sales_online_nonneg CHECK (online_total >= 0)"
    )
    op.execute("ALTER TABLE cash_ledger DROP CONSTRAINT IF EXISTS cash_ledger_kind_check")
    op.execute("ALTER TABLE cash_ledger DROP CONSTRAINT IF EXISTS ck_cash_ledger_kind")
    op.execute(
        """
        ALTER TABLE cash_ledger ADD CONSTRAINT ck_cash_ledger_kind
        CHECK (kind IN ('cash','upi','online','expense','reversal'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cash_ledger DROP CONSTRAINT IF EXISTS ck_cash_ledger_kind")
    op.execute("DELETE FROM cash_ledger WHERE kind = 'online'")
    op.execute(
        """
        ALTER TABLE cash_ledger ADD CONSTRAINT cash_ledger_kind_check
        CHECK (kind IN ('cash','upi','expense','reversal'))
        """
    )
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS ck_sales_online_nonneg")
    op.execute("ALTER TABLE sales DROP COLUMN online_total")
