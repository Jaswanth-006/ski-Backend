"""End-to-end critical-flow test (Phase 7-C).

Drives the whole money+stock path in one test: login → master data → pricing → stock intake
→ driver load → reconciled sale (Move-to-Day-Sheet) → day sheet → close day → export → EOD.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.core.config import settings
from app.db.models import (
    CashDenomination,
    CashLedger,
    CylinderType,
    DaySheetStatus,
    Inventory,
    Price,
    Sale,
    SaleLine,
    StockLedger,
    StockLoad,
)
from app.workers.tasks import export_day_sheet
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-e2e"
DAY = dt.date(2093, 2, 1)
DS = DAY.isoformat()


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(StockLoad).where(StockLoad.business_date == DAY))
        await db.execute(delete(DaySheetStatus).where(DaySheetStatus.business_date == DAY))
        sale_ids = (await db.scalars(select(Sale.id).where(Sale.business_date == DAY))).all()
        for sid in sale_ids:
            await db.execute(delete(CashDenomination).where(CashDenomination.sale_id == sid))
            await db.execute(delete(CashLedger).where(CashLedger.sale_id == sid))
            await db.execute(delete(SaleLine).where(SaleLine.sale_id == sid))
        await db.execute(delete(Sale).where(Sale.business_date == DAY))
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.commit()
    await engine.dispose()


async def test_full_day_end_to_end(
    client: tuple[AsyncClient, SeededUsers], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, users = client
    monkeypatch.setattr(export_day_sheet, "delay", lambda *a, **k: None)  # no worker in tests
    await _cleanup()
    try:
        # 1. Login.
        login = await http.post(
            "/v1/auth/login", json={"phone": TEST_ADMIN_PHONE, "password": TEST_PASSWORD}
        )
        assert login.status_code == 200
        admin = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # 2. Master data + 3. pricing.
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "E2E"}
            )
        ).json()["id"]
        assert (
            await http.put(
                "/v1/prices",
                headers=admin,
                json={
                    "cylinder_type_id": type_id,
                    "unit_price": 1000,
                    "effective_date": "2000-01-01",
                },
            )
        ).status_code == 204

        # 4. Stock intake (100) + 5. driver load (60 out, 20 back).
        assert (
            await http.post(
                "/v1/stock/intake",
                headers=admin,
                json={"business_date": DS, "lines": [{"cylinder_type_id": type_id, "qty": 100}]},
            )
        ).status_code == 200
        assert (
            await http.post(
                "/v1/stock/loads",
                headers=admin,
                json={
                    "business_date": DS,
                    "delivery_id": str(users.delivery_id),
                    "cylinder_type_id": type_id,
                    "loaded_qty": 60,
                    "returned_qty": 20,
                },
            )
        ).status_code == 201

        # 6. Reconciled sale (40 × 1000 = 40000, paid by UPI) → Move to Day Sheet.
        sale = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 40}],
                "denominations": [],
                "upi_total": 40000,
            },
        )
        assert sale.status_code == 201 and sale.json()["status"] == "approved"

        # 7. Day sheet reflects it (sold 40, loaded 60, returned 20; warehouse closes at 60).
        sheet = (await http.get(f"/v1/day-sheet/{DS}", headers=admin)).json()
        row = next(r for r in sheet["rows"] if r["delivery_id"] == str(users.delivery_id))
        assert (row["cylinders"], row["loaded"], row["returned"]) == (40, 60, 20)
        assert sheet["stock"]["closing"] == 60
        assert float(sheet["totals"]["total"]) == 40000

        # 8. Close day → locked; 9. a closed day rejects new sales.
        closed = await http.post(f"/v1/day-sheet/{DS}/close", headers=admin)
        assert closed.status_code == 200 and closed.json()["is_closed"] is True
        rejected = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "denominations": [],
                "upi_total": 1000,
            },
        )
        assert rejected.status_code == 409

        # 10. Export → job accepted and pollable.
        exp = await http.post(f"/v1/day-sheet/{DS}/export", headers=admin)
        assert exp.status_code == 202
        job = await http.get(f"/v1/jobs/{exp.json()['job_id']}", headers=admin)
        assert job.status_code == 200 and job.json()["kind"] == "export"

        # 11. EOD analytics reflects the day (owner sees net profit).
        eod = (await http.get(f"/v1/analytics/eod?date={DS}", headers=admin)).json()
        assert eod["cylinders_sold"] == 40
        assert eod["net_profit"] is not None
    finally:
        await _cleanup()
