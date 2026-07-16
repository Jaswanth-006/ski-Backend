"""sale line empties — empties the delivery person actually returned

Each sale line now records how many empty cylinders came back (may differ from the
number sold). Empty stock rises by this count, and the day sheet shows it per party.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sale_lines ADD COLUMN empty_qty INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE sale_lines ADD CONSTRAINT ck_sale_lines_empty_nonneg CHECK (empty_qty >= 0)")
    # Existing sales returned one empty per full sold.
    op.execute("UPDATE sale_lines SET empty_qty = qty")


def downgrade() -> None:
    op.execute("ALTER TABLE sale_lines DROP CONSTRAINT IF EXISTS ck_sale_lines_empty_nonneg")
    op.execute("ALTER TABLE sale_lines DROP COLUMN empty_qty")
