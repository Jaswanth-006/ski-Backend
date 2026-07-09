"""Deposit / transfer tests (Phase 8-C)."""

from __future__ import annotations

import datetime as dt

from app.core.config import settings
from app.db.models import Bank, BankAccount, Transfer, Vendor
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

BANK_NAME = "ZZ Transfer Bank"
VENDOR_NAME = "ZZ Transfer Vendor"
DAY = dt.date(2097, 1, 1)
DAY_S = DAY.isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Transfer).where(Transfer.business_date == DAY))
        bank_ids = (await db.scalars(select(Bank.id).where(Bank.name == BANK_NAME))).all()
        for bid in bank_ids:
            await db.execute(delete(BankAccount).where(BankAccount.bank_id == bid))
        await db.execute(delete(Bank).where(Bank.name == BANK_NAME))
        await db.execute(delete(Vendor).where(Vendor.name == VENDOR_NAME))
        await db.commit()
    await engine.dispose()


async def _balance(http: AsyncClient, headers: dict[str, str], account_id: str) -> float:
    res = await http.get("/v1/bank-accounts?active=all", headers=headers)
    for a in res.json():
        if a["id"] == account_id:
            return float(a["balance"])
    raise KeyError(account_id)


async def test_deposits_move_money_between_sources(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        bank_id = (await http.post("/v1/banks", headers=admin, json={"name": BANK_NAME})).json()[
            "id"
        ]
        acc_a = (
            await http.post(
                "/v1/bank-accounts",
                headers=admin,
                json={"bank_id": bank_id, "account_type": "savings"},
            )
        ).json()["id"]
        acc_b = (
            await http.post(
                "/v1/bank-accounts",
                headers=admin,
                json={"bank_id": bank_id, "account_type": "current"},
            )
        ).json()["id"]
        vendor_id = (
            await http.post("/v1/vendors", headers=admin, json={"name": VENDOR_NAME})
        ).json()["id"]

        # Box → vendor (external): allowed, doesn't touch bank balances.
        r1 = await http.post(
            "/v1/transfers",
            headers=admin,
            json={
                "business_date": DAY_S,
                "amount": 1000,
                "source_kind": "cashier_box",
                "dest_kind": "vendor",
                "dest_vendor_id": vendor_id,
                "method": "cash",
            },
        )
        assert r1.status_code == 201, r1.text
        assert r1.json()["source_label"] == "Cashier box"
        assert r1.json()["dest_label"] == VENDOR_NAME

        # Box → own account A: A goes up 5000.
        await http.post(
            "/v1/transfers",
            headers=admin,
            json={
                "business_date": DAY_S,
                "amount": 5000,
                "source_kind": "cashier_box",
                "dest_kind": "bank_account",
                "dest_bank_account_id": acc_a,
                "method": "transfer",
            },
        )
        assert await _balance(http, admin, acc_a) == 5000

        # A → B: A down 2000, B up 2000 (box untouched).
        await http.post(
            "/v1/transfers",
            headers=admin,
            json={
                "business_date": DAY_S,
                "amount": 2000,
                "source_kind": "bank_account",
                "source_bank_account_id": acc_a,
                "dest_kind": "bank_account",
                "dest_bank_account_id": acc_b,
                "method": "transfer",
            },
        )
        assert await _balance(http, admin, acc_a) == 3000
        assert await _balance(http, admin, acc_b) == 2000

        # History lists all three for the date.
        listed = await http.get(f"/v1/transfers?start={DAY_S}&end={DAY_S}", headers=admin)
        assert len(listed.json()) == 3
    finally:
        await _cleanup()
