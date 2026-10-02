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


async def test_return_damaged_or_lost(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = (
            await http.post(
                "/v1/cylinder-types", headers=admin, json={"code": TYPE_CODE, "label": "SV2"}
            )
        ).json()["id"]
        acc_id = (
            await http.post("/v1/accessories", headers=admin, json={"name": ACC_NAME})
        ).json()["id"]
        await http.post(
            "/v1/stock/ac4",
            headers=admin,
            json={
                "business_date": D1.isoformat(),
                "cylinders": [{"cylinder_type_id": type_id, "qty": 50}],
                "accessories": [{"accessory_id": acc_id, "qty": 10}],
            },
        )

        # Return 3 damaged full, 2 lost empties and 1 damaged accessory.
        ret = await http.post(
            "/v1/stock/return",
            headers=admin,
            json={
                "business_date": D1.isoformat(),
                "lines": [
                    {"cylinder_type_id": type_id, "condition": "full", "qty": 3, "note": "damaged"},
                    {"cylinder_type_id": type_id, "condition": "empty", "qty": 2, "note": "lost"},
                    {"accessory_id": acc_id, "qty": 1, "note": "damaged"},
                ],
            },
        )
        assert ret.status_code == 201
        row = _cyl_row(ret.json(), TYPE_CODE)
        assert row["full_closing"] == 47
        assert row["empty_closing"] == -2
        assert _acc_row(ret.json(), ACC_NAME)["closing"] == 9

        # The live inventory that sales draw from moves too.
        inv = (await http.get("/v1/inventory", headers=admin)).json()
        assert next(i for i in inv if i["cylinder_type_id"] == type_id)["quantity"] == 47

        # Can't return more full cylinders than are in stock — nothing is written.
        too_many = await http.post(
            "/v1/stock/return",
            headers=admin,
            json={"lines": [{"cylinder_type_id": type_id, "condition": "full", "qty": 999}]},
        )
        assert too_many.status_code == 409

        # A cylinder line needs a condition; an accessory line must not have one.
        for bad in (
            {"cylinder_type_id": type_id, "qty": 1},
            {"accessory_id": acc_id, "condition": "full", "qty": 1},
            {"cylinder_type_id": type_id, "accessory_id": acc_id, "condition": "full", "qty": 1},
        ):
            res = await http.post("/v1/stock/return", headers=admin, json={"lines": [bad]})
            assert res.status_code == 422
    finally:
        await _cleanup()


async def test_accessory_update_and_delete(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        acc_id = (
            await http.post("/v1/accessories", headers=admin, json={"name": ACC_NAME})
        ).json()["id"]

        # Rename + deactivate.
        upd = await http.patch(
            f"/v1/accessories/{acc_id}",
            headers=admin,
            json={"name": ACC_NAME + "-x", "is_active": False},
        )
        assert upd.status_code == 200
        assert upd.json()["name"] == ACC_NAME + "-x"
        assert upd.json()["is_active"] is False

        # Delete an unused accessory.
        assert (await http.delete(f"/v1/accessories/{acc_id}", headers=admin)).status_code == 204
    finally:
        await _cleanup()
