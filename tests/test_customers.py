"""Customer catalog + customer sales tests (Phase I)."""

from __future__ import annotations

import datetime as dt
import uuid

from app.core.config import settings
from app.db.models import (
    CashDenomination,
    CashLedger,
    Customer,
    CustomerBalance,
    CylinderType,
    Inventory,
    Price,
    Sale,
    SaleLine,
    StockLedger,
)
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-cust"
CUSTOMER = "ZZ-cust-ABC Foods"
DAY = dt.date(2094, 8, 3)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return str(res.json()["access_token"])


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        cids = (await db.scalars(select(Customer.id).where(Customer.name == CUSTOMER))).all()
        for cid in cids:
            await db.execute(delete(CustomerBalance).where(CustomerBalance.customer_id == cid))
            sids = (await db.scalars(select(Sale.id).where(Sale.customer_id == cid))).all()
            for sid in sids:
                await db.execute(delete(CashDenomination).where(CashDenomination.sale_id == sid))
                await db.execute(delete(CashLedger).where(CashLedger.sale_id == sid))
                await db.execute(delete(SaleLine).where(SaleLine.sale_id == sid))
                await db.execute(delete(StockLedger).where(StockLedger.ref_id == sid))
                await db.execute(delete(Sale).where(Sale.id == sid))
        await db.execute(delete(Customer).where(Customer.name == CUSTOMER))
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


async def test_customer_sale_shows_on_day_sheet(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        cust = await http.post("/v1/customers", headers=admin, json={"name": CUSTOMER})
        assert cust.status_code == 201
        customer_id = cust.json()["id"]
        assert (
            await http.post("/v1/customers", headers=admin, json={"name": CUSTOMER})
        ).status_code == 409

        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "CU"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 100, "effective_date": "2000-01-01"},
        )
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "business_date": DAY.isoformat(),
                "cylinders": [{"cylinder_type_id": type_id, "qty": 100}],
            },
        )
        # Direct customer sale — no delivery boy. 40 × 100 = 4000, all UPI.
        res = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "invoice_no": f"T-{uuid.uuid4()}",
                "customer_id": customer_id,
                "business_date": DAY.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 40}],
                "upi_total": 4000,
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["party_kind"] == "customer"
        assert res.json()["party_name"] == CUSTOMER

        # A sale must name exactly one party.
        bad = await http.post(
            "/v1/sales",
            headers={**admin, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "invoice_no": f"T-{uuid.uuid4()}",
                "business_date": DAY.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 1}],
                "upi_total": 100,
            },
        )
        assert bad.status_code == 422  # neither party given

        sheet = (await http.get(f"/v1/day-sheet/{DAY.isoformat()}", headers=admin)).json()
        crow = next(r for r in sheet["rows"] if r["delivery_id"] == customer_id)
        assert crow["party_kind"] == "customer"
        assert crow["cylinders"] == 40
        assert float(crow["upi"]) == 4000
    finally:
        await _cleanup()


async def test_invoice_number_and_customer_balance(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    invoice = f"INV-{uuid.uuid4()}"
    try:
        customer_id = (
            await http.post("/v1/customers", headers=admin, json={"name": CUSTOMER})
        ).json()["id"]
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "CU"}
            )
        ).json()["id"]
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": type_id, "unit_price": 100, "effective_date": "2000-01-01"},
        )
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "business_date": DAY.isoformat(),
                "cylinders": [{"cylinder_type_id": type_id, "qty": 100}],
            },
        )

        def sale(inv: str | None) -> dict[str, object]:
            body: dict[str, object] = {
                "customer_id": customer_id,
                "business_date": DAY.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 10}],
                "upi_total": 600,
                "balance_total": 400,  # 10 × 100 = 1000; 400 left unpaid
            }
            if inv is not None:
                body["invoice_no"] = inv
            return body

        def key() -> dict[str, str]:
            return {**admin, "Idempotency-Key": str(uuid.uuid4())}

        # Invoice number is required (and can't be blank).
        assert (await http.post("/v1/sales", headers=key(), json=sale(None))).status_code == 422
        assert (await http.post("/v1/sales", headers=key(), json=sale("  "))).status_code == 422

        res = await http.post("/v1/sales", headers=key(), json=sale(f"  {invoice} "))
        assert res.status_code == 201, res.text
        assert res.json()["invoice_no"] == invoice  # trimmed
        assert float(res.json()["balance_total"]) == 400

        # The same invoice number can't be used again.
        dup = await http.post("/v1/sales", headers=key(), json=sale(invoice))
        assert dup.status_code == 409
        assert invoice in dup.json()["detail"]

        # The unpaid part is charged to the customer's balance.
        summary = (await http.get("/v1/customer-balances/summary", headers=admin)).json()
        row = next(r for r in summary if r["customer_id"] == customer_id)
        assert float(row["charged"]) == 400 and float(row["balance"]) == 400

        # They pay back 150.
        rep = await http.post(
            "/v1/customer-balances",
            headers=admin,
            json={
                "customer_id": customer_id,
                "amount": 150,
                "entry_date": (DAY + dt.timedelta(days=2)).isoformat(),
                "kind": "repayment",
            },
        )
        assert rep.status_code == 201
        summary = (await http.get("/v1/customer-balances/summary", headers=admin)).json()
        row = next(r for r in summary if r["customer_id"] == customer_id)
        assert float(row["repaid"]) == 150 and float(row["balance"]) == 250

        entries = (
            await http.get(f"/v1/customer-balances?customer_id={customer_id}", headers=admin)
        ).json()
        assert {e["kind"] for e in entries} == {"charge", "repayment"}
        assert invoice in next(e for e in entries if e["kind"] == "charge")["note"]

        # The day sheet shows the customer's balance for that day.
        sheet = (await http.get(f"/v1/day-sheet/{DAY.isoformat()}", headers=admin)).json()
        crow = next(r for r in sheet["rows"] if r["delivery_id"] == customer_id)
        assert float(crow["balance"]) == 400
    finally:
        await _cleanup()
