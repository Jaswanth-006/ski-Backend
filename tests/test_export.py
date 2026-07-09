"""Excel export tests (Phase 4-D)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from app.schemas.day_sheet import DaySheetOut, DaySheetTotals, StockSummary
from app.workers.exports import build_day_sheet_xlsx
from app.workers.tasks import export_day_sheet
from httpx import AsyncClient

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers


def test_build_day_sheet_xlsx_returns_valid_workbook() -> None:
    sheet = DaySheetOut(
        business_date=dt.date(2026, 1, 1),
        is_closed=False,
        closed_at=None,
        rows=[],
        totals=DaySheetTotals(cylinders=0, cash=Decimal(0), upi=Decimal(0), total=Decimal(0)),
        expenses_total=Decimal(0),
        net=Decimal(0),
        denomination_totals=[],
        cashier_opening=Decimal(0),
        cashier_closing=Decimal(0),
        stock=StockSummary(opening=0, loaded=0, sold=0, returned=0, closing=0),
    )
    data = build_day_sheet_xlsx(sheet)
    assert data[:2] == b"PK"  # .xlsx is a zip archive
    assert len(data) > 0


async def test_export_enqueues_job(
    client: tuple[AsyncClient, SeededUsers], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    # Stub the broker hand-off so we don't need a running worker.
    monkeypatch.setattr(export_day_sheet, "delay", lambda *a, **k: None)
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    res = await http.post("/v1/day-sheet/2026-01-01/export", headers=admin)
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "queued"
    # The job is pollable
    got = await http.get(f"/v1/jobs/{body['job_id']}", headers=admin)
    assert got.status_code == 200
    assert got.json()["kind"] == "export"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token
