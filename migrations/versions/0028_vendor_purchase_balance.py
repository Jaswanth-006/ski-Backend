"""Purchases come out of the vendor's balance

Money deposited with a vendor (IOC) is a balance; each ac4 purchase now records its amount as
a transfer from that vendor's balance (source_kind 'vendor') to the purchase (dest_kind
'purchase'), linked by stock_entry_id. Vendor balance = opening + deposits − purchases.

The IOC invoice number of an ac4 entry no longer has to be unique (checked in the app only).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _kinds(source: str, dest: str) -> None:
    op.execute("ALTER TABLE transfers DROP CONSTRAINT IF EXISTS ck_transfers_source_kind")
    op.execute(
        f"ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source_kind CHECK (source_kind IN ({source}))"
    )
    op.execute("ALTER TABLE transfers DROP CONSTRAINT IF EXISTS ck_transfers_dest_kind")
    op.execute(
        f"ALTER TABLE transfers ADD CONSTRAINT ck_transfers_dest_kind CHECK (dest_kind IN ({dest}))"
    )


def _refs(with_purchase: bool) -> None:
    """Each kind carries its own id (and only that one)."""
    source = (
        "(source_kind = 'bank_account') = (source_bank_account_id IS NOT NULL)"
        " AND (source_kind = 'person') = (source_person_id IS NOT NULL)"
    )
    dest = (
        "(dest_kind = 'vendor' AND dest_vendor_id IS NOT NULL)"
        " OR (dest_kind = 'bank_account' AND dest_bank_account_id IS NOT NULL)"
        " OR (dest_kind = 'person' AND dest_person_id IS NOT NULL)"
        " OR (dest_kind = 'cashier_box')"
    )
    if with_purchase:
        source += " AND (source_kind = 'vendor') = (source_vendor_id IS NOT NULL)"
        dest += " OR (dest_kind = 'purchase')"
    op.execute("ALTER TABLE transfers DROP CONSTRAINT IF EXISTS ck_transfers_source")
    op.execute(f"ALTER TABLE transfers ADD CONSTRAINT ck_transfers_source CHECK ({source})")
    op.execute("ALTER TABLE transfers DROP CONSTRAINT IF EXISTS ck_transfers_dest")
    op.execute(f"ALTER TABLE transfers ADD CONSTRAINT ck_transfers_dest CHECK ({dest})")


def upgrade() -> None:
    op.execute("ALTER TABLE transfers ADD COLUMN source_vendor_id UUID REFERENCES vendors(id)")
    _kinds(
        "'cashier_box', 'bank_account', 'person', 'online', 'vendor'",
        "'vendor', 'person', 'bank_account', 'cashier_box', 'purchase'",
    )
    _refs(with_purchase=True)


def downgrade() -> None:
    op.execute("DELETE FROM transfers WHERE source_kind = 'vendor' OR dest_kind = 'purchase'")
    _refs(with_purchase=False)
    _kinds(
        "'cashier_box', 'bank_account', 'person', 'online'",
        "'vendor', 'person', 'bank_account', 'cashier_box'",
    )
    op.execute("ALTER TABLE transfers DROP COLUMN source_vendor_id")
