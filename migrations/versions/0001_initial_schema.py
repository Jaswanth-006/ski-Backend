"""initial schema — all v1 tables

Canonical DDL: 01-BACKEND-PRD §4 (the `jobs` table lands in Phase 0-F).

Revision ID: 0001
Revises:
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA_SQL = """
-- ============ Identity ============
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('super_admin','office_admin','delivery')),
    phone         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    family_id   UUID NOT NULL,
    token_hash  TEXT NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Catalog & pricing (temporal) ============
CREATE TABLE cylinder_types (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code      TEXT UNIQUE NOT NULL,
    label     TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE prices (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cylinder_type_id UUID NOT NULL REFERENCES cylinder_types(id),
    unit_price       NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
    effective_date   DATE NOT NULL,
    created_by       UUID NOT NULL REFERENCES users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cylinder_type_id, effective_date)
);

-- ============ Inventory (optimistic locking) ============
CREATE TABLE inventory (
    cylinder_type_id UUID PRIMARY KEY REFERENCES cylinder_types(id),
    quantity         INTEGER NOT NULL CHECK (quantity >= 0),
    version          INTEGER NOT NULL DEFAULT 0
);

-- ============ Append-only stock ledger ============
CREATE TABLE stock_ledger (
    id               BIGSERIAL PRIMARY KEY,
    cylinder_type_id UUID NOT NULL REFERENCES cylinder_types(id),
    delta            INTEGER NOT NULL,
    reason           TEXT NOT NULL CHECK (reason IN ('intake','sale','reversal','adjust')),
    ref_id           UUID,
    created_by       UUID NOT NULL REFERENCES users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Sales (idempotent) ============
CREATE TABLE sales (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key UUID UNIQUE NOT NULL,
    delivery_id     UUID NOT NULL REFERENCES users(id),
    business_date   DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected')),
    upi_total       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (upi_total >= 0),
    submitted_via   TEXT NOT NULL DEFAULT 'mobile'
                    CHECK (submitted_via IN ('mobile','web')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at     TIMESTAMPTZ,
    approved_by     UUID REFERENCES users(id)
);

CREATE TABLE sale_lines (
    id               BIGSERIAL PRIMARY KEY,
    sale_id          UUID NOT NULL REFERENCES sales(id),
    cylinder_type_id UUID NOT NULL REFERENCES cylinder_types(id),
    qty              INTEGER NOT NULL CHECK (qty >= 0),
    unit_price       NUMERIC(10,2) NOT NULL
);

CREATE TABLE cash_denominations (
    id         BIGSERIAL PRIMARY KEY,
    sale_id    UUID NOT NULL REFERENCES sales(id),
    note_value INTEGER NOT NULL CHECK (note_value > 0),
    note_count INTEGER NOT NULL CHECK (note_count >= 0)
);

-- ============ Append-only cash ledger ============
CREATE TABLE cash_ledger (
    id         BIGSERIAL PRIMARY KEY,
    sale_id    UUID REFERENCES sales(id),
    amount     NUMERIC(12,2) NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('cash','upi','expense','reversal')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Expense items (admin-managed master data) ============
CREATE TABLE expense_items (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    category   TEXT,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name)
);

-- ============ Expenses ============
CREATE TABLE expenses (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_date DATE NOT NULL,
    item_id       UUID NOT NULL REFERENCES expense_items(id),
    amount        NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    method        TEXT NOT NULL CHECK (method IN ('cash','digital')),
    note          TEXT,
    created_by    UUID NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Day-sheet lock ============
CREATE TABLE day_sheet_status (
    business_date DATE PRIMARY KEY,
    is_closed     BOOLEAN NOT NULL DEFAULT FALSE,
    closed_by     UUID REFERENCES users(id),
    closed_at     TIMESTAMPTZ
);

-- ============ Immutable audit log ============
CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor_id   UUID REFERENCES users(id),
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  TEXT,
    old_value  JSONB,
    new_value  JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Indexes ============
CREATE INDEX idx_sales_date_delivery ON sales (business_date, delivery_id);
CREATE INDEX idx_sales_status        ON sales (status) WHERE status = 'pending';
CREATE INDEX idx_stock_ledger_type   ON stock_ledger (cylinder_type_id, created_at);
CREATE INDEX idx_cash_ledger_date    ON cash_ledger (created_at);
CREATE INDEX idx_prices_lookup       ON prices (cylinder_type_id, effective_date DESC);
CREATE INDEX idx_expenses_date       ON expenses (business_date);
CREATE INDEX idx_expenses_item       ON expenses (item_id);
CREATE INDEX idx_cyl_active          ON cylinder_types (is_active);
CREATE INDEX idx_expitem_active      ON expense_items (is_active);
CREATE INDEX idx_audit_entity        ON audit_log (entity, entity_id, created_at);
"""

# Drop order respects FK dependencies (children before parents).
DROP_SQL = """
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS day_sheet_status;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS expense_items;
DROP TABLE IF EXISTS cash_ledger;
DROP TABLE IF EXISTS cash_denominations;
DROP TABLE IF EXISTS sale_lines;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS stock_ledger;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS prices;
DROP TABLE IF EXISTS cylinder_types;
DROP TABLE IF EXISTS refresh_tokens;
DROP TABLE IF EXISTS users;
"""


def _execute_each(sql: str) -> None:
    # asyncpg (via SQLAlchemy) runs one statement per execute, so split on ";".
    for statement in filter(None, (s.strip() for s in sql.split(";"))):
        op.execute(statement)


def upgrade() -> None:
    _execute_each(SCHEMA_SQL)


def downgrade() -> None:
    _execute_each(DROP_SQL)
