"""Opening stock (Master Catalog): stock on hand at the start of a date."""

from __future__ import annotations

import datetime as dt

from app.core.config import settings
from app.db.models import Accessory, CylinderType, Inventory, StockLedger
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-open"
ACC_NAME = "ZZ open regulator"
DAY = dt.date(2093, 3, 10)
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
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        aids = (await db.scalars(select(Accessory.id).where(Accessory.name == ACC_NAME))).all()
        for aid in aids:
            await db.execute(delete(StockLedger).where(StockLedger.accessory_id == aid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.execute(delete(Accessory).where(Accessory.name == ACC_NAME))
        await db.commit()
    await engine.dispose()


async def test_opening_stock(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = await _token(http, TEST_ADMIN_PHONE)
    office = await _token(http, TEST_OFFICE_PHONE)
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "Open"}
            )
        ).json()["id"]
        acc = await http.post("/v1/accessories", headers=admin, json={"name": ACC_NAME})
        assert acc.status_code == 201, acc.text
        acc_id = acc.json()["id"]

        lines = [
            {"cylinder_type_id": type_id, "condition": "full", "qty": 50},
            {"cylinder_type_id": type_id, "condition": "empty", "qty": 20},
            {"accessory_id": acc_id, "qty": 5},
        ]
        # Only the owner sets it.
        r = await http.put("/v1/stock/opening", headers=office, json={"as_of": DS, "lines": lines})
        assert r.status_code == 403
        r = await http.put("/v1/stock/opening", headers=admin, json={"as_of": DS, "lines": lines})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["as_of"] == DS
        mine = {
            (x["condition"] or "acc"): x["qty"]
            for x in body["rows"]
            if x["cylinder_type_id"] == type_id or x["accessory_id"] == acc_id
        }
        assert mine == {"full": 50, "empty": 20, "acc": 5}
        got = (await http.get("/v1/stock/opening", headers=office)).json()
        assert got["as_of"] == DS

        # It is the stock at the start of that day.
        ov = (await http.get(f"/v1/stock/overview?date={DS}", headers=admin)).json()
        row = next(c for c in ov["cylinders"] if c["cylinder_type_id"] == type_id)
        assert (row["full_opening"], row["empty_opening"]) == (50, 20)
        inv = (await http.get("/v1/inventory", headers=admin)).json()
        assert next(i for i in inv if i["cylinder_type_id"] == type_id)["quantity"] == 50
        rep = (await http.get(f"/v1/reports/stock?start={DS}&end={DS}", headers=admin)).json()
        full = next(x for x in rep if x["cylinder_type_id"] == type_id and x["condition"] == "full")
        assert (full["opening"], full["other"], full["closing"]) == (50, 0, 50)

        # 15 empties go to the plant; the opening can't drop below what that needed.
        r = await http.post(
            "/v1/stock/erv",
            headers=admin,
            json={"business_date": DS, "lines": [{"cylinder_type_id": type_id, "qty": 15}]},
        )
        assert r.status_code == 201, r.text
        lower = [{**lines[1], "qty": 10}, lines[0], lines[2]]
        r = await http.put("/v1/stock/opening", headers=admin, json={"as_of": DS, "lines": lower})
        assert r.status_code == 409, r.text
        assert (await http.get("/v1/stock/opening", headers=admin)).json()["as_of"] == DS

        # Raising it is fine and moves the live full count.
        more = [{**lines[0], "qty": 60}, lines[1], lines[2]]
        r = await http.put("/v1/stock/opening", headers=admin, json={"as_of": DS, "lines": more})
        assert r.status_code == 200, r.text
        inv = (await http.get("/v1/inventory", headers=admin)).json()
        assert next(i for i in inv if i["cylinder_type_id"] == type_id)["quantity"] == 60
    finally:
        await _cleanup()
