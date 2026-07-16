"""Sales, reconciliation, Move-to-Day-Sheet transaction, and audit tests (Phase 3)."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import CylinderType, Inventory, Price, SaleLine, StockLedger
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TEST_CODE = "ZZ-sale"
TODAY = dt.date.today().isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TEST_CODE))
        ).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(SaleLine).where(SaleLine.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TEST_CODE))
        await db.commit()
    await engine.dispose()


async def _setup(http: AsyncClient, admin: dict[str, str], qty: int, price: int = 1000) -> str:
    """Create a priced, stocked test variety. Returns its id."""
    created = await http.post(
        "/v1/cylinder-types", headers=admin, json={"code": TEST_CODE, "label": "Sale Test"}
    )
    type_id: str = created.json()["id"]
    await http.put(
        "/v1/prices",
        headers=admin,
        json={"cylinder_type_id": type_id, "unit_price": price, "effective_date": TODAY},
    )
    await http.post(
        "/v1/stock/intake",
        headers=admin,
        json={"lines": [{"cylinder_type_id": type_id, "qty": qty}]},
    )
    return type_id


async def _inventory_qty(http: AsyncClient, headers: dict[str, str], type_id: str) -> int:
    res = await http.get("/v1/inventory", headers=headers)
    for r in res.json():
        if r["cylinder_type_id"] == type_id:
            q = r["quantity"]
            assert isinstance(q, int)
            return q
    raise KeyError(type_id)


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def test_sale_success_and_reconciled(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50, price=1000)
        res = await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 2}],
                "denominations": [{"note_value": 500, "note_count": 3}],  # 1500 cash
                "upi_total": 500,  # revenue 2000 == 1500 + 500
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "approved"
        assert float(body["revenue_total"]) == 2000
        assert float(body["cash_total"]) == 1500
        assert float(body["upi_total"]) == 500
        # Inventory drew down 50 → 48
        assert await _inventory_qty(http, admin, type_id) == 48
    finally:
        await _cleanup()


async def test_idempotent_resubmit_creates_one_sale(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50)
        payload = {
            "delivery_id": str(users.delivery_id),
            "business_date": TODAY,
            "lines": [{"cylinder_type_id": type_id, "qty": 2}],
            "denominations": [{"note_value": 1000, "note_count": 2}],  # 2000
            "upi_total": 0,
        }
        key = _key()
        first = await http.post("/v1/sales", headers={**admin, **key}, json=payload)
        second = await http.post("/v1/sales", headers={**admin, **key}, json=payload)
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["id"] == second.json()["id"]  # same sale
        assert await _inventory_qty(http, admin, type_id) == 48  # deducted once, not twice
    finally:
        await _cleanup()


async def test_reconciliation_mismatch_blocks_office(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50)
        res = await http.post(
            "/v1/sales",
            headers={**office, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 2}],  # revenue 2000
                "denominations": [{"note_value": 500, "note_count": 3}],  # 1500
                "upi_total": 400,  # collected 1900 != 2000 → mismatch
            },
        )
        assert res.status_code == 422
        assert "flags" in res.json()["detail"]
        # Rolled back: inventory untouched
        assert await _inventory_qty(http, admin, type_id) == 50
    finally:
        await _cleanup()


async def test_insufficient_stock_rolls_back(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=1)  # only 1 in stock
        res = await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 5}],  # more than stock
                "denominations": [{"note_value": 1000, "note_count": 5}],
                "upi_total": 0,
            },
        )
        assert res.status_code == 409
        # Zero side effects: stock unchanged
        assert await _inventory_qty(http, admin, type_id) == 1
    finally:
        await _cleanup()


async def test_audit_records_price_and_sale(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50)  # setup already sets a price → audit
        await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "denominations": [{"note_value": 1000, "note_count": 1}],
                "upi_total": 0,
            },
        )
        price_audit = await http.get("/v1/audit?entity=price", headers=admin)
        sale_audit = await http.get("/v1/audit?entity=sale", headers=admin)
        assert price_audit.status_code == 200 and len(price_audit.json()) >= 1
        assert len(sale_audit.json()) >= 1
        assert sale_audit.json()[0]["action"] == "sale.post"
    finally:
        await _cleanup()


async def test_sale_with_online_payment_and_empty_stock(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    """Online is settled by the company, not the boy; a sale returns empties into stock."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50, price=100)
        # 10 cyl × 100 = 1000 = cash 250 (5×₹50) + upi 250 + online 500.
        res = await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 10}],
                "denominations": [{"note_value": 50, "note_count": 5}],
                "upi_total": 250,
                "online_total": 500,
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert float(body["online_total"]) == 500
        assert float(body["settled_total"]) == 500  # cash 250 + upi 250 (online excluded)
        assert float(body["revenue_total"]) == 1000

        # Stock: 10 full went out, 10 empties came back.
        ov = (await http.get(f"/v1/stock/overview?date={TODAY}", headers=admin)).json()
        row = next(r for r in ov["cylinders"] if r["cylinder_type_id"] == type_id)
        assert row["full_sold"] == 10
        assert row["empty_returned_by_customers"] == 10
    finally:
        await _cleanup()


