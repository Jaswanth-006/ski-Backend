"""Schema shape tests (no DB required) — guards the registered tables and key constraints."""

from __future__ import annotations

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

EXPECTED_TABLES = {
    "users",
    "refresh_tokens",
    "cylinder_types",
    "prices",
    "inventory",
    "stock_ledger",
    "sales",
    "sale_lines",
    "cash_denominations",
    "cash_ledger",
    "expense_items",
    "expenses",
    "day_sheet_status",
    "audit_log",
    "jobs",  # added in Phase 0-F
    "banks",  # added in Phase 8-B
    "bank_accounts",
    "vendors",
    "transfers",  # added in Phase 8-C
    "stock_loads",  # added in Phase 8-D
    "accessories",  # added in stock v2
    "delivery_other_sales",  # added in Phase C
    "credits",  # added in Phase E
    "customers",  # added in Phase I
    "delivery_balances",  # added in Phase K
}


def test_all_v1_tables_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_jobs_table_present() -> None:
    # Added with the async infrastructure in Phase 0-F.
    assert "jobs" in Base.metadata.tables


def test_sales_has_unique_idempotency_key() -> None:
    idempotency = models.Sale.__table__.c.idempotency_key
    assert idempotency.unique is True
