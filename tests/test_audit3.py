"""Audit 3: the per-boy extra is dated, stock never goes negative on any day, retried saves
are recorded once, and user changes can't lock the owner out or keep old sessions alive."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.core.config import settings
from app.db.models import (
    CylinderType,
    DeliveryOtherSales,
    Inventory,
    Price,
    RefreshToken,
    SaleLine,
    StockLedger,
    Transfer,
    User,
    Vendor,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-audit3"
VENDOR = "ZZ Audit3 Vendor"
D0 = dt.date(2092, 4, 1)
D1 = dt.date(2092, 4, 2)
D2 = dt.date(2092, 4, 3)
USER_PHONE = "7900000031"


async def _token(http: AsyncClient, phone: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": password})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _cleanup(delivery_id: uuid.UUID | None = None) -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Transfer).where(Transfer.business_date.in_([D0, D1, D2])))
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(SaleLine).where(SaleLine.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.execute(delete(Vendor).where(Vendor.name == VENDOR))
        if delivery_id is not None:
            await db.execute(
                delete(DeliveryOtherSales).where(DeliveryOtherSales.delivery_id == delivery_id)
            )
        ids = (await db.scalars(select(User.id).where(User.phone == USER_PHONE))).all()
        if ids:
            await db.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(list(ids))))
            await db.execute(delete(User).where(User.id.in_(list(ids))))
        await db.commit()
    await engine.dispose()


async def test_dated_extra_stock_by_date_and_repeat_safe_saves(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup(users.delivery_id)
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    tag = uuid.uuid4().hex[:8]
    boy = str(users.delivery_id)
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "A3"}
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
                "business_date": D0.isoformat(),
                "cylinders": [{"cylinder_type_id": type_id, "qty": 10}],
            },
        )
        # The boy's extra: ₹50 from D0, ₹80 from D2.
        for amount, day in ((50, D0), (80, D2)):
            r = await http.put(
                f"/v1/delivery-other-sales/{boy}",
                headers=admin,
                json={"amount_per_cylinder": amount, "effective_date": day.isoformat()},
            )
            assert r.status_code == 200, r.text
        listed = (
            await http.get(f"/v1/delivery-other-sales?on_date={D1.isoformat()}", headers=admin)
        ).json()
        assert (
            float(next(x for x in listed if x["delivery_id"] == boy)["amount_per_cylinder"]) == 50
        )

        def sale(day: dt.date, qty: int, total: int) -> dict[str, Any]:
            return {
                "invoice_no": f"A3-{day.day}-{tag}",
                "delivery_id": boy,
                "business_date": day.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": qty}],
                "upi_total": total,
            }

        async def post_sale(body: dict[str, Any]) -> int:
            r = await http.post(
                "/v1/sales", headers={**office, "Idempotency-Key": str(uuid.uuid4())}, json=body
            )
            return r.status_code

        # A sale on D1 is priced with D1's extra (₹50), not the later ₹80.
        assert await post_sale(sale(D1, 2, 2 * 1080)) == 422  # doesn't tally
        assert await post_sale(sale(D1, 2, 2 * 1050)) == 201
        assert await post_sale(sale(D2, 1, 1080)) == 201

        async def erv(day: dt.date, qty: int, key: str | None = None) -> int:
            headers = {**office, "Idempotency-Key": key} if key else office
            r = await http.post(
                "/v1/stock/erv",
                headers=headers,
                json={
                    "business_date": day.isoformat(),
                    "lines": [{"cylinder_type_id": type_id, "qty": qty}],
                },
            )
            return r.status_code

        # Empties came back on D1: none could go to the plant on D0.
        assert await erv(D0, 1) == 409
        assert await erv(D1, 2) == 201
        # D1 has no empties left (the D2 one came later), so another on D1 is refused.
        assert await erv(D1, 1) == 409
        # The same erv sent twice (a retry) is recorded once.
        key = str(uuid.uuid4())
        assert await erv(D2, 1, key) == 201
        assert await erv(D2, 1, key) == 201
        ov = (await http.get(f"/v1/stock/overview?date={D2.isoformat()}", headers=admin)).json()
        row = next(r for r in ov["cylinders"] if r["code"] == TYPE_CODE)
        assert row["empty_closing"] == 0

        # A deposit retried with the same key is recorded once.
        vendor = (await http.post("/v1/vendors", headers=admin, json={"name": VENDOR})).json()["id"]
        body = {
            "business_date": D2.isoformat(),
            "amount": 100,
            "source_kind": "cashier_box",
            "dest_kind": "vendor",
            "dest_vendor_id": vendor,
            "method": "cash",
        }
        key = str(uuid.uuid4())
        first = await http.post(
            "/v1/transfers", headers={**office, "Idempotency-Key": key}, json=body
        )
        again = await http.post(
            "/v1/transfers", headers={**office, "Idempotency-Key": key}, json=body
        )
        assert first.status_code == 201 and again.status_code == 201
        assert first.json()["id"] == again.json()["id"]
        # The same key can't be reused for a different kind of entry.
        clash = await http.post(
            "/v1/expenses",
            headers={**office, "Idempotency-Key": key},
            json={
                "business_date": D2.isoformat(),
                "item_id": str(uuid.uuid4()),
                "amount": 10,
                "method": "cash",
            },
        )
        assert clash.status_code == 409, clash.text
        deps = (
            await http.get(
                f"/v1/transfers?start={D2.isoformat()}&end={D2.isoformat()}", headers=admin
            )
        ).json()
        assert len([d for d in deps if d["dest_label"] == VENDOR]) == 1
    finally:
        await _cleanup(users.delivery_id)


async def test_owner_cant_lock_out_and_new_password_signs_out(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    try:
        me = (await http.get("/v1/me", headers=admin)).json()["id"]
        for change in ({"is_active": False}, {"role": "office_admin"}):
            r = await http.patch(f"/v1/users/{me}", headers=admin, json=change)
            assert r.status_code == 409, r.text

        created = await http.post(
            "/v1/users",
            headers=admin,
            json={
                "name": "A3 Office",
                "phone": USER_PHONE,
                "role": "office_admin",
                "password": "Office@123",
            },
        )
        assert created.status_code == 201, created.text
        login = await http.post(
            "/v1/auth/login", json={"phone": USER_PHONE, "password": "Office@123"}
        )
        refresh = login.json()["refresh_token"]
        r = await http.patch(
            f"/v1/users/{created.json()['id']}", headers=admin, json={"password": "Changed@123"}
        )
        assert r.status_code == 200, r.text
        # The session opened with the old password can't be renewed.
        r = await http.post("/v1/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 401
    finally:
        await _cleanup()
