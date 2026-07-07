"""Stock intake + inventory tests (Phase 2-A)."""

from __future__ import annotations

from app.core.config import settings
from app.db.models import CylinderType, Inventory, StockLedger
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

TEST_CODE = "ZZ-stock"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _make_type(http: AsyncClient, headers: dict[str, str]) -> str:
    res = await http.post(
        "/v1/cylinder-types", headers=headers, json={"code": TEST_CODE, "label": "Stock Test"}
    )
    type_id: str = res.json()["id"]
    return type_id


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        ids = (
            await db.scalars(select(CylinderType.id).where(CylinderType.code == TEST_CODE))
        ).all()
        for tid in ids:
            await db.execute(delete(StockLedger).where(StockLedger.cylinder_type_id == tid))
            await db.execute(delete(Inventory).where(Inventory.cylinder_type_id == tid))
        await db.execute(delete(CylinderType).where(CylinderType.code == TEST_CODE))
        await db.commit()
    await engine.dispose()


def _qty(rows: list[dict[str, object]], type_id: str) -> int:
    for row in rows:
        if row["cylinder_type_id"] == type_id:
            qty = row["quantity"]
            assert isinstance(qty, int)
            return qty
    raise KeyError(type_id)


async def test_intake_increases_inventory_and_appends_ledger(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        type_id = await _make_type(http, admin)

        # First intake: 15
        res = await http.post(
            "/v1/stock/intake",
            headers=admin,
            json={"lines": [{"cylinder_type_id": type_id, "qty": 15}]},
        )
        assert res.status_code == 200, res.text
        assert _qty(res.json(), type_id) == 15

        # Second intake: +5 → 20
        res2 = await http.post(
            "/v1/stock/intake",
            headers=admin,
            json={"lines": [{"cylinder_type_id": type_id, "qty": 5}]},
        )
        assert _qty(res2.json(), type_id) == 20

        # Live inventory view agrees
        inv = await http.get("/v1/inventory", headers=admin)
        assert _qty(inv.json(), type_id) == 20

        # Two immutable ledger rows were appended (one per intake)
        engine = create_async_engine(settings.database_url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(StockLedger)
                .where(StockLedger.cylinder_type_id == type_id, StockLedger.reason == "intake")
            )
            assert count == 2
        await engine.dispose()
    finally:
        await _cleanup()


async def test_office_can_record_intake(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    try:
        type_id = await _make_type(http, admin)
        res = await http.post(
            "/v1/stock/intake",
            headers=office,
            json={"lines": [{"cylinder_type_id": type_id, "qty": 3}]},
        )
        assert res.status_code == 200
        assert _qty(res.json(), type_id) == 3
    finally:
        await _cleanup()
