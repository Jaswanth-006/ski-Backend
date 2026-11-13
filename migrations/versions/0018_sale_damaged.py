"""sale line damaged — cylinders that came back damaged or were lost

Each sale line records how many of the cylinders sold came back damaged or were lost
(the "Return" column on the day sheet). They are not added to empty stock.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sale_lines ADD COLUMN damaged_qty INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE sale_lines ADD CONSTRAINT ck_sale_lines_damaged_nonneg "
        "CHECK (damaged_qty >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sale_lines DROP CONSTRAINT IF EXISTS ck_sale_lines_damaged_nonneg")
    op.execute("ALTER TABLE sale_lines DROP COLUMN damaged_qty")
