"""A sale's money moves: cash stays in the cashier box, UPI goes to a bank account, online
goes to the vendor (IOC) — recorded with the sale, undone when it is cancelled."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.config import settings
from app.db.models import (
    Bank,
    BankAccount,
    CylinderType,
    Inventory,
    Price,
    SaleLine,
    StockLedger,
    Transfer,
    Vendor,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-money"
NAME = "ZZ Money"
DAY = dt.date(2093, 6, 9)
DS = DAY.isoformat()


async def _token(http: AsyncClient, phone: str) -> dict[str, str]:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(
            delete(Transfer).where(Transfer.business_date.in_([DAY, DAY - dt.timedelta(days=1)]))
        )
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(SaleLine).where(SaleLine.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        bank_ids = (await db.scalars(select(Bank.id).where(Bank.name == NAME))).all()
        for bid in bank_ids:
            await db.execute(delete(BankAccount).where(BankAccount.bank_id == bid))
        await db.execute(delete(Bank).where(Bank.name == NAME))
        await db.execute(delete(Vendor).where(Vendor.name == NAME))
        await db.commit()
    await engine.dispose()


async def test_sale_records_where_the_money_went(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    tag = uuid.uuid4().hex[:8]
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Money"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 1000, "effective_date": "2000-01-01"},
        )
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "invoice_no": f"IOC-{tag}",
                "business_date": DS,
                "cylinders": [{"cylinder_type_id": type_id, "qty": 20}],
            },
        )
        bank = (await http.post("/v1/banks", headers=admin, json={"name": NAME})).json()["id"]
        acc = (
            await http.post(
                "/v1/bank-accounts",
                headers=admin,
                json={"bank_id": bank, "account_type": "current", "opening_balance": 1000},
            )
        ).json()["id"]
        vendor = (await http.post("/v1/vendors", headers=admin, json={"name": NAME})).json()["id"]
        box_before = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()

        async def balances() -> tuple[float, float]:
            accs = (await http.get("/v1/bank-accounts?active=all", headers=admin)).json()
            vens = (await http.get("/v1/vendors?active=all", headers=admin)).json()
            return (
                float(next(a for a in accs if a["id"] == acc)["balance"]),
                float(next(v for v in vens if v["id"] == vendor)["paid"]),
            )

        # 10 × 1000: cash 5000, UPI 3000 → bank account, online 2000 → vendor.
        body: dict[str, Any] = {
            "invoice_no": f"M-{tag}",
            "delivery_id": str(users.delivery_id),
            "business_date": DS,
            "lines": [{"cylinder_type_id": type_id, "qty": 10}],
            "denominations": [{"note_value": 500, "note_count": 10}],
            "upi_total": 3000,
            "online_total": 2000,
            "upi_account_id": acc,
            "online_vendor_id": vendor,
        }
        # Back-dated: the 20 cylinders arrived on DAY, so nothing could be sold the day before.
        early = await http.post(
            "/v1/sales",
            headers={**office, "Idempotency-Key": str(uuid.uuid4())},
            json={
                **body,
                "invoice_no": f"E-{tag}",
                "business_date": (DAY - dt.timedelta(days=1)).isoformat(),
                "upi_account_id": None,
                "online_vendor_id": None,
            },
        )
        assert early.status_code == 409 and "insufficient stock" in early.json()["detail"]

        bad = await http.post(
            "/v1/sales",
            headers={**office, "Idempotency-Key": str(uuid.uuid4())},
            json={**body, "upi_account_id": str(uuid.uuid4())},
        )
        assert bad.status_code in (400, 404, 422), bad.text
        res = await http.post(
            "/v1/sales", headers={**office, "Idempotency-Key": str(uuid.uuid4())}, json=body
        )
        assert res.status_code == 201, res.text
        sale = res.json()
        assert sale["upi_account_id"] == acc and sale["online_vendor_id"] == vendor

        assert await balances() == (4000, 2000)  # bank 1000 + 3000 UPI; vendor paid 2000
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        # Cash stays in the box; the UPI came in and went on to the bank.
        assert float(box["closing"]) - float(box_before["closing"]) == 5000
        assert float(box["hand_cash_closing"]) - float(box_before["hand_cash_closing"]) == 5000

        deps = (await http.get(f"/v1/transfers?start={DS}&end={DS}", headers=admin)).json()
        mine = {d["dest_label"]: d for d in deps if d["sale_id"] == sale["id"]}
        assert mine[f"{NAME} · current"]["source_label"] == "Cashier box"
        assert mine[NAME]["source_label"] == "Customers (online)"
        # They belong to the invoice: Edit entries can't change them on their own.
        r = await http.post(
            f"/v1/transfers/{mine[NAME]['id']}/delete", headers=office, json={"reason": "typo"}
        )
        assert r.status_code == 409 and f"M-{tag}" in r.json()["detail"]

        # Cancelling the sale takes its deposits with it.
        r = await http.post(
            f"/v1/sales/{sale['id']}/cancel", headers=office, json={"reason": "wrong boy"}
        )
        assert r.status_code == 200, r.text
        assert await balances() == (1000, 0)
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["closing"]) == float(box_before["closing"])
        assert float(box["hand_cash_closing"]) == float(box_before["hand_cash_closing"])

        # A UPI repayment can go straight on to the bank account.
        r = await http.post(
            "/v1/delivery-balances",
            headers=office,
            json={
                "delivery_id": str(users.delivery_id),
                "amount": 400,
                "entry_date": DS,
                "kind": "repayment",
                "method": "upi",
                "upi_account_id": acc,
            },
        )
        assert r.status_code == 201, r.text
        rep_id = r.json()["id"]
        assert await balances() == (1400, 0)
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["closing"]) == float(box_before["closing"])  # in and on to the bank
        assert float(box["hand_cash_closing"]) == float(box_before["hand_cash_closing"])
        assert float(box["upi_to_bank"]) >= 400
        # Its deposit follows the repayment and can't be changed on its own.
        deps = (await http.get(f"/v1/transfers?start={DS}&end={DS}", headers=admin)).json()
        (upi_dep,) = [d for d in deps if d["balance_entry_id"] == rep_id]
        r = await http.post(
            f"/v1/transfers/{upi_dep['id']}/delete", headers=office, json={"reason": "typo"}
        )
        assert r.status_code == 409 and "repayment" in r.json()["detail"]
        r = await http.put(
            f"/v1/delivery-balances/{rep_id}",
            headers=office,
            json={"reason": "typo", "entry_date": DS, "amount": 300, "method": "upi"},
        )
        assert r.status_code == 204, r.text
        assert await balances() == (1300, 0)
        r = await http.post(
            f"/v1/delivery-balances/{rep_id}/delete", headers=office, json={"reason": "typo"}
        )
        assert r.status_code == 204, r.text
        assert await balances() == (1000, 0)
        # A bad bank account records nothing.
        r = await http.post(
            "/v1/delivery-balances",
            headers=office,
            json={
                "delivery_id": str(users.delivery_id),
                "amount": 50,
                "entry_date": DS,
                "kind": "repayment",
                "method": "upi",
                "upi_account_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 400
    finally:
        await _cleanup()
