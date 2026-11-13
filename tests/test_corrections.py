"""Corrections: edit / delete purchase entries, expenses, deposits, balance entries, credits."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.config import settings
from app.db.models import CylinderType, Inventory, Price, SaleLine, StockLedger
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-corr"
DAY = dt.date(2098, 5, 6)
DS = DAY.isoformat()
WHY = {"reason": "typo"}


async def _token(http: AsyncClient, phone: str) -> dict[str, str]:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
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


async def _stock(http: AsyncClient, h: dict[str, str], type_id: str) -> tuple[int, int, int]:
    inv = next(
        r["quantity"]
        for r in (await http.get("/v1/inventory", headers=h)).json()
        if r["cylinder_type_id"] == type_id
    )
    ov = (await http.get(f"/v1/stock/overview?date={DS}", headers=h)).json()
    row = next(r for r in ov["cylinders"] if r["cylinder_type_id"] == type_id)
    return inv, row["full_closing"], row["empty_closing"]


async def _entries(http: AsyncClient, h: dict[str, str], kind: str) -> list[Any]:
    rows = (await http.get(f"/v1/stock/entries?date={DS}", headers=h)).json()
    return [e for e in rows if e["kind"] == kind]


async def test_corrections(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    boy = str(users.delivery_id)
    tag = uuid.uuid4().hex[:6]
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Corr"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 100, "effective_date": "2000-01-01"},
        )

        # ---- Purchase: ac4 50, edit to 40.
        await http.post(
            "/v1/stock/ac4",
            headers=office,
            json={"business_date": DS, "cylinders": [{"cylinder_type_id": type_id, "qty": 50}]},
        )
        (ac4,) = await _entries(http, admin, "ac4")
        line = {"cylinder_type_id": type_id, "condition": "full", "qty": 40}
        edited = await http.put(
            f"/v1/stock/entries/{ac4['entry_id']}",
            headers=office,
            json={**WHY, "business_date": DS, "lines": [line]},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["lines"][0]["qty"] == 40
        assert await _stock(http, admin, type_id) == (40, 40, 0)

        # Sell 30 (30 empties back), then the ac4 can't drop below what was sold.
        sale = await http.post(
            "/v1/sales",
            headers={**office, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "invoice_no": f"C-{tag}",
                "delivery_id": boy,
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 30}],
                "upi_total": 2000,
                "balance_total": 1000,
            },
        )
        assert sale.status_code == 201, sale.text
        too_low = await http.put(
            f"/v1/stock/entries/{ac4['entry_id']}",
            headers=office,
            json={**WHY, "business_date": DS, "lines": [{**line, "qty": 20}]},
        )
        assert too_low.status_code == 409 and "not enough" in too_low.json()["detail"]
        gone = await http.post(
            f"/v1/stock/entries/{ac4['entry_id']}/delete", headers=office, json=WHY
        )
        assert gone.status_code == 409
        assert await _stock(http, admin, type_id) == (10, 10, 30)  # unchanged

        # erv 10 → edit to 12 → delete.
        await http.post(
            "/v1/stock/erv",
            headers=office,
            json={"business_date": DS, "lines": [{"cylinder_type_id": type_id, "qty": 10}]},
        )
        (erv,) = await _entries(http, admin, "erv")
        r = await http.put(
            f"/v1/stock/entries/{erv['entry_id']}",
            headers=office,
            json={
                **WHY,
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "condition": "empty", "qty": 12}],
            },
        )
        assert r.status_code == 200
        assert (await _stock(http, admin, type_id))[2] == 18
        r = await http.post(f"/v1/stock/entries/{erv['entry_id']}/delete", headers=office, json=WHY)
        assert r.status_code == 204
        assert (await _stock(http, admin, type_id))[2] == 30
        assert await _entries(http, admin, "erv") == []

        # ---- Expenses: edit amount, then delete.
        item_id = (
            await http.post("/v1/expense-items", headers=admin, json={"name": f"ZZ-corr-{tag}"})
        ).json()["id"]
        exp = (
            await http.post(
                "/v1/expenses",
                headers=office,
                json={"business_date": DS, "item_id": item_id, "amount": 300, "method": "cash"},
            )
        ).json()
        r = await http.put(
            f"/v1/expenses/{exp['id']}",
            headers=office,
            json={**WHY, "business_date": DS, "item_id": item_id, "amount": 250, "method": "cash"},
        )
        assert r.status_code == 204
        listed = (await http.get(f"/v1/expenses?date={DS}", headers=admin)).json()
        assert [float(e["amount"]) for e in listed if e["id"] == exp["id"]] == [250]
        assert (
            await http.put(f"/v1/expenses/{exp['id']}", headers=office, json={"reason": "x"})
        ).status_code == 422
        r = await http.post(f"/v1/expenses/{exp['id']}/delete", headers=office, json=WHY)
        assert r.status_code == 204
        listed = (await http.get(f"/v1/expenses?date={DS}", headers=admin)).json()
        assert not any(e["id"] == exp["id"] for e in listed)

        # ---- Deposits: edit amount, cashier box follows; delete.
        before = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        dep = (
            await http.post(
                "/v1/transfers",
                headers=office,
                json={
                    "business_date": DS,
                    "amount": 500,
                    "source_kind": "cashier_box",
                    "dest_kind": "person",
                    "dest_person_name": f"ZZ {tag}",
                    "method": "cash",
                },
            )
        ).json()
        r = await http.put(
            f"/v1/transfers/{dep['id']}",
            headers=office,
            json={**WHY, "business_date": DS, "amount": 400, "method": "cash"},
        )
        assert r.status_code == 204
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["deposited"]) - float(before["deposited"]) == 400
        assert (
            await http.post(f"/v1/transfers/{dep['id']}/delete", headers=office, json=WHY)
        ).status_code == 204
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["deposited"]) == float(before["deposited"])

        # ---- Balance entries: the sale's charge belongs to the invoice; a repayment is editable.
        entries = (await http.get(f"/v1/balance-entries?date={DS}", headers=admin)).json()
        sale_charge = next(e for e in entries if e["invoice_no"] == f"C-{tag}")
        r = await http.put(
            f"/v1/delivery-balances/{sale_charge['id']}",
            headers=office,
            json={**WHY, "entry_date": DS, "amount": 1},
        )
        assert r.status_code == 409 and "invoice" in r.json()["detail"]
        rep = (
            await http.post(
                "/v1/delivery-balances",
                headers=office,
                json={"delivery_id": boy, "amount": 600, "entry_date": DS, "kind": "repayment"},
            )
        ).json()
        r = await http.put(
            f"/v1/delivery-balances/{rep['id']}",
            headers=office,
            json={**WHY, "entry_date": DS, "amount": 700, "method": "upi"},
        )
        assert r.status_code == 204
        entries = (await http.get(f"/v1/balance-entries?date={DS}", headers=admin)).json()
        mine = next(e for e in entries if e["id"] == rep["id"])
        assert float(mine["amount"]) == 700 and mine["method"] == "upi"
        owed = (await http.get("/v1/delivery-balances/summary", headers=admin)).json()
        assert float(next(o for o in owed if o["delivery_id"] == boy)["balance"]) == 300
        r = await http.post(f"/v1/delivery-balances/{rep['id']}/delete", headers=office, json=WHY)
        assert r.status_code == 204

        # ---- Credits: edit, delete.
        credit = (
            await http.post(
                "/v1/credits",
                headers=office,
                json={"person_name": f"ZZ {tag}", "amount": 1000, "given_date": DS},
            )
        ).json()
        r = await http.put(
            f"/v1/credits/{credit['id']}",
            headers=office,
            json={**WHY, "person_name": f"ZZ {tag} K", "amount": 900, "given_date": DS},
        )
        assert r.status_code == 204
        credits = (await http.get("/v1/credits", headers=admin)).json()
        c = next(x for x in credits if x["id"] == credit["id"])
        assert c["person_name"] == f"ZZ {tag} K" and float(c["amount"]) == 900
        assert (
            await http.post(f"/v1/credits/{credit['id']}/delete", headers=office, json=WHY)
        ).status_code == 204

        # ---- Closed day: office can't correct, owner can.
        exp2 = (
            await http.post(
                "/v1/expenses",
                headers=office,
                json={"business_date": DS, "item_id": item_id, "amount": 50, "method": "cash"},
            )
        ).json()
        await http.post(f"/v1/day-sheet/{DS}/close", headers=admin)
        r = await http.post(f"/v1/expenses/{exp2['id']}/delete", headers=office, json=WHY)
        assert r.status_code == 409 and "only the owner" in r.json()["detail"]
        assert (
            await http.post(f"/v1/expenses/{exp2['id']}/delete", headers=admin, json=WHY)
        ).status_code == 204
        assert (
            await http.post(f"/v1/expenses/{uuid.uuid4()}/delete", headers=admin, json=WHY)
        ).status_code == 404

        # ---- Audited, with the reason.
        for entity, action in (
            ("stock", "stock.ac4.edit"),
            ("stock", "stock.erv.delete"),
            ("expense", "expense.edit"),
            ("transfer", "transfer.delete"),
            ("delivery_balance", "delivery_balance.edit"),
            ("credit", "credit.delete"),
        ):
            rows = (await http.get(f"/v1/audit?entity={entity}", headers=admin)).json()
            hit = next((x for x in rows if x["action"] == action), None)
            assert hit is not None, action
            assert hit["new_value"]["reason"] == "typo", action
    finally:
        await _cleanup()
