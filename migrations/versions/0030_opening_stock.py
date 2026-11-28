"""Opening stock rows in the stock ledger (reason 'opening')

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE = "'intake','ac4','erv','return','sale','reversal','adjust'"


def _reasons(values: str) -> None:
    op.execute("ALTER TABLE stock_ledger DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason")
    op.execute(
        "ALTER TABLE stock_ledger ADD CONSTRAINT ck_stock_ledger_reason "
        f"CHECK (reason IN ({values}))"
    )


def upgrade() -> None:
    _reasons(_BASE + ",'opening'")


def downgrade() -> None:
    op.execute("DELETE FROM stock_ledger WHERE reason = 'opening'")
    _reasons(_BASE)
