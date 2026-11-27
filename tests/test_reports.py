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
        await db.execute(
            delete(Transfer).where(Transfer.business_date.in_([D, D - dt.timedelta(days=1)]))
        )
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
                "invoice_no": f"IOC-{uuid.uuid4().hex[:10]}",
                "business_date": DS,
                "cylinders": [{"cylinder_type_id": type_id, "qty": 500}],
            },
        )
        # Sell 300 (→ 300 empties come back), then send 100 empties to the plant via erv.
        await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "invoice_no": f"T-{uuid.uuid4()}",
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

        # Stock: per cylinder, a full row and an empty row — A + B − C = closing.
        rows = {
            r["condition"]: r for r in await _report(http, admin, "stock") if r["code"] == TYPE_CODE
        }
        full, empty = rows["full"], rows["empty"]
        # Full: received = ac4 500, issue = sold 300.
        assert [full[k] for k in ("opening", "received", "issue", "other", "closing")] == [
            0,
            500,
            300,
            0,
            200,
        ]
        # Empty: received = 300 back from the sale, issue = erv 100.
        assert [empty[k] for k in ("opening", "received", "issue", "other", "closing")] == [
            0,
            300,
            100,
            0,
            200,
        ]
        # The next day opens with what this day closed with.
        nd = (D + dt.timedelta(days=1)).isoformat()
        nxt = (await http.get(f"/v1/reports/stock?start={nd}&end={nd}", headers=admin)).json()
        opening = {r["condition"]: r["opening"] for r in nxt if r["code"] == TYPE_CODE}
        assert opening == {"full": 200, "empty": 200}

        deliv = next(
            r
            for r in await _report(http, admin, "delivery")
            if r["delivery_id"] == str(users.delivery_id)
        )
        assert float(deliv["sales"]) == 300000  # 300 × 1000
        assert (deliv["full_cylinders"], deliv["empty_cylinders"]) == (300, 300)

        exp = next(r for r in await _report(http, admin, "expenses") if r["item_name"] == ITEM_NAME)
        assert float(exp["total"]) == 200 and exp["count"] == 1
        # One item's entries: the day, who entered it, how much.
        led = (
            await http.get(f"/v1/reports/expenses/{item_id}?start={DS}&end={DS}", headers=admin)
        ).json()
        assert led["item_name"] == ITEM_NAME and led["count"] == 1
        assert float(led["total"]) == 200
        (entry,) = led["rows"]
        assert entry["business_date"] == DS and float(entry["amount"]) == 200
        assert entry["method"] == "cash" and entry["entered_by"]
        missing = await http.get(
            f"/v1/reports/expenses/{uuid.uuid4()}?start={DS}&end={DS}", headers=admin
        )
        assert missing.status_code == 404

        # Deposits: a bank account with ₹5000 opening; a day earlier ₹700 came in from the box.
        bank_id = (await http.post("/v1/banks", headers=admin, json={"name": VENDOR_NAME})).json()[
            "id"
        ]
        acc = (
            await http.post(
                "/v1/bank-accounts",
                headers=admin,
                json={"bank_id": bank_id, "account_type": "current", "opening_balance": 5000},
            )
        ).json()["id"]
        prev = (D - dt.timedelta(days=1)).isoformat()

        async def move(day: str, amount: int, body: dict[str, Any]) -> None:
            r = await http.post(
                "/v1/transfers",
                headers=admin,
                json={"business_date": day, "amount": amount, "method": "transfer", **body},
            )
            assert r.status_code == 201, r.text

        await move(
            prev,
            700,
            {
                "source_kind": "cashier_box",
                "dest_kind": "bank_account",
                "dest_bank_account_id": acc,
            },
        )
        # In range: box → bank 2000, bank → vendor 500.
        await move(
            DS,
            2000,
            {
                "source_kind": "cashier_box",
                "dest_kind": "bank_account",
                "dest_bank_account_id": acc,
            },
        )
        await move(
            DS,
            500,
            {
                "source_kind": "bank_account",
                "source_bank_account_id": acc,
                "dest_kind": "vendor",
                "dest_vendor_id": vendor_id,
            },
        )

        places = await _report(http, admin, "deposits")
        vend = next(r for r in places if r["kind"] == "vendor" and r["ref_id"] == vendor_id)
        assert vend["name"] == VENDOR_NAME
        assert (float(vend["money_in"]), float(vend["money_out"]), vend["count"]) == (1500, 0, 2)
        bank = next(r for r in places if r["kind"] == "bank_account" and r["ref_id"] == acc)
        assert bank["name"] == f"{VENDOR_NAME} · current"
        assert (float(bank["money_in"]), float(bank["money_out"])) == (2000, 500)
        assert any(r["kind"] == "cashier_box" and r["ref_id"] is None for r in places)

        # The bank's statement: opening 5000 + 700 before, then each deposit with its balance.
        led = (
            await http.get(
                f"/v1/reports/deposits/bank_account/{acc}?start={DS}&end={DS}", headers=admin
            )
        ).json()
        assert float(led["opening"]) == 5700
        assert [(r["direction"], float(r["amount"]), float(r["balance"])) for r in led["rows"]] == [
            ("in", 2000, 7700),
            ("out", 500, 7200),
        ]
        assert led["rows"][0]["from_label"] == "Cashier box"
        assert led["rows"][1]["to_label"] == VENDOR_NAME
        assert (float(led["total_in"]), float(led["total_out"]), float(led["closing"])) == (
            2000,
            500,
            7200,
        )
        # Vendor statement: no balance, just what came in and from where.
        vled = (
            await http.get(
                f"/v1/reports/deposits/vendor/{vendor_id}?start={DS}&end={DS}", headers=admin
            )
        ).json()
        assert vled["opening"] is None and float(vled["total_in"]) == 1500
        assert {r["from_label"] for r in vled["rows"]} == {
            "Cashier box",
            f"{VENDOR_NAME} · current",
        }
        box = await http.get(
            f"/v1/reports/deposits/cashier_box/box?start={DS}&end={DS}", headers=admin
        )
        assert box.status_code == 200 and box.json()["name"] == "Cashier box"
        for bad in (f"vendor/{uuid.uuid4()}", "vendor/nope"):
            r = await http.get(f"/v1/reports/deposits/{bad}?start={DS}&end={DS}", headers=admin)
            assert r.status_code == 404
    finally:
        await _cleanup()


