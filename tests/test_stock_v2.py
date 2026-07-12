"""Stock v2 tests — accessories catalog, ac4 (received), erv (empty return), overview."""

from __future__ import annotations

import datetime as dt

from app.core.config import settings
from app.db.models import Accessory, CylinderType, Inventory, Price, StockLedger
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

TYPE_CODE = "ZZ-sv2"
ACC_NAME = "ZZ-sv2-regulator"
D1 = dt.date(2097, 3, 10)
D2 = dt.date(2097, 3, 11)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return str(res.json()["access_token"])


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        tids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TYPE_CODE))
        ).all()
        aids = (await db.scalars(select(Accessory.id).where(Accessory.name == ACC_NAME))).all()
        for tid in tids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(Price).where(Price.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        for aid in aids:
            await db.execute(delete(StockLedger).where(StockLedger.accessory_id == aid))
        await db.execute(delete(Accessory).where(Accessory.name == ACC_NAME))
        await db.execute(delete(CylinderType).where(CylinderType.code == TYPE_CODE))
        await db.commit()
    await engine.dispose()


def _cyl_row(overview: dict[str, object], code: str) -> dict[str, int]:
    return next(r for r in overview["cylinders"] if r["code"] == code)  # type: ignore[attr-defined]


def _acc_row(overview: dict[str, object], name: str) -> dict[str, int]:
    return next(r for r in overview["accessories"] if r["name"] == name)  # type: ignore[attr-defined]


async def test_accessory_catalog_and_ac4_erv_overview(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "SV2"}
            )
        ).json()["id"]

        # Accessory catalog: create + duplicate guard + list.
        acc = await http.post("/v1/accessories", headers=admin, json={"name": ACC_NAME})
        assert acc.status_code == 201
        acc_id = acc.json()["id"]
        assert (
            await http.post("/v1/accessories", headers=admin, json={"name": ACC_NAME})
        ).status_code == 409
        listed = (await http.get("/v1/accessories", headers=admin)).json()
        assert any(a["name"] == ACC_NAME for a in listed)

        # ac4 on D1: receive 100 full cylinders + 20 accessories.
        ac4 = await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "business_date": D1.isoformat(),
                "cylinders": [{"cylinder_type_id": type_id, "qty": 100}],
                "accessories": [{"accessory_id": acc_id, "qty": 20}],
            },
        )
        assert ac4.status_code == 201
        row = _cyl_row(ac4.json(), TYPE_CODE)
        assert row["full_opening"] == 0
        assert row["full_received"] == 100
        assert row["full_closing"] == 100
        accrow = _acc_row(ac4.json(), ACC_NAME)
        assert accrow["received"] == 20 and accrow["closing"] == 20

        # D2 carries D1's closing as opening.
        d2 = (await http.get(f"/v1/stock/overview?date={D2.isoformat()}", headers=admin)).json()
        assert _cyl_row(d2, TYPE_CODE)["full_opening"] == 100

        # erv on D2: send 30 empties back to the plant.
        erv = await http.post(
            "/v1/stock/erv",
            headers=admin,
            json={
                "business_date": D2.isoformat(),
                "lines": [{"cylinder_type_id": type_id, "qty": 30}],
            },
        )
        assert erv.status_code == 201
        erow = _cyl_row(erv.json(), TYPE_CODE)
        assert erow["empty_sent_to_plant"] == 30
        assert erow["empty_closing"] == -30  # no customer returns yet (phase B adds those)
    finally:
        await _cleanup()
