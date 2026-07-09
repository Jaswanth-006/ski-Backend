"""banking master data (banks, bank_accounts, vendors)

Phase 8-B. Accounting-only reference data: the banks/accounts money can move
between and the vendors/people money is paid to.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE banks (
            id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name      TEXT NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bank_accounts (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id      UUID NOT NULL REFERENCES banks(id),
            account_type TEXT NOT NULL,
            label        TEXT,
            is_active    BOOLEAN NOT NULL DEFAULT true
        )
        """
    )
    op.execute("CREATE INDEX idx_bank_accounts_bank ON bank_accounts(bank_id)")
    op.execute(
        """
        CREATE TABLE vendors (
            id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name      TEXT NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT true
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bank_accounts")
    op.execute("DROP TABLE IF EXISTS vendors")
    op.execute("DROP TABLE IF EXISTS banks")
