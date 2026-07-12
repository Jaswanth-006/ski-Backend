"""Date-range report tests (Phase 8-E)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.config import settings
from app.db.models import (
    Bank,
    BankAccount,
    CashDenomination,
    CashLedger,
    CylinderType,
    Expense,
    ExpenseItem,
    Inventory,
    Price,
    Sale,
    SaleLine,
    StockLedger,
    StockLoad,
    Transfer,
    Vendor,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-rep"
ITEM_NAME = "ZZ-rep-A4"
VENDOR_NAME = "ZZ-rep-vendor"
D = dt.date(2094, 4, 1)
DS = D.isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Transfer).where(Transfer.business_date == D))
        await db.execute(delete(StockLoad).where(StockLoad.business_date == D))
        await db.execute(delete(Expense).where(Expense.business_date == D))
        await db.execute(delete(ExpenseItem).where(ExpenseItem.name == ITEM_NAME))
        await db.execute(delete(Vendor).where(Vendor.name == VENDOR_NAME))
        bank_ids = (await db.scalars(select(Bank.id).where(Bank.name == VENDOR_NAME))).all()
        for bid in bank_ids:
            await db.execute(delete(BankAccount).where(BankAccount.bank_id == bid))
        await db.execute(delete(Bank).where(Bank.name == VENDOR_NAME))
        sale_ids = (await db.scalars(select(Sale.id).where(Sale.business_date == D))).all()
        for sid in sale_ids:
            await db.execute(delete(CashDenomination).where(CashDenomination.sale_id == sid))
            await db.execute(delete(CashLedger).where(CashLedger.sale_id == sid))
            await db.execute(delete(SaleLine).where(SaleLine.sale_id == sid))
        await db.execute(delete(Sale).where(Sale.business_date == D))
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


async def _report(http: AsyncClient, headers: dict[str, str], name: str) -> Any:
    return (await http.get(f"/v1/reports/{name}?start={DS}&end={DS}", headers=headers)).json()


async def test_date_range_reports(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Rep"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 1000, "effective_date": "2000-01-01"},
        )
        # ac4: receive 500 full from the plant.
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "business_date": DS,
                "cylinders": [{"cylinder_type_id": type_id, "qty": 500}],
            },
        )
        # Sell 300 (→ 300 empties come back), then send 100 empties to the plant via erv.
        await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 300}],
                "denominations": [],
                "upi_total": 300000,
            },
        )
        await http.post(
            "/v1/stock/erv",
            headers=admin,
            json={
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 100}],
            },
        )
        item_id = (
            await http.post("/v1/expense-items", headers=admin, json={"name": ITEM_NAME})
        ).json()["id"]
        await http.post(
            "/v1/expenses",
            headers=admin,
            json={"business_date": DS, "item_id": item_id, "amount": 200, "method": "cash"},
        )
        vendor_id = (
            await http.post("/v1/vendors", headers=admin, json={"name": VENDOR_NAME})
        ).json()["id"]
        await http.post(
            "/v1/transfers",
            headers=admin,
            json={
                "business_date": DS,
                "amount": 1000,
                "source_kind": "cashier_box",
                "dest_kind": "vendor",
                "dest_vendor_id": vendor_id,
                "method": "cash",
            },
        )

        stock = next(r for r in await _report(http, admin, "stock") if r["code"] == TYPE_CODE)
        assert (stock["ac4"], stock["erv"]) == (500, 100)

        deliv = next(
            r
            for r in await _report(http, admin, "delivery")
            if r["delivery_id"] == str(users.delivery_id)
        )
        assert float(deliv["sales"]) == 300000  # 300 × 1000
        assert (deliv["full_cylinders"], deliv["empty_cylinders"]) == (300, 300)

        exp = next(r for r in await _report(http, admin, "expenses") if r["item_name"] == ITEM_NAME)
        assert float(exp["total"]) == 200 and exp["count"] == 1

        dep = next(
            r for r in await _report(http, admin, "deposits") if r["recipient"] == VENDOR_NAME
        )
        assert float(dep["total"]) == 1000 and dep["kind"] == "vendor"
    finally:
        await _cleanup()
