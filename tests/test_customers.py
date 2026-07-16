"""Customer catalog + customer sales tests (Phase I)."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import (
    CashDenomination,
    CashLedger,
    Customer,
    CylinderType,
    Inventory,
    Price,
    Sale,
    SaleLine,
    StockLedger,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-cust"
CUSTOMER = "ZZ-cust-ABC Foods"
DAY = dt.date(2094, 8, 3)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return str(res.json()["access_token"])


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        cids = (await db.scalars(select(Customer.id).where(Customer.name == CUSTOMER))).all()
        for cid in cids:
            sids = (await db.scalars(select(Sale.id).where(Sale.customer_id == cid))).all()
            for sid in sids:
                await db.execute(delete(CashDenomination).where(CashDenomination.sale_id == sid))
                await db.execute(delete(CashLedger).where(CashLedger.sale_id == sid))
                await db.execute(delete(SaleLine).where(SaleLine.sale_id == sid))
                await db.execute(delete(StockLedger).where(StockLedger.ref_id == sid))
                await db.execute(delete(Sale).where(Sale.id == sid))
        await db.execute(delete(Customer).where(Customer.name == CUSTOMER))
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


async def test_customer_sale_shows_on_day_sheet(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        cust = await http.post("/v1/customers", headers=admin, json={"name": CUSTOMER})
        assert cust.status_code == 201
        customer_id = cust.json()["id"]
        assert (
            await http.post("/v1/customers", headers=admin, json={"name": CUSTOMER})
        ).status_code == 409

        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "CU"}
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
                "cylinders": [{"cylinder_type_id": type_id, "qty": 100}],
            },
        )
        # Direct customer sale — no delivery boy. 40 × 100 = 4000, all UPI.
        res = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "customer_id": customer_id,
                "business_date": DAY.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 40}],
                "upi_total": 4000,
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["party_kind"] == "customer"
        assert res.json()["party_name"] == CUSTOMER

        # A sale must name exactly one party.
        bad = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "business_date": DAY.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "upi_total": 100,
            },
        )
        assert bad.status_code == 422  # neither party given

        sheet = (await http.get(f"/v1/day-sheet/{DAY.isoformat()}", headers=admin)).json()
        crow = next(r for r in sheet["rows"] if r["delivery_id"] == customer_id)
        assert crow["party_kind"] == "customer"
        assert crow["cylinders"] == 40
        assert float(crow["upi"]) == 4000
    finally:
        await _cleanup()
