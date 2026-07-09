"""Stock opening/closing + per-driver load/return tests (Phase 8-D)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.config import settings
from app.db.models import (
    CashDenomination,
    CashLedger,
    CylinderType,
    Inventory,
    Price,
    Sale,
    SaleLine,
    StockLedger,
    StockLoad,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-load"
D1 = dt.date(2095, 5, 1)
D2 = dt.date(2095, 5, 2)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(StockLoad).where(StockLoad.business_date.in_([D1, D2])))
        sale_ids = (await db.scalars(select(Sale.id).where(Sale.business_date.in_([D1, D2])))).all()
        for sid in sale_ids:
            await db.execute(delete(CashDenomination).where(CashDenomination.sale_id == sid))
            await db.execute(delete(CashLedger).where(CashLedger.sale_id == sid))
            await db.execute(delete(SaleLine).where(SaleLine.sale_id == sid))
        await db.execute(delete(Sale).where(Sale.business_date.in_([D1, D2])))
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


async def _sheet(http: AsyncClient, headers: dict[str, str], d: dt.date) -> Any:
    return (await http.get(f"/v1/day-sheet/{d.isoformat()}", headers=headers)).json()


async def test_stock_open_close_and_driver_loads(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Load"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 1000, "effective_date": "2000-01-01"},
        )
        # Morning: 500 into the warehouse on D1.
        await http.post(
            "/v1/stock/intake",
            headers=admin,
            json={
                "business_date": D1.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 500}],
            },
        )
        # Driver loads 400, returns 100.
        assert (
            await http.post(
                "/v1/stock/loads",
                headers=admin,
                json={
                    "business_date": D1.isoformat(),
                    "delivery_id": str(users.delivery_id),
                    "cylinder_type_id": type_id,
                    "loaded_qty": 400,
                    "returned_qty": 100,
                },
            )
        ).status_code == 201
        # Sells 300 (paid by UPI so reconciliation is trivial).
        assert (
            await http.post(
                "/v1/sales",
                headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
                json={
                    "delivery_id": str(users.delivery_id),
                    "business_date": D1.isoformat(),
                    "lines": [{"cylinder_type_id": type_id, "qty": 300}],
                    "denominations": [],
                    "upi_total": 300000,
                },
            )
        ).status_code == 201

        sheet = await _sheet(http, admin, D1)
        stock = sheet["stock"]
        assert stock == {"opening": 0, "loaded": 400, "sold": 300, "returned": 100, "closing": 200}
        row = next(r for r in sheet["rows"] if r["delivery_id"] == str(users.delivery_id))
        assert row["loaded"] == 400 and row["cylinders"] == 300 and row["returned"] == 100

        # Next day opens at 200 (carried over) with no activity.
        sheet2 = await _sheet(http, admin, D2)
        assert sheet2["stock"]["opening"] == 200 and sheet2["stock"]["closing"] == 200
    finally:
        await _cleanup()
