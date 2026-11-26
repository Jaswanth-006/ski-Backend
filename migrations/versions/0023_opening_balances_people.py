"""opening balances + people (debtors / creditors); money can flow in from people

- bank_accounts.opening_balance: money in the account when it was added.
- vendors.opening_balance: amount paid to the vendor before using the app.
- people: a Debtor owes us (we gave them money), a Creditor we owe (they gave the company
  money). Each has an opening balance.
- transfers: money can now come FROM a person and go TO the cashier box, so a debtor's
  repayment or a creditor's loan lands in the box or a bank account. Persons are picked from
  the people list (dest_person_id / source_person_id) instead of a typed name.
- credits (money given until repaid) become debtors; the credits table is dropped.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Inline CHECKs from 0005 got Postgres' own names; drop every name they may carry.
_OLD_CHECKS = (
    "transfers_source_kind_check",
    "transfers_dest_kind_check",
    "ck_transfers_source_kind",
    "ck_transfers_dest_kind",
    "ck_transfers_source",
    "ck_transfers_dest",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bank_accounts ADD COLUMN opening_balance NUMERIC(14,2) NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE vendors ADD COLUMN opening_balance NUMERIC(14,2) NOT NULL DEFAULT 0")

    op.execute(
        """
        CREATE TABLE people (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL,
            kind            TEXT NOT NULL CHECK (kind IN ('debtor', 'creditor')),
            phone           TEXT,
            note            TEXT,
            opening_balance NUMERIC(14,2) NOT NULL DEFAULT 0,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_people_name_kind UNIQUE (name, kind)
        )
        """
    )

    for name in _OLD_CHECKS:
        op.execute(f"ALTER TABLE transfers DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE transfers ADD COLUMN source_person_id UUID REFERENCES people(id)")
    op.execute("ALTER TABLE transfers ADD COLUMN dest_person_id UUID REFERENCES people(id)")

    # Typed-in person names on old deposits → debtors (we gave them money).
    op.execute(
        """
        INSERT INTO people (name, kind)
        SELECT DISTINCT dest_person_name, 'debtor' FROM transfers
        WHERE dest_kind = 'person' AND dest_person_name IS NOT NULL
        ON CONFLICT (name, kind) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE transfers t SET dest_person_id = p.id
        FROM people p
        WHERE t.dest_kind = 'person' AND p.kind = 'debtor' AND p.name = t.dest_person_name
        """
    )

    # Open credits → debtors, their total as the opening balance.
    op.execute(
        """
        INSERT INTO people (name, kind, opening_balance, note)
        SELECT person_name, 'debtor', SUM(amount), 'moved from Credit'
        FROM credits WHERE NOT is_settled GROUP BY person_name
        ON CONFLICT (name, kind)
        DO UPDATE SET opening_balance = people.opening_balance + EXCLUDED.opening_balance
        """
    )
    op.execute("DROP TABLE credits")

    op.execute(
        "ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source_kind "
        "CHECK (source_kind IN ('cashier_box', 'bank_account', 'person'))"
    )
    op.execute(
        "ALTER TABLE transfers ADD CONSTRAINT ck_transfers_dest_kind "
        "CHECK (dest_kind IN ('vendor', 'person', 'bank_account', 'cashier_box'))"
    )
    op.execute(
        """
        ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source CHECK (
            (source_kind = 'bank_account') = (source_bank_account_id IS NOT NULL)
            AND (source_kind = 'person') = (source_person_id IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE transfers ADD CONSTRAINT ck_transfers_dest CHECK (
            (dest_kind = 'vendor'       AND dest_vendor_id       IS NOT NULL) OR
            (dest_kind = 'bank_account' AND dest_bank_account_id IS NOT NULL) OR
            (dest_kind = 'person'       AND dest_person_id       IS NOT NULL) OR
            (dest_kind = 'cashier_box')
        )
        """
    )


def downgrade() -> None:
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
    for name in _OLD_CHECKS:
        op.execute(f"ALTER TABLE transfers DROP CONSTRAINT IF EXISTS {name}")
    op.execute(
        "DELETE FROM transfers WHERE source_kind = 'person' OR dest_kind = 'cashier_box'"
    )
    op.execute(
        """
        UPDATE transfers t SET dest_person_name = p.name
        FROM people p WHERE t.dest_person_id = p.id AND t.dest_person_name IS NULL
        """
    )
    op.execute("ALTER TABLE transfers DROP COLUMN dest_person_id")
    op.execute("ALTER TABLE transfers DROP COLUMN source_person_id")
    op.execute(
        "ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source_kind "
        "CHECK (source_kind IN ('cashier_box', 'bank_account'))"
    )
    op.execute(
        "ALTER TABLE transfers ADD CONSTRAINT ck_transfers_dest_kind "
        "CHECK (dest_kind IN ('vendor', 'person', 'bank_account'))"
    )
    op.execute("DROP TABLE people")
    op.execute("ALTER TABLE vendors DROP COLUMN opening_balance")
    op.execute("ALTER TABLE bank_accounts DROP COLUMN opening_balance")
