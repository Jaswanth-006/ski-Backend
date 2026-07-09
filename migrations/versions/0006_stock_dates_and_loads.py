"""stock business dates + per-driver load/return log

Phase 8-D. Attributes each stock movement to a business date so warehouse opening/closing
stock can be derived per day (today's closing = tomorrow's opening), and adds a per-delivery
daily load/return logbook (loaded → sold → returned). Warehouse inventory stays intake − sale;
loads are a reconciliation layer that does not change on-hand quantities.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stock_ledger ADD COLUMN business_date DATE")
    op.execute("UPDATE stock_ledger SET business_date = created_at::date")
    op.execute("ALTER TABLE stock_ledger ALTER COLUMN business_date SET NOT NULL")
    op.execute("ALTER TABLE stock_ledger ALTER COLUMN business_date SET DEFAULT CURRENT_DATE")
    op.execute("CREATE INDEX idx_stock_ledger_date ON stock_ledger(business_date)")

    op.execute(
        """
        CREATE TABLE stock_loads (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            business_date    DATE NOT NULL,
            delivery_id      UUID NOT NULL REFERENCES users(id),
            cylinder_type_id UUID NOT NULL REFERENCES cylinder_types(id),
            loaded_qty       INTEGER NOT NULL DEFAULT 0 CHECK (loaded_qty >= 0),
            returned_qty     INTEGER NOT NULL DEFAULT 0 CHECK (returned_qty >= 0),
            created_by       UUID NOT NULL REFERENCES users(id),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_stock_loads_day
                UNIQUE (business_date, delivery_id, cylinder_type_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_loads")
    op.execute("DROP INDEX IF EXISTS idx_stock_ledger_date")
    op.execute("ALTER TABLE stock_ledger DROP COLUMN IF EXISTS business_date")
