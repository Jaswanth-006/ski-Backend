"""credits — money given out, tracked until repaid

A simple receivables ledger: record money handed to a person, then mark it settled
when they pay it back. Answers 'did this person credit me back yet?'.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE credits (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            person_name  TEXT NOT NULL,
            amount       NUMERIC(12,2) NOT NULL CHECK (amount > 0),
            given_date   DATE NOT NULL,
            note         TEXT,
            is_settled   BOOLEAN NOT NULL DEFAULT FALSE,
            settled_date DATE,
            created_by   UUID NOT NULL REFERENCES users(id),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_credits_open ON credits(is_settled)")


def downgrade() -> None:
    op.execute("DROP TABLE credits")