async def test_delivery_person_ledger(client: tuple[AsyncClient, SeededUsers]) -> None:
    """Per-delivery-boy statement: each line's own balance; nothing carried in from before."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    boy = str(users.delivery_id)
    before, after = (D - dt.timedelta(days=1)).isoformat(), (D + dt.timedelta(days=1)).isoformat()
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
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "invoice_no": f"IOC-{uuid.uuid4().hex[:10]}",
                "business_date": DS,
                "cylinders": [{"cylinder_type_id": type_id, "qty": 50}],
            },
        )
        # Owed 500 from before the range — must not show up.
        await http.post(
            "/v1/delivery-balances",
            headers=admin,
            json={"delivery_id": boy, "amount": 500, "entry_date": before, "kind": "charge"},
        )
        # 10 × 1000 = 10000 = cash 2500 + upi 2500 + online 1000 + balance 4000; 8 empties back.
        sale = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "invoice_no": "ZZ-rep-INV1",
                "delivery_id": boy,
                "business_date": DS,
                "lines": [{"cylinder_type_id": type_id, "qty": 10, "empty_qty": 8}],
                "denominations": [{"note_value": 500, "note_count": 5}],
                "upi_total": 2500,
                "online_total": 1000,
                "balance_total": 4000,
            },
        )
        assert sale.status_code == 201, sale.text
        await http.post(
            "/v1/delivery-balances",
            headers=admin,
            json={
                "delivery_id": boy,
                "amount": 3000,
                "entry_date": after,
                "kind": "repayment",
                "note": "paid at office",
            },
        )

        res = await http.get(f"/v1/reports/delivery/{boy}?start={DS}&end={after}", headers=admin)
        assert res.status_code == 200, res.text
        body = res.json()
        assert "opening_balance" not in body
        assert [r["kind"] for r in body["rows"]] == ["sale", "repayment"]
        s, rp = body["rows"]
        assert s["invoice_no"] == "ZZ-rep-INV1"
        assert (s["qty"], s["empty_qty"]) == (10, 8)
        assert [float(s[k]) for k in ("amount", "cash", "upi", "online", "balance")] == [
            10000,
            2500,
            2500,
            1000,
            4000,
        ]
        assert float(rp["repaid"]) == 3000 and rp["note"] == "paid at office"
        assert float(rp["balance"]) == 0
        assert float(body["total_amount"]) == 10000 and float(body["total_repaid"]) == 3000
        assert float(body["total_balance"]) == 1000  # 4000 unpaid − 3000 repaid

        # The overall delivery report counts empties actually returned.
        deliv = next(r for r in await _report(http, admin, "delivery") if r["delivery_id"] == boy)
        assert (deliv["full_cylinders"], deliv["empty_cylinders"]) == (10, 8)

        missing = await http.get(
            f"/v1/reports/delivery/{users.admin_id}?start={DS}&end={DS}", headers=admin
        )
        assert missing.status_code == 404
    finally:
        await _cleanup()
