"""Banking master-data tests (Phase 8-B)."""

from __future__ import annotations

from app.core.config import settings
from app.db.models import Bank, BankAccount, Vendor
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

BANK_NAME = "ZZ Test Bank"
VENDOR_NAME = "ZZ Test Vendor"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        bank_ids = (await db.scalars(select(Bank.id).where(Bank.name == BANK_NAME))).all()
        for bid in bank_ids:
            await db.execute(delete(BankAccount).where(BankAccount.bank_id == bid))
        await db.execute(delete(Bank).where(Bank.name == BANK_NAME))
        await db.execute(delete(Vendor).where(Vendor.name == VENDOR_NAME))
        await db.commit()
    await engine.dispose()


async def test_bank_account_vendor_crud(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        # Create a bank, an account under it, and a vendor.
        bank = await http.post("/v1/banks", headers=admin, json={"name": BANK_NAME})
        assert bank.status_code == 201, bank.text
        bank_id = bank.json()["id"]

        acc = await http.post(
            "/v1/bank-accounts",
            headers=admin,
            json={"bank_id": bank_id, "account_type": "savings", "label": "Main"},
        )
        assert acc.status_code == 201, acc.text
        assert acc.json()["bank_name"] == BANK_NAME
        account_id = acc.json()["id"]

        vendor = await http.post("/v1/vendors", headers=admin, json={"name": VENDOR_NAME})
        assert vendor.status_code == 201, vendor.text

        # Everything is editable.
        edited = await http.patch(
            f"/v1/bank-accounts/{account_id}",
            headers=admin,
            json={"account_type": "current", "label": "Ops"},
        )
        assert edited.status_code == 200
        assert edited.json()["account_type"] == "current"

        # Duplicate bank name is rejected.
        dup = await http.post("/v1/banks", headers=admin, json={"name": BANK_NAME})
        assert dup.status_code == 409

        # Deactivate hides from the default (active) listing.
        assert (
            await http.patch(f"/v1/banks/{bank_id}", headers=admin, json={"is_active": False})
        ).status_code == 200
        active = await http.get("/v1/banks", headers=admin)
        assert BANK_NAME not in [b["name"] for b in active.json()]
        all_banks = await http.get("/v1/banks?active=all", headers=admin)
        assert BANK_NAME in [b["name"] for b in all_banks.json()]
    finally:
        await _cleanup()


async def test_office_cannot_create_bank(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    res = await http.post("/v1/banks", headers=office, json={"name": "ZZ Nope Bank"})
    assert res.status_code == 403
