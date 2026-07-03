"""Expense items catalog tests (Phase 1-D): CRUD + soft-delete + dropdown filter."""

from __future__ import annotations

from app.core.config import settings
from app.db.models import ExpenseItem
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

CREATED_NAME = "ZZ Test Petrol"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        await db.execute(delete(ExpenseItem).where(ExpenseItem.name == CREATED_NAME))
        await db.commit()
    await engine.dispose()


async def test_create_edit_deactivate_and_filter(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        created = await http.post(
            "/v1/expense-items", headers=admin, json={"name": CREATED_NAME, "category": "Fuel"}
        )
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]
        assert created.json()["category"] == "Fuel"

        active = await http.get("/v1/expense-items", headers=admin)
        assert any(r["name"] == CREATED_NAME for r in active.json())

        dup = await http.post("/v1/expense-items", headers=admin, json={"name": CREATED_NAME})
        assert dup.status_code == 409

        edited = await http.patch(
            f"/v1/expense-items/{item_id}", headers=admin, json={"category": "Vehicle"}
        )
        assert edited.status_code == 200
        assert edited.json()["category"] == "Vehicle"

        deactivated = await http.patch(
            f"/v1/expense-items/{item_id}", headers=admin, json={"is_active": False}
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False

        active_after = await http.get("/v1/expense-items", headers=admin)
        assert all(r["name"] != CREATED_NAME for r in active_after.json())

        all_rows = await http.get("/v1/expense-items?active=all", headers=admin)
        assert any(r["name"] == CREATED_NAME for r in all_rows.json())
    finally:
        await _cleanup()


async def test_office_can_list_but_not_create(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    assert (await http.get("/v1/expense-items", headers=office)).status_code == 200
    created = await http.post("/v1/expense-items", headers=office, json={"name": "ZZ x"})
    assert created.status_code == 403
