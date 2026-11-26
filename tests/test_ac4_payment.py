"""ac4 with a payment: the vendor is paid from the cashier box / a bank in the same entry."""

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
        await db.execute(delete(Transfer).where(Transfer.business_date == DAY))
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


async def test_ac4_records_the_vendor_payment(client: tuple[AsyncClient, SeededUsers]) -> None:
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
        box_before = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        lines = [{"cylinder_type_id": type_id, "qty": 10}]

        async def ac4(invoice: str, payment: dict[str, Any] | None) -> Any:
            body: dict[str, Any] = {"invoice_no": invoice, "business_date": DS, "cylinders": lines}
            if payment is not None:
                body["payment"] = payment
            return await http.post("/v1/stock/ac4", headers=office, json=body)

        # Bad payments record nothing — not even the stock.
        r = await ac4(f"P-{tag}-x", {"amount": 5, "vendor_id": str(uuid.uuid4())})
        assert r.status_code == 400
        r = await ac4(
            f"P-{tag}-y",
            {"amount": 5, "vendor_id": vendor["id"], "source_kind": "bank_account"},
        )
        assert r.status_code == 422
        entries = (await http.get(f"/v1/stock/entries?date={DS}", headers=admin)).json()
        assert entries == []

        r = await ac4(f"P-{tag}", {"amount": "8500.50", "vendor_id": vendor["id"]})
        assert r.status_code == 201, r.text
        (entry,) = (await http.get(f"/v1/stock/entries?date={DS}", headers=admin)).json()
        assert float(entry["payment_amount"]) == 8500.5
        assert entry["payment_label"] == f"Cashier box → {VENDOR}"

        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["deposited"]) - float(box_before["deposited"]) == 8500.5
        vendors = (await http.get("/v1/vendors?active=all", headers=admin)).json()
        v = next(x for x in vendors if x["id"] == vendor["id"])
        assert float(v["paid"]) == 8500.5 and float(v["total_paid"]) == 9500.5
        deps = (await http.get(f"/v1/transfers?start={DS}&end={DS}", headers=admin)).json()
        assert [d["note"] for d in deps] == [f"ac4 invoice P-{tag}"]

        # Without a payment the purchase is just stock.
        assert (await ac4(f"P-{tag}-2", None)).status_code == 201

        # Deleting the purchase removes its payment.
        r = await http.post(
            f"/v1/stock/entries/{entry['entry_id']}/delete",
            headers=office,
            json={"reason": "wrong invoice"},
        )
        assert r.status_code == 204, r.text
        deps = (await http.get(f"/v1/transfers?start={DS}&end={DS}", headers=admin)).json()
        assert deps == []
        box = (await http.get(f"/v1/cashier-box/{DS}", headers=admin)).json()
        assert float(box["deposited"]) == float(box_before["deposited"])
    finally:
        await _cleanup()
