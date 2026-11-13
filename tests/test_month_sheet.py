"""Month sheet tests (Phase H) — per-date rollup with online, empties, denominations."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import CylinderType, Inventory, Price, SaleLine, StockLedger
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-ms"
DAY = dt.date(2095, 4, 5)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return str(res.json()["access_token"])


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(SaleLine).where(SaleLine.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.commit()
    await engine.dispose()


async def test_month_sheet_by_date_with_online_and_empties(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "MS"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 100, "effective_date": "2000-01-01"},
        )
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "business_date": DAY.isoformat(),
                "cylinders": [{"cylinder_type_id": type_id, "qty": 50}],
            },
        )
        # 10 cyl × 100 = 1000 = cash 500 + upi 200 + online 100 + balance 200;
        # 8 empties back, 1 damaged.
        sale = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "invoice_no": f"T-{uuid.uuid4()}",
                "delivery_id": str(users.delivery_id),
                "business_date": DAY.isoformat(),
                "lines": [
                    {"cylinder_type_id": type_id, "qty": 10, "empty_qty": 8, "damaged_qty": 1}
                ],
                "denominations": [{"note_value": 500, "note_count": 1}],
                "upi_total": 200,
                "online_total": 100,
                "balance_total": 200,
            },
        )
        assert sale.status_code == 201, sale.text

        ms = (await http.get(f"/v1/month-sheet/{DAY.year}/{DAY.month}", headers=admin)).json()
        day = next(d for d in ms["days"] if d["business_date"] == DAY.isoformat())
        assert (day["cylinders"], day["empties"], day["damaged"]) == (10, 8, 1)
        assert [float(day[k]) for k in ("amount", "upi", "cash", "online", "balance")] == [
            1000,
            200,
            500,
            100,
            200,
        ]

        # The month row is that day sheet's final totals.
        ds = (await http.get(f"/v1/day-sheet/{DAY.isoformat()}", headers=admin)).json()["totals"]
        assert (ds["cylinders"], ds["empties"], ds["damaged"]) == (
            day["cylinders"],
            day["empties"],
            day["damaged"],
        )
        for k in ("amount", "upi", "cash", "online", "balance"):
            assert float(ds[k]) == float(day[k]), k
    finally:
        await _cleanup()
