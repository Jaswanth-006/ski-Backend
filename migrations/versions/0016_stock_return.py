"""stock return — damaged or lost items written out of stock

Adds the ``return`` stock-ledger reason (full/empty cylinders or accessories taken out of
stock because they were damaged or lost) and an optional ``note`` for why.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason")
    op.execute(
        """
        ALTER TABLE stock_ledger ADD CONSTRAINT ck_stock_ledger_reason
        CHECK (reason IN ('intake','ac4','erv','return','sale','reversal','adjust'))
        """
    )
    op.execute("ALTER TABLE stock_ledger ADD COLUMN note TEXT")


def downgrade() -> None:
    op.execute("DELETE FROM stock_ledger WHERE reason = 'return'")
    op.execute("ALTER TABLE stock_ledger DROP COLUMN note")
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason")
    op.execute(
        """
        ALTER TABLE stock_ledger ADD CONSTRAINT ck_stock_ledger_reason
        CHECK (reason IN ('intake','ac4','erv','sale','reversal','adjust'))
        """
    )
