"""Temporal pricing tests (Phase 1-E): effective-dated resolution + bulk set."""

from __future__ import annotations

import datetime as dt

from app.core.config import settings
from app.db.models import Price
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

# Far-future dates so tests never collide with real/seed data and clean up in one sweep.
CLEAN_FROM = dt.date(2099, 1, 1)


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _type_ids(http: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    res = await http.get("/v1/cylinder-types?active=all", headers=headers)
    return {row["code"]: row["id"] for row in res.json()}


async def _price_of(
    http: AsyncClient, headers: dict[str, str], date: str, code: str
) -> float | None:
    res = await http.get(f"/v1/prices?date={date}", headers=headers)
    for row in res.json():
        if row["code"] == code:
            return None if row["unit_price"] is None else float(row["unit_price"])
    return None


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        await db.execute(delete(Price).where(Price.effective_date >= CLEAN_FROM))
        await db.commit()
    await engine.dispose()


async def test_temporal_resolution(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        types = await _type_ids(http, admin)
        t14 = types["14.2kg"]

        # Two effective-dated prices for the same variety.
        r1 = await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": t14, "unit_price": 1000, "effective_date": "2099-01-01"},
        )
        assert r1.status_code == 204, r1.text
        await http.put(
            "/v1/prices",
            headers=admin,
            json={"cylinder_type_id": t14, "unit_price": 1100, "effective_date": "2099-02-01"},
        )

        # A date resolves to the latest price effective on/before it.
        assert await _price_of(http, admin, "2099-01-15", "14.2kg") == 1000
        assert await _price_of(http, admin, "2099-03-01", "14.2kg") == 1100
        # Before any price exists → null.
        assert await _price_of(http, admin, "2098-12-31", "14.2kg") is None
    finally:
        await _cleanup()


async def test_bulk_sets_all_varieties(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        types = await _type_ids(http, admin)
        res = await http.put(
            "/v1/prices/bulk",
            headers=admin,
            json={
                "effective_date": "2099-01-01",
                "prices": [
                    {"cylinder_type_id": types["5kg"], "unit_price": 500},
                    {"cylinder_type_id": types["19kg"], "unit_price": 2000},
                ],
            },
        )
        assert res.status_code == 204, res.text
        assert await _price_of(http, admin, "2099-01-01", "5kg") == 500
        assert await _price_of(http, admin, "2099-01-01", "19kg") == 2000
    finally:
        await _cleanup()


async def test_office_cannot_set_price(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    res = await http.put(
        "/v1/prices",
        headers=office,
        json={
            "cylinder_type_id": str(users.admin_id),  # any uuid; blocked before it matters
            "unit_price": 999,
            "effective_date": "2099-01-01",
        },
    )
    assert res.status_code == 403
