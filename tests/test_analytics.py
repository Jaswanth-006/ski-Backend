"""EOD analytics tests (Phase 4-E). Aggregation only; net profit is owner-only."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import (
    CylinderType,
    Expense,
    ExpenseItem,
    Inventory,
    Price,
    SaleLine,
    StockLedger,
    StockLoad,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-an"
ITEM_NAME = "ZZ-an-fuel"
DAY_DATE = dt.date(2098, 6, 3)  # isolated from other suites
DAY = DAY_DATE.isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Expense).where(Expense.business_date == DAY_DATE))
        await db.execute(delete(ExpenseItem).where(ExpenseItem.name == ITEM_NAME))
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(StockLoad).where(StockLoad.cylinder_type_id == tid))
            await db.execute(delete(SaleLine).where(SaleLine.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.commit()
    await engine.dispose()


async def test_eod_numbers_and_owner_only_net_profit(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    try:
        # A priced + stocked variety, one sale (revenue 3000), one cash expense (200).
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "AN"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 1000, "effective_date": "2000-01-01"},
        )
        await http.post(
            "/v1/stock/intake",
            headers=admin,
            json={"lines": [{"cylinder_type_id": type_id, "qty": 50}]},
        )
        assert (
            await http.post(
                "/v1/sales",
                headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
                json={
                    "delivery_id": str(users.delivery_id),
                    "business_date": DAY,
                    "lines": [{"cylinder_type_id": type_id, "qty": 3}],  # revenue 3000
                    "denominations": [{"note_value": 1000, "note_count": 2}],  # 2000 cash
                    "upi_total": 1000,  # collected 3000
                },
            )
        ).status_code == 201
        item_id = (
            await http.post("/v1/expense-items", headers=admin, json={"name": ITEM_NAME})
        ).json()["id"]
        await http.post(
            "/v1/expenses",
            headers=admin,
            json={"business_date": DAY, "item_id": item_id, "amount": 200, "method": "cash"},
        )

        # Owner sees the real numbers including net profit.
        eod_admin = (await http.get(f"/v1/analytics/eod?date={DAY}", headers=admin)).json()
        assert eod_admin["cylinders_sold"] == 3
        assert float(eod_admin["expenses_total"]) == 200
        assert eod_admin["net_profit"] is not None
        assert float(eod_admin["net_profit"]) == 3000 - 200  # collected − expenses

        # Office sees the aggregates but net profit is withheld.
        eod_office = (await http.get(f"/v1/analytics/eod?date={DAY}", headers=office)).json()
        assert eod_office["cylinders_sold"] == 3
        assert eod_office["net_profit"] is None
    finally:
        await _cleanup()


async def test_collections_trend_and_cylinder_movement(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "AN"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 1000, "effective_date": "2000-01-01"},
        )
        await http.post(
            "/v1/stock/intake",
            headers=admin,
            json={"lines": [{"cylinder_type_id": type_id, "qty": 50}]},
        )
        # Load 10 out to the driver, then sell 3 (cash 2000 + UPI 1000 = 3000 collected).
        await http.post(
            "/v1/stock/loads",
            headers=admin,
            json={
                "business_date": DAY,
                "delivery_id": str(users.delivery_id),
                "cylinder_type_id": type_id,
                "loaded_qty": 10,
            },
        )
        assert (
            await http.post(
                "/v1/sales",
                headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
                json={
                    "delivery_id": str(users.delivery_id),
                    "business_date": DAY,
                    "lines": [{"cylinder_type_id": type_id, "qty": 3}],
                    "denominations": [{"note_value": 1000, "note_count": 2}],
                    "upi_total": 1000,
                },
            )
        ).status_code == 201

        # Collections trend: 7 points, oldest first, the last one is DAY with total 3000.
        trend = (
            await http.get(f"/v1/analytics/collections?date={DAY}&days=7", headers=admin)
        ).json()
        assert len(trend["points"]) == 7
        assert trend["points"][-1]["business_date"] == DAY
        assert float(trend["points"][-1]["total"]) == 3000
        assert float(trend["points"][0]["total"]) == 0  # a quiet day earlier in the window

        # Cylinder movement: our variety shows loaded 10, sold 3, left 47 (50 intake − 3 sold).
        movement = (
            await http.get(f"/v1/analytics/cylinder-movement?date={DAY}", headers=admin)
        ).json()
        row = next(r for r in movement["rows"] if r["code"] == TYPE_CODE)
        assert row["loaded"] == 10
        assert row["sold"] == 3
        assert row["left"] == 47
    finally:
        await _cleanup()
