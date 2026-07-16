"""Delivery-boy balance tests (Phase K)."""

from __future__ import annotations

import datetime as dt

from app.core.config import settings
from app.db.models import DeliveryBalance
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

DAY = dt.date(2093, 5, 6)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return str(res.json()["access_token"])


async def _cleanup(delivery_id: str) -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(DeliveryBalance).where(DeliveryBalance.delivery_id == delivery_id))
        await db.commit()
    await engine.dispose()


async def test_balance_charge_repayment_summary_and_day_sheet(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    boy = str(users.delivery_id)
    await _cleanup(boy)
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        # Boy owes 5000 (charge on DAY).
        c = await http.post(
            "/v1/delivery-balances",
            headers=admin,
            json={
                "delivery_id": boy,
                "amount": 5000,
                "entry_date": DAY.isoformat(),
                "kind": "charge",
            },
        )
        assert c.status_code == 201
        # Pays back 2500 later.
        await http.post(
            "/v1/delivery-balances",
            headers=admin,
            json={
                "delivery_id": boy,
                "amount": 2500,
                "entry_date": (DAY + dt.timedelta(days=3)).isoformat(),
                "kind": "repayment",
            },
        )

        summary = (await http.get("/v1/delivery-balances/summary", headers=admin)).json()
        row = next(r for r in summary if r["delivery_id"] == boy)
        assert float(row["charged"]) == 5000
        assert float(row["repaid"]) == 2500
        assert float(row["balance"]) == 2500  # remaining

        entries = (await http.get(f"/v1/delivery-balances?delivery_id={boy}", headers=admin)).json()
        assert len(entries) == 2
        assert {e["kind"] for e in entries} == {"charge", "repayment"}

        # The day of the charge shows it on the day sheet for that boy.
        sheet = (await http.get(f"/v1/day-sheet/{DAY.isoformat()}", headers=admin)).json()
        drow = next(r for r in sheet["rows"] if r["delivery_id"] == boy)
        assert float(drow["balance"]) == 5000
    finally:
        await _cleanup(boy)
