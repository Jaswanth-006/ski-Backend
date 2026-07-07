"""Master day sheet + day close/lock tests (Phase 4-A/B)."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import (
    CylinderType,
    DaySheetStatus,
    Inventory,
    Price,
    SaleLine,
    StockLedger,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-ds"
DAY_DATE = dt.date(2098, 6, 1)  # isolated from TODAY used by other tests
DAY = DAY_DATE.isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(DaySheetStatus).where(DaySheetStatus.business_date == DAY_DATE))
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


async def _setup(http: AsyncClient, admin: dict[str, str]) -> str:
    """Create a priced + stocked variety. Returns type_id."""
    type_id: str = (
        await http.post(
            "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "DS"}
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
    return type_id


async def _post_sale(
    http: AsyncClient, admin: dict[str, str], type_id: str, delivery_id: str
) -> int:
    res = await http.post(
        "/v1/sales",
        headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "delivery_id": delivery_id,
            "business_date": DAY,
            "lines": [{"cylinder_type_id": type_id, "qty": 3}],  # revenue 3000
            "denominations": [{"note_value": 1000, "note_count": 2}],  # 2000 cash
            "upi_total": 1000,  # collected 3000
        },
    )
    return res.status_code


async def test_day_sheet_consolidates_and_closes(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin)
        assert await _post_sale(http, admin, type_id, str(users.delivery_id)) == 201

        # Day sheet shows the driver's consolidated row.
        sheet = (await http.get(f"/v1/day-sheet/{DAY}", headers=admin)).json()
        assert sheet["is_closed"] is False
        row = next(r for r in sheet["rows"] if r["delivery_id"] == str(users.delivery_id))
        assert row["cylinders"] == 3
        assert float(row["cash"]) == 2000 and float(row["upi"]) == 1000
        assert float(sheet["totals"]["total"]) == 3000

        # Close the day → locked.
        closed = await http.post(f"/v1/day-sheet/{DAY}/close", headers=admin)
        assert closed.status_code == 200
        assert closed.json()["is_closed"] is True

        # Closing again is rejected.
        assert (await http.post(f"/v1/day-sheet/{DAY}/close", headers=admin)).status_code == 409

        # A closed day rejects new sales.
        assert await _post_sale(http, admin, type_id, str(users.delivery_id)) == 409
    finally:
        await _cleanup()
