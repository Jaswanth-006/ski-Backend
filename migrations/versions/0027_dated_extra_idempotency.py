"""Dated per-boy extra, and repeat-safe saves

delivery_other_sales gets an effective_date (part of the key) so a back-dated or edited sale
uses the extra that applied on its own date, like the cylinder price. Existing rows apply
from 2000-01-01.

idempotency_keys remembers a saved entry by the Idempotency-Key the web app sends, so a
retried deposit / expense / repayment / erv / return is not recorded twice.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE delivery_other_sales "
        "ADD COLUMN effective_date DATE NOT NULL DEFAULT DATE '2000-01-01'"
    )
    op.execute("ALTER TABLE delivery_other_sales DROP CONSTRAINT delivery_other_sales_pkey")
    op.execute(
        "ALTER TABLE delivery_other_sales "
        "ADD CONSTRAINT delivery_other_sales_pkey PRIMARY KEY (delivery_id, effective_date)"
    )
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            key        UUID PRIMARY KEY,
            scope      TEXT NOT NULL,
            response   JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE idempotency_keys")
    # Keep each boy's latest extra only.
    op.execute(
        "DELETE FROM delivery_other_sales d USING delivery_other_sales n "
        "WHERE n.delivery_id = d.delivery_id AND n.effective_date > d.effective_date"
    )
    op.execute("ALTER TABLE delivery_other_sales DROP CONSTRAINT delivery_other_sales_pkey")
    op.execute("ALTER TABLE delivery_other_sales DROP COLUMN effective_date")
    op.execute(
        "ALTER TABLE delivery_other_sales "
        "ADD CONSTRAINT delivery_other_sales_pkey PRIMARY KEY (delivery_id)"
    )
