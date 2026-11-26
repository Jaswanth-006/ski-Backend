"""Opening balances (bank accounts, vendors, people) and debtors / creditors."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import Bank, BankAccount, Person, Transfer, Vendor
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TAG = "ZZ Open"
DAY = dt.date(2096, 3, 1)
DS = DAY.isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Transfer).where(Transfer.business_date == DAY))
        bank_ids = (await db.scalars(select(Bank.id).where(Bank.name.like(f"{TAG}%")))).all()
        for bid in bank_ids:
            await db.execute(delete(BankAccount).where(BankAccount.bank_id == bid))
        await db.execute(delete(Bank).where(Bank.name.like(f"{TAG}%")))
        await db.execute(delete(Vendor).where(Vendor.name.like(f"{TAG}%")))
        await db.execute(delete(Person).where(Person.name.like(f"{TAG}%")))
        await db.commit()
    await engine.dispose()


def _find(rows: list[dict[str, object]], row_id: str) -> dict[str, object]:
    return next(r for r in rows if r["id"] == row_id)


async def test_opening_balances_and_people(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    tag = uuid.uuid4().hex[:6]
    try:
        bank = (await http.post("/v1/banks", headers=admin, json={"name": f"{TAG} {tag}"})).json()
        r = await http.post(
            "/v1/bank-accounts",
            headers=admin,
            json={"bank_id": bank["id"], "account_type": "current", "opening_balance": "10000"},
        )
        assert r.status_code == 201, r.text
        acc = r.json()
        assert float(acc["opening_balance"]) == 10000 and float(acc["balance"]) == 10000

        vendor = (
            await http.post(
                "/v1/vendors",
                headers=admin,
                json={"name": f"{TAG} V {tag}", "opening_balance": "50000"},
            )
        ).json()
        assert float(vendor["total_paid"]) == 50000
        r = await http.post(
            "/v1/vendors", headers=admin, json={"name": f"{TAG} X {tag}", "opening_balance": -1}
        )
        assert r.status_code == 422

        # Office can add people; the same name can be a debtor and a creditor.
        debtor = (
            await http.post(
                "/v1/people",
                headers=office,
                json={"name": f"{TAG} Ravi {tag}", "kind": "debtor", "opening_balance": 2000},
            )
        ).json()
        creditor = (
            await http.post(
                "/v1/people",
                headers=office,
                json={"name": f"{TAG} Ravi {tag}", "kind": "creditor", "opening_balance": 5000},
            )
        ).json()
        assert debtor["kind"] == "debtor" and creditor["kind"] == "creditor"
        r = await http.post(
            "/v1/people", headers=office, json={"name": f"{TAG} Ravi {tag}", "kind": "debtor"}
        )
        assert r.status_code == 409

        async def move(body: dict[str, object]) -> dict[str, object]:
            res = await http.post(
                "/v1/transfers",
                headers=office,
                json={"business_date": DS, "method": "cash", **body},
            )
            assert res.status_code == 201, res.text
            out: dict[str, object] = res.json()
            return out

        # Bank → vendor 3000; bank → debtor 1000; debtor pays 500 back into the bank;
        # creditor lends 4000 into the bank; we repay the creditor 1500 from the bank.
        await move(
            {
                "amount": 3000,
                "source_kind": "bank_account",
                "source_bank_account_id": acc["id"],
                "dest_kind": "vendor",
                "dest_vendor_id": vendor["id"],
            }
        )
        await move(
            {
                "amount": 1000,
                "source_kind": "bank_account",
                "source_bank_account_id": acc["id"],
                "dest_kind": "person",
                "dest_person_id": debtor["id"],
            }
        )
        back = await move(
            {
                "amount": 500,
                "source_kind": "person",
                "source_person_id": debtor["id"],
                "dest_kind": "bank_account",
                "dest_bank_account_id": acc["id"],
            }
        )
        assert back["source_label"] == f"{TAG} Ravi {tag}"
        await move(
            {
                "amount": 4000,
                "source_kind": "person",
                "source_person_id": creditor["id"],
                "dest_kind": "bank_account",
                "dest_bank_account_id": acc["id"],
            }
        )
        await move(
            {
                "amount": 1500,
                "source_kind": "bank_account",
                "source_bank_account_id": acc["id"],
                "dest_kind": "person",
                "dest_person_id": creditor["id"],
            }
        )

        accounts = (await http.get("/v1/bank-accounts?active=all", headers=admin)).json()
        # 10000 − 3000 − 1000 + 500 + 4000 − 1500
        assert float(_find(accounts, acc["id"])["balance"]) == 9000
        vendors = (await http.get("/v1/vendors?active=all", headers=admin)).json()
        v = _find(vendors, vendor["id"])
        assert float(v["paid"]) == 3000 and float(v["total_paid"]) == 53000

        people = (await http.get("/v1/people?active=all", headers=office)).json()
        d = _find(people, debtor["id"])
        assert float(d["given"]) == 1000 and float(d["received"]) == 500
        assert float(d["balance"]) == 2500  # 2000 + 1000 − 500: they owe us
        c = _find(people, creditor["id"])
        assert float(c["balance"]) == 7500  # 5000 + 4000 − 1500: we owe them
        debtors = (await http.get("/v1/people?kind=debtor&active=all", headers=office)).json()
        assert all(p["kind"] == "debtor" for p in debtors)

        # Opening balance: only the owner can change it later.
        r = await http.patch(
            f"/v1/people/{debtor['id']}", headers=office, json={"opening_balance": 0}
        )
        assert r.status_code == 403
        r = await http.patch(f"/v1/people/{debtor['id']}", headers=office, json={"phone": "99"})
        assert r.status_code == 200 and r.json()["phone"] == "99"
        r = await http.patch(
            f"/v1/people/{debtor['id']}", headers=admin, json={"opening_balance": 0}
        )
        assert r.status_code == 200 and float(r.json()["balance"]) == 500
        r = await http.patch(
            f"/v1/bank-accounts/{acc['id']}", headers=admin, json={"opening_balance": "0"}
        )
        assert float(r.json()["balance"]) == -1000

        # Shape rules.
        bad = {"business_date": DS, "amount": 1, "method": "cash"}
        r = await http.post(
            "/v1/transfers",
            headers=office,
            json={**bad, "source_kind": "person", "dest_kind": "cashier_box"},
        )
        assert r.status_code == 422  # no source person
        r = await http.post(
            "/v1/transfers",
            headers=office,
            json={
                **bad,
                "source_kind": "person",
                "source_person_id": debtor["id"],
                "dest_kind": "vendor",
                "dest_vendor_id": vendor["id"],
            },
        )
        assert r.status_code == 422  # a person's money comes into the box or a bank
        r = await http.post(
            "/v1/transfers",
            headers=office,
            json={**bad, "source_kind": "cashier_box", "dest_kind": "cashier_box"},
        )
        assert r.status_code == 422
        r = await http.post(
            "/v1/transfers",
            headers=office,
            json={
                **bad,
                "source_kind": "cashier_box",
                "dest_kind": "person",
                "dest_person_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 400

        # The credits page is gone.
        assert (await http.get("/v1/credits", headers=admin)).status_code == 404
    finally:
        await _cleanup()
