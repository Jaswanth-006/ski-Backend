"""expense attributed to a delivery boy

An expense can now be tied to a delivery boy (fuel etc. on his route). It still
counts in the day's expense total, and the day sheet shows it per driver so his
net hand-in = settled − his expenses.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE expenses ADD COLUMN delivery_id UUID REFERENCES users(id)")
    op.execute("CREATE INDEX idx_expenses_delivery ON expenses(delivery_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_expenses_delivery")
    op.execute("ALTER TABLE expenses DROP COLUMN delivery_id")
