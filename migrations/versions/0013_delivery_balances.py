"""delivery balances — money a delivery boy still owes the office

When a boy hands in less than he settled, the shortfall is a `charge`. When he later
pays some back, that's a `repayment`. His running balance = Σ charges − Σ repayments.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE delivery_balances (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            delivery_id UUID NOT NULL REFERENCES users(id),
            amount      NUMERIC(12,2) NOT NULL CHECK (amount > 0),
            entry_date  DATE NOT NULL,
            kind        TEXT NOT NULL CHECK (kind IN ('charge','repayment')),
            note        TEXT,
            created_by  UUID NOT NULL REFERENCES users(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_delivery_balances_driver ON delivery_balances(delivery_id)")
    op.execute("CREATE INDEX idx_delivery_balances_date ON delivery_balances(entry_date)")


def downgrade() -> None:
    op.execute("DROP TABLE delivery_balances")