async def test_sale_online_mismatch_blocks_office(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    """Office cannot post when cash + upi + online != revenue."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50, price=100)
        res = await http.post(
            "/v1/sales",
            headers={**office, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 10}],  # revenue 1000
                "denominations": [{"note_value": 100, "note_count": 3}],  # cash 300
                "upi_total": 200,
                "online_total": 100,  # 300 + 200 + 100 = 600 ≠ 1000
            },
        )
        assert res.status_code == 422
    finally:
        await _cleanup()


async def test_other_sales_per_boy_applies_to_line_total(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    """A boy's extra ₹/cylinder rides on top of the fixed price and must be settled."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _setup(http, admin, qty=50, price=100)
        # Set boy's extra to ₹20/cyl.
        put = await http.put(
            f"/v1/delivery-other-sales/{users.delivery_id}",
            headers=admin,
            json={"amount_per_cylinder": 20},
        )
        assert put.status_code == 200
        assert float(put.json()["amount_per_cylinder"]) == 20
        # It shows in the list.
        listed = (await http.get("/v1/delivery-other-sales", headers=admin)).json()
        assert any(
            r["delivery_id"] == str(users.delivery_id) and float(r["amount_per_cylinder"]) == 20
            for r in listed
        )

        # 10 cyl × (100 + 20) = 1200 → must collect 1200.
        res = await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": str(users.delivery_id),
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 10}],
                "denominations": [{"note_value": 500, "note_count": 2}],  # cash 1000
                "upi_total": 200,  # 1000 + 200 = 1200
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert float(body["revenue_total"]) == 1200
        line = body["lines"][0]
        assert float(line["unit_price"]) == 100
        assert float(line["other_sales_per_unit"]) == 20
        assert float(line["line_total"]) == 1200
    finally:
        await _cleanup()


async def test_sale_balance_pushed_to_delivery_ledger(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    """Uncollected balance reconciles the sale and is charged to the boy's ledger."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    boy = str(users.delivery_id)
    try:
        type_id = await _setup(http, admin, qty=50, price=100)
        # 10 × 100 = 1000; boy hands 500 cash, keeps 500 → balance 500.
        res = await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": boy,
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 10}],
                "denominations": [{"note_value": 500, "note_count": 1}],
                "upi_total": 0,
                "online_total": 0,
                "balance_total": 500,
            },
        )
        assert res.status_code == 201, res.text
        assert float(res.json()["balance_total"]) == 500
        assert float(res.json()["settled_total"]) == 500  # only the cash handed

        summary = (await http.get("/v1/delivery-balances/summary", headers=admin)).json()
        row = next(r for r in summary if r["delivery_id"] == boy)
        assert float(row["balance"]) >= 500  # the sale created a charge

        sheet = (await http.get(f"/v1/day-sheet/{TODAY}", headers=admin)).json()
        drow = next(r for r in sheet["rows"] if r["delivery_id"] == boy)
        assert float(drow["balance"]) == 500
    finally:
        await _cleanup()
        # Clean the balance charge created above.
        from app.db.models import DeliveryBalance
        from sqlalchemy import delete as _delete
        from sqlalchemy.ext.asyncio import async_sessionmaker as _sm
        from sqlalchemy.ext.asyncio import create_async_engine as _ce

        eng = _ce(settings.database_url)
        async with _sm(eng, expire_on_commit=False)() as db:
            await db.execute(_delete(DeliveryBalance).where(DeliveryBalance.delivery_id == boy))
            await db.commit()
        await eng.dispose()


async def test_sale_empties_differ_from_sold_and_show_on_day_sheet(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    """Empties returned can differ from cylinders sold and appear on the day sheet."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    boy = str(users.delivery_id)
    try:
        type_id = await _setup(http, admin, qty=50, price=100)
        # Sold 10, but only 8 empties came back.
        res = await http.post(
            "/v1/sales",
            headers={**admin, **_key()},
            json={
                "delivery_id": boy,
                "business_date": TODAY,
                "lines": [{"cylinder_type_id": type_id, "qty": 10, "empty_qty": 8}],
                "denominations": [{"note_value": 1000, "note_count": 1}],
                "upi_total": 0,
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["lines"][0]["empty_qty"] == 8

        sheet = (await http.get(f"/v1/day-sheet/{TODAY}", headers=admin)).json()
        row = next(r for r in sheet["rows"] if r["delivery_id"] == boy)
        assert row["cylinders"] == 10
        assert row["empties"] == 8

        # Empty stock rose by 8 (not 10) for the type.
        ov = (await http.get(f"/v1/stock/overview?date={TODAY}", headers=admin)).json()
        crow = next(r for r in ov["cylinders"] if r["cylinder_type_id"] == type_id)
        assert crow["empty_returned_by_customers"] == 8
    finally:
        await _cleanup()


async def test_delete_cylinder_type(client: tuple[AsyncClient, SeededUsers]) -> None:
    """An unused variety deletes; one used by a price is blocked (409)."""
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        # Unused → deletes.
        t1 = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TEST_CODE, "label": "Del"}
            )
        ).json()["id"]
        assert (await http.delete(f"/v1/cylinder-types/{t1}", headers=admin)).status_code == 204

        # Priced → blocked.
        t2 = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TEST_CODE, "label": "Del2"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": t2, "unit_price": 100, "effective_date": TODAY},
        )
        assert (await http.delete(f"/v1/cylinder-types/{t2}", headers=admin)).status_code == 409
    finally:
        await _cleanup()
