"""ac4 with a cost: the purchase is taken from the money already deposited with the vendor."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.config import settings
from app.db.models import CylinderType, Inventory, StockLedger, Transfer, Vendor
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-pay"
VENDOR = "ZZ Pay Vendor"
DAY = dt.date(2095, 7, 8)
DS = DAY.isoformat()


async def _token(http: AsyncClient, phone: str) -> dict[str, str]:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(
            delete(Transfer).where(Transfer.business_date.in_([DAY, DAY + dt.timedelta(days=1)]))
        )
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.execute(delete(Vendor).where(Vendor.name == VENDOR))
        await db.commit()
    await engine.dispose()


async def test_ac4_cost_comes_out_of_the_vendor_balance(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    tag = uuid.uuid4().hex[:6]
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Pay"}
            )
        ).json()["id"]
        vendor = (
            await http.post(
                "/v1/vendors", headers=admin, json={"name": VENDOR, "opening_balance": 1000}
            )
        ).json()
        vid = vendor["id"]

        async def balance() -> dict[str, Any]:
            vendors = (await http.get("/v1/vendors?active=all", headers=admin)).json()
            return next(x for x in vendors if x["id"] == vid)

        # A week earlier: 5000 deposited with the vendor from the cashier box.
        r = await http.post(
            "/v1/transfers",
            headers=office,
            json={
                "business_date": DS,
                "amount": 5000,
                "source_kind": "cashier_box",
                "dest_kind": "vendor",
                "dest_vendor_id": vid,
                "method": "cash",
            },
        )
        assert r.status_code == 201, r.text
        box_before = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float((await balance())["balance"]) == 6000

        lines = [{"cylinder_type_id": type_id, "qty": 10}]

        async def ac4(invoice: str, purchase: dict[str, Any] | None) -> Any:
            body: dict[str, Any] = {"invoice_no": invoice, "business_date": DS, "cylinders": lines}
            if purchase is not None:
                body["purchase"] = purchase
            return await http.post("/v1/stock/ac4", headers=office, json=body)

        # An unknown vendor records nothing — not even the stock.
        r = await ac4(f"P-{tag}-x", {"amount": 5, "vendor_id": str(uuid.uuid4())})
        assert r.status_code == 400
        assert (await http.get(f"/v1/stock/entries?date={DS}", headers=admin)).json() == []

        r = await ac4(f"P-{tag}", {"amount": "4500.50", "vendor_id": vid})
        assert r.status_code == 201, r.text
        (entry,) = (await http.get(f"/v1/stock/entries?date={DS}", headers=admin)).json()
        assert float(entry["payment_amount"]) == 4500.5
        assert entry["payment_label"] == f"{VENDOR} → Purchase"
        assert entry["purchase_vendor_id"] == vid

        v = await balance()
        assert float(v["used"]) == 4500.5 and float(v["balance"]) == 1499.5
        # The cashier box is not touched — the money was already with the vendor.
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["deposited"]) == float(box_before["deposited"])

        # The purchase shows on the vendor's report as money out, with a running balance.
        rep = (
            await http.get(f"/v1/reports/deposits/vendor/{vid}?start={DS}&end={DS}", headers=admin)
        ).json()
        assert float(rep["opening"]) == 1000 and float(rep["closing"]) == 1499.5
        assert [(x["direction"], float(x["amount"])) for x in rep["rows"]] == [
            ("in", 5000),
            ("out", 4500.5),
        ]
        assert rep["rows"][1]["to_label"] == "Purchase (ac4)"
        summary = (
            await http.get(f"/v1/reports/deposits?start={DS}&end={DS}", headers=admin)
        ).json()
        row = next(x for x in summary if x["kind"] == "vendor" and x["ref_id"] == vid)
        assert float(row["money_in"]) == 5000 and float(row["money_out"]) == 4500.5

        # It is listed with the deposits but is changed through the purchase.
        deps = (await http.get(f"/v1/transfers?start={DS}&end={DS}", headers=admin)).json()
        cost = next(d for d in deps if d["dest_kind"] == "purchase")
        assert cost["stock_entry_id"] == entry["entry_id"]
        r = await http.post(
            f"/v1/transfers/{cost['id']}/delete", headers=office, json={"reason": "nope"}
        )
        assert r.status_code == 409 and "purchase" in r.json()["detail"]

        # The same invoice number may be recorded again; this one has no cost yet.
        assert (await ac4(f"P-{tag}", None)).status_code == 201
        entries = (await http.get(f"/v1/stock/entries?date={DS}", headers=admin)).json()
        second = next(e for e in entries if e["entry_id"] != entry["entry_id"])
        assert second["payment_amount"] is None

        # Editing the purchase: date, invoice and cost move together.
        nd = (DAY + dt.timedelta(days=1)).isoformat()
        line = {"cylinder_type_id": type_id, "condition": "full", "qty": 10}
        r = await http.put(
            f"/v1/stock/entries/{entry['entry_id']}",
            headers=office,
            json={
                "reason": "wrong date",
                "business_date": nd,
                "invoice_no": f"P-{tag}-B",
                "lines": [line],
                "purchase_amount": 3000,
            },
        )
        assert r.status_code == 200, r.text
        moved = (await http.get(f"/v1/transfers?start={nd}&end={nd}", headers=admin)).json()
        assert [(d["note"], float(d["amount"])) for d in moved] == [
            (f"ac4 invoice P-{tag}-B", 3000)
        ]
        assert float((await balance())["balance"]) == 3000

        # Adding a cost to the second entry needs the vendor.
        edit = {"reason": "add cost", "business_date": DS, "lines": [line], "purchase_amount": 100}
        r = await http.put(f"/v1/stock/entries/{second['entry_id']}", headers=office, json=edit)
        assert r.status_code == 400
        edit["purchase_vendor_id"] = vid
        r = await http.put(f"/v1/stock/entries/{second['entry_id']}", headers=office, json=edit)
        assert r.status_code == 200, r.text
        assert float((await balance())["balance"]) == 2900

        # A cost of 0 removes it; deleting the purchase removes its cost too.
        edit = {"reason": "no cost", "business_date": DS, "lines": [line], "purchase_amount": 0}
        r = await http.put(f"/v1/stock/entries/{second['entry_id']}", headers=office, json=edit)
        assert r.status_code == 200, r.text
        r = await http.post(
            f"/v1/stock/entries/{entry['entry_id']}/delete",
            headers=office,
            json={"reason": "wrong invoice"},
        )
        assert r.status_code == 204, r.text
        v = await balance()
        assert float(v["used"]) == 0 and float(v["balance"]) == 6000
    finally:
        await _cleanup()
