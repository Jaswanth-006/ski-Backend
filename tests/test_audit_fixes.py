"""Audit fixes: day reopen + closed-day lock, route expenses, repayments in the box, inactive
people, stock checks, paise, no override, unknown people, dashboard totals, audit rows."""

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

TYPE_CODE = "ZZ-fix"
ITEM_NAME = "ZZ-fix-fuel"
DAY = dt.date(2097, 3, 4)
DS = DAY.isoformat()


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


async def _sale(http: AsyncClient, h: dict[str, str], body: dict[str, Any]) -> Any:
    return await http.post(
        "/v1/sales", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json=body
    )


async def _box(http: AsyncClient, h: dict[str, str]) -> Any:
    return (await http.get(f"/v1/cashier-box/{DS}", headers=h)).json()


async def test_audit_fixes(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    boy = str(users.delivery_id)
    tag = uuid.uuid4().hex[:6]
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Fix"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={
                "cylinder_type_id": type_id,
                "unit_price": 979.10,
                "effective_date": "2000-01-01",
            },
        )
        await http.post(
            "/v1/stock/ac4",
            headers=office,
            json={"business_date": DS, "cylinders": [{"cylinder_type_id": type_id, "qty": 40}]},
        )
        item_id = (
            await http.post("/v1/expense-items", headers=admin, json={"name": f"{ITEM_NAME}-{tag}"})
        ).json()["id"]

        # #10 paise: 3 × 979.10 = 2937.30; online arrives as a float with a binary tail.
        paise = await _sale(
            http,
            office,
            {
                "invoice_no": f"P-{tag}",
                "delivery_id": boy,
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 3}],
                "online_total": 979.1 * 3,  # 2937.2999999999997
            },
        )
        assert paise.status_code == 201, paise.text

        # #13 no override: even the owner can't post an unbalanced sale.
        unbalanced = await _sale(
            http,
            admin,
            {
                "invoice_no": f"U-{tag}",
                "delivery_id": boy,
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "upi_total": 500,
            },
        )
        assert unbalanced.status_code == 422

        # #14 unknown people → clear errors, not 500s.
        bad_party = await _sale(
            http,
            office,
            {
                "invoice_no": f"X-{tag}",
                "delivery_id": str(users.admin_id),
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "upi_total": 979.10,
            },
        )
        assert bad_party.status_code == 400 and "delivery person" in bad_party.json()["detail"]
        bad_balance = await http.post(
            "/v1/delivery-balances",
            headers=office,
            json={
                "delivery_id": str(users.admin_id),
                "amount": 10,
                "entry_date": DS,
                "kind": "repayment",
            },
        )
        assert bad_balance.status_code == 404
        bad_expense = await http.post(
            "/v1/expenses",
            headers=office,
            json={
                "business_date": DS,
                "item_id": item_id,
                "amount": 10,
                "method": "cash",
                "delivery_id": str(uuid.uuid4()),
            },
        )
        assert bad_expense.status_code == 404

        # #4 route expense settles part of the sale: 10 × 979.10 = 9791
        # = cash 5000 + upi 3791 + fuel 1000; nothing left owed.
        before = await _box(http, admin)
        route = await _sale(
            http,
            office,
            {
                "invoice_no": f"R-{tag}",
                "delivery_id": boy,
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 10}],
                "denominations": [{"note_value": 500, "note_count": 10}],
                "upi_total": 3791,
                "expenses": [{"item_id": item_id, "amount": 1000}],
            },
        )
        assert route.status_code == 201, route.text
        sale = route.json()
        assert float(sale["balance_total"]) == 0 and float(sale["expenses_total"]) == 1000
        assert sale["expenses"][0]["item_id"] == item_id
        after = await _box(http, admin)
        # Collected 5000 + 3791; the fuel never reached the box, so box expenses don't move.
        assert float(after["collected"]) - float(before["collected"]) == 8791
        assert float(after["expenses"]) == float(before["expenses"])
        expenses = (await http.get(f"/v1/expenses?date={DS}", headers=admin)).json()
        assert any(float(e["amount"]) == 1000 for e in expenses)

        # Cancelling the sale removes its route expense too.
        cancelled = await http.post(
            f"/v1/sales/{sale['id']}/cancel", headers=office, json={"reason": "test"}
        )
        assert cancelled.status_code == 200
        expenses = (await http.get(f"/v1/expenses?date={DS}", headers=admin)).json()
        assert not any(float(e["amount"]) == 1000 for e in expenses)

        # #5 repayments land in the cashier box; cash ones in hand cash too.
        await http.post(
            "/v1/delivery-balances",
            headers=office,
            json={"delivery_id": boy, "amount": 700, "entry_date": DS, "kind": "charge"},
        )
        b0 = await _box(http, admin)
        for amount, method in ((300, "cash"), (200, "upi")):
            r = await http.post(
                "/v1/delivery-balances",
                headers=office,
                json={
                    "delivery_id": boy,
                    "amount": amount,
                    "entry_date": DS,
                    "kind": "repayment",
                    "method": method,
                },
            )
            assert r.status_code == 201 and r.json()["method"] == method
        b1 = await _box(http, admin)
        assert float(b1["repaid"]) - float(b0["repaid"]) == 500
        assert float(b1["hand_cash_repaid"]) - float(b0["hand_cash_repaid"]) == 300
        assert float(b1["closing"]) - float(b0["closing"]) == 500

        # #8 dashboard: sale value and unpaid balance for the day.
        eod = (await http.get(f"/v1/analytics/eod?date={DS}", headers=admin)).json()
        assert float(eod["sales_total"]) == 2937.30
        assert float(eod["net_profit"]) == 2937.30 - float(eod["expenses_total"])

        # #7 erv can't send more empties than are in stock (none came back yet).
        erv = await http.post(
            "/v1/stock/erv",
            headers=office,
            json={"business_date": DS, "lines": [{"cylinder_type_id": type_id, "qty": 999}]},
        )
        assert erv.status_code == 409 and "not enough" in erv.json()["detail"]

        # #6 a deactivated boy still shows on the day sheet and while he owes money.
        await http.patch(f"/v1/users/{boy}", headers=admin, json={"is_active": False})
        sheet = (await http.get(f"/v1/day-sheet/{DS}", headers=admin)).json()
        assert any(r["delivery_id"] == boy for r in sheet["rows"])
        owed = (await http.get("/v1/delivery-balances/summary", headers=admin)).json()
        assert any(r["delivery_id"] == boy and float(r["balance"]) > 0 for r in owed)
        await http.patch(f"/v1/users/{boy}", headers=admin, json={"is_active": True})

        # #2/#3 close → office is locked out of every entry; owner can still fix; reopen.
        assert (await http.post(f"/v1/day-sheet/{DS}/close", headers=office)).status_code == 200
        locked = [
            await http.post(
                "/v1/stock/ac4",
                headers=office,
                json={"business_date": DS, "cylinders": [{"cylinder_type_id": type_id, "qty": 1}]},
            ),
            await http.post(
                "/v1/expenses",
                headers=office,
                json={"business_date": DS, "item_id": item_id, "amount": 5, "method": "cash"},
            ),
            await http.post(
                "/v1/delivery-balances",
                headers=office,
                json={"delivery_id": boy, "amount": 5, "entry_date": DS, "kind": "repayment"},
            ),
        ]
        for res in locked:
            assert res.status_code == 409 and "only the owner" in res.json()["detail"]
        owner_fix = await http.post(
            "/v1/expenses",
            headers=admin,
            json={"business_date": DS, "item_id": item_id, "amount": 5, "method": "cash"},
        )
        assert owner_fix.status_code == 201
        assert (await http.post(f"/v1/day-sheet/{DS}/reopen", headers=office)).status_code == 403
        reopened = await http.post(f"/v1/day-sheet/{DS}/reopen", headers=admin)
        assert reopened.status_code == 200 and reopened.json()["is_closed"] is False
        assert (await http.post(f"/v1/day-sheet/{DS}/reopen", headers=admin)).status_code == 409

        # #12 audit rows for stock, balances, cancels, reopen and admin edits.
        for entity, action in (
            ("stock", "stock.ac4"),
            ("delivery_balance", "delivery_balance.repayment"),
            ("sale", "sale.cancel"),
            ("day_sheet", "daysheet.reopen"),
            ("expense_item", "expense_item.create"),
            ("user", "user.update"),
        ):
            rows = (await http.get(f"/v1/audit?entity={entity}", headers=admin)).json()
            assert any(r["action"] == action for r in rows), action
    finally:
        await _cleanup()
