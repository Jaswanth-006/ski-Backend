"""sale balance — uncollected amount the delivery boy owes

A sale can leave a `balance`: the part of the revenue the boy didn't hand over (kept /
didn't collect). It reconciles as cash + upi + online + balance == revenue, and the
balance is pushed onto his delivery-balance ledger as a charge.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sales ADD COLUMN balance_total NUMERIC(12,2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE sales ADD CONSTRAINT ck_sales_balance_nonneg CHECK (balance_total >= 0)")


def downgrade() -> None:
    op.execute("ALTER TABLE sales DROP CONSTRAINT IF EXISTS ck_sales_balance_nonneg")
    op.execute("ALTER TABLE sales DROP COLUMN balance_total")
