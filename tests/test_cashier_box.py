"""Cashier box tests (Phase 8-A) — persistent, carry-over cash-in-hand."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import (
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
    Transfer,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-box"
ITEM_NAME = "ZZ-box-fuel"
D1 = dt.date(2096, 3, 1)
D2 = dt.date(2096, 3, 2)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Transfer).where(Transfer.business_date.in_([D1, D2])))
        await db.execute(delete(Expense).where(Expense.business_date.in_([D1, D2])))
        await db.execute(delete(ExpenseItem).where(ExpenseItem.name == ITEM_NAME))
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


async def _box(http: AsyncClient, headers: dict[str, str], d: dt.date) -> dict[str, float]:
    res = await http.get(f"/v1/cashier-box/{d.isoformat()}", headers=headers)
    return {k: float(v) for k, v in res.json().items() if k != "business_date"}


async def test_cashier_box_carries_over(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Box"}
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

        # Day 1: sell 2 (revenue 2000 = cash 2000).
        await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": D1.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 2}],
                "denominations": [{"note_value": 1000, "note_count": 2}],
                "upi_total": 0,
            },
        )
        d1 = await _box(http, admin, D1)
        assert d1["opening"] == 0 and d1["collected"] == 2000 and d1["closing"] == 2000
        # All-cash sale → hand cash equals the closing balance.
        assert d1["hand_cash_closing"] == 2000

        # Day 2: opening carries the 2000. Sell 1 (1000), deposit 500 from the box.
        await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": D2.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "denominations": [{"note_value": 1000, "note_count": 1}],
                "upi_total": 0,
            },
        )
        await http.post(
            "/v1/transfers",
            headers=admin,
            json={
                "business_date": D2.isoformat(),
                "amount": 500,
                "source_kind": "cashier_box",
                "dest_kind": "person",
                "dest_person_name": "Owner",
                "method": "cash",
            },
        )
        d2 = await _box(http, admin, D2)
        assert d2["opening"] == 2000  # yesterday's closing
        assert d2["collected"] == 1000
        assert d2["deposited"] == 500
        assert d2["closing"] == 2500  # 2000 + 1000 − 500
        assert d2["hand_cash_closing"] == 2500  # all cash: 2000 + 1000 − 500 deposit
    finally:
        await _cleanup()
