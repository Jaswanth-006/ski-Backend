"""transfers (deposits / money movement)

Phase 8-C. Records money leaving a source (the cashier box or a bank account) to a
destination (a vendor, a person, or one of your own bank accounts). Balances are derived
from this table (bank accounts) and from cash_ledger minus box-sourced transfers (cashier box).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transfers (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            business_date          DATE NOT NULL,
            amount                 NUMERIC(14,2) NOT NULL CHECK (amount > 0),
            source_kind            TEXT NOT NULL
                                   CHECK (source_kind IN ('cashier_box','bank_account')),
            source_bank_account_id UUID REFERENCES bank_accounts(id),
            dest_kind              TEXT NOT NULL
                                   CHECK (dest_kind IN ('vendor','person','bank_account')),
            dest_vendor_id         UUID REFERENCES vendors(id),
            dest_bank_account_id   UUID REFERENCES bank_accounts(id),
            dest_person_name       TEXT,
            method                 TEXT NOT NULL,
            note                   TEXT,
            created_by             UUID NOT NULL REFERENCES users(id),
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_transfers_source
                CHECK ((source_kind = 'bank_account') = (source_bank_account_id IS NOT NULL)),
            CONSTRAINT ck_transfers_dest CHECK (
                (dest_kind = 'vendor'       AND dest_vendor_id       IS NOT NULL) OR
                (dest_kind = 'bank_account' AND dest_bank_account_id IS NOT NULL) OR
                (dest_kind = 'person'       AND dest_person_name     IS NOT NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX idx_transfers_date ON transfers(business_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transfers")
