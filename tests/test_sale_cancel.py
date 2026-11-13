"""Cancel and edit a posted sale: everything it did is reversed; closed days are owner-only."""

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

TYPE_CODE = "ZZ-cancel"
DAY = dt.date(2096, 2, 3)
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


def _sale(boy: str, type_id: str, invoice: str, qty: int, cash_500s: int, **extra: Any) -> Any:
    """qty × ₹1000, paid with `cash_500s` ₹500 notes; the rest via `extra` (upi/balance)."""
    return {
        "invoice_no": invoice,
        "delivery_id": boy,
        "business_date": DS,
        "lines": [{"cylinder_type_id": type_id, "qty": qty, **extra.pop("line", {})}],
        "denominations": [{"note_value": 500, "note_count": cash_500s}] if cash_500s else [],
        **extra,
    }


async def _post(http: AsyncClient, h: dict[str, str], body: Any) -> Any:
    res = await http.post(
        "/v1/sales", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json=body
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _stock(http: AsyncClient, h: dict[str, str], type_id: str) -> tuple[int, int, int]:
    """(inventory, full closing, empty closing) for the test cylinder on DAY."""
    inv = next(
        r["quantity"]
        for r in (await http.get("/v1/inventory", headers=h)).json()
        if r["cylinder_type_id"] == type_id
    )
    ov = (await http.get(f"/v1/stock/overview?date={DS}", headers=h)).json()
    row = next(r for r in ov["cylinders"] if r["cylinder_type_id"] == type_id)
    return inv, row["full_closing"], row["empty_closing"]


async def _boy_row(http: AsyncClient, h: dict[str, str], boy: str) -> Any:
    sheet = (await http.get(f"/v1/day-sheet/{DS}", headers=h)).json()
    return next(r for r in sheet["rows"] if r["delivery_id"] == boy)


async def _owed(http: AsyncClient, h: dict[str, str], boy: str) -> float:
    summary = (await http.get("/v1/delivery-balances/summary", headers=h)).json()
    return float(next(r for r in summary if r["delivery_id"] == boy)["balance"])


async def test_cancel_and_edit_reverse_everything(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    boy = str(users.delivery_id)
    tag = uuid.uuid4().hex[:8]
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Cancel"}
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
            json={"business_date": DS, "cylinders": [{"cylinder_type_id": type_id, "qty": 50}]},
        )

        # 10 × 1000 = 10000 = cash 5000 + upi 3000 + balance 2000; 8 empties back.
        inv_a = f"A-{tag}"
        sale = await _post(
            http,
            office,
            _sale(
                boy,
                type_id,
                inv_a,
                10,
                10,
                upi_total=3000,
                balance_total=2000,
                line={"empty_qty": 8},
            ),
        )
        assert await _stock(http, admin, type_id) == (40, 40, 8)
        assert (await _boy_row(http, admin, boy))["cylinders"] == 10
        assert await _owed(http, admin, boy) == 2000

        # Reason is required.
        short = await http.post(
            f"/v1/sales/{sale['id']}/cancel", headers=office, json={"reason": " "}
        )
        assert short.status_code == 422

        cancelled = await http.post(
            f"/v1/sales/{sale['id']}/cancel", headers=office, json={"reason": "wrong boy"}
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["cancel_reason"] == "wrong boy"
        assert cancelled.json()["denominations"] == [{"note_value": 500, "note_count": 10}]

        # Stock, day sheet and balance are back as if the sale never happened.
        assert await _stock(http, admin, type_id) == (50, 50, 0)
        row = await _boy_row(http, admin, boy)
        assert row["cylinders"] == 0 and float(row["cash"]) == 0 and float(row["balance"]) == 0
        assert await _owed(http, admin, boy) == 0

        # Cancelling twice is refused; an unknown sale is 404.
        again = await http.post(
            f"/v1/sales/{sale['id']}/cancel", headers=office, json={"reason": "again"}
        )
        assert again.status_code == 409
        missing = await http.post(
            f"/v1/sales/{uuid.uuid4()}/cancel", headers=office, json={"reason": "nope"}
        )
        assert missing.status_code == 404

        # The cancelled invoice number can be used again.
        b = await _post(http, office, _sale(boy, type_id, inv_a, 5, 10))
        assert (await _boy_row(http, admin, boy))["cylinders"] == 5

        # Edit: 5 → 4 cylinders, same invoice number, in one step.
        edited = await http.post(
            f"/v1/sales/{b['id']}/edit",
            headers={**office, "Idempotency-Key": str(uuid.uuid4())},
            json={"reason": "one cylinder short", "sale": _sale(boy, type_id, inv_a, 4, 8)},
        )
        assert edited.status_code == 201, edited.text
        assert edited.json()["id"] != b["id"] and edited.json()["invoice_no"] == inv_a
        old = (await http.get(f"/v1/sales/{b['id']}", headers=admin)).json()
        assert old["status"] == "cancelled"
        assert await _stock(http, admin, type_id) == (46, 46, 4)
        assert (await _boy_row(http, admin, boy))["cylinders"] == 4

        # A failing edit (payment doesn't match) changes nothing.
        bad = await http.post(
            f"/v1/sales/{edited.json()['id']}/edit",
            headers={**office, "Idempotency-Key": str(uuid.uuid4())},
            json={"reason": "typo", "sale": _sale(boy, type_id, inv_a, 4, 1)},
        )
        assert bad.status_code == 422
        still = (await http.get(f"/v1/sales/{edited.json()['id']}", headers=admin)).json()
        assert still["status"] == "approved"
        assert await _stock(http, admin, type_id) == (46, 46, 4)

        # Closed day: office is blocked, the owner can still fix it.
        assert (await http.post(f"/v1/day-sheet/{DS}/close", headers=admin)).status_code == 200
        blocked = await http.post(
            f"/v1/sales/{edited.json()['id']}/cancel", headers=office, json={"reason": "late fix"}
        )
        assert blocked.status_code == 409
        assert "only the owner" in blocked.json()["detail"]
        owner = await http.post(
            f"/v1/sales/{edited.json()['id']}/cancel", headers=admin, json={"reason": "late fix"}
        )
        assert owner.status_code == 200
        assert await _stock(http, admin, type_id) == (50, 50, 0)
    finally:
        await _cleanup()
