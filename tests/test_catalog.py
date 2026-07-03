"""Cylinder varieties catalog tests (Phase 1-C): CRUD + soft-delete + dropdown filter."""

from __future__ import annotations

from app.core.config import settings
from app.db.models import CylinderType
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers

CREATED_CODE = "ZZ-6kg"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        await db.execute(delete(CylinderType).where(CylinderType.code == CREATED_CODE))
        await db.commit()
    await engine.dispose()


async def test_list_defaults_to_active_only(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    office = await _token(http, TEST_OFFICE_PHONE)
    res = await http.get("/v1/cylinder-types", headers={"Authorization": f"Bearer {office}"})
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) >= 4  # the seeded Indane varieties
    assert all(r["is_active"] for r in rows)


async def test_create_edit_deactivate_and_dropdown_filter(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        # Create
        created = await http.post(
            "/v1/cylinder-types", headers=admin, json={"code": CREATED_CODE, "label": "6 kg Trial"}
        )
        assert created.status_code == 201, created.text
        type_id = created.json()["id"]

        # Appears in the active dropdown source
        active = await http.get("/v1/cylinder-types", headers=admin)
        assert any(r["code"] == CREATED_CODE for r in active.json())

        # Duplicate code rejected
        dup = await http.post(
            "/v1/cylinder-types", headers=admin, json={"code": CREATED_CODE, "label": "dup"}
        )
        assert dup.status_code == 409

        # Edit label
        edited = await http.patch(
            f"/v1/cylinder-types/{type_id}", headers=admin, json={"label": "6 kg Domestic"}
        )
        assert edited.status_code == 200
        assert edited.json()["label"] == "6 kg Domestic"

        # Soft-delete → vanishes from the active dropdown but stays in ?active=all
        deactivated = await http.patch(
            f"/v1/cylinder-types/{type_id}", headers=admin, json={"is_active": False}
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False

        active_after = await http.get("/v1/cylinder-types", headers=admin)
        assert all(r["code"] != CREATED_CODE for r in active_after.json())

        all_rows = await http.get("/v1/cylinder-types?active=all", headers=admin)
        assert any(r["code"] == CREATED_CODE for r in all_rows.json())
    finally:
        await _cleanup()


async def test_office_cannot_create_variety(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    office = {"Authorization": f"Bearer {await _token(http, TEST_OFFICE_PHONE)}"}
    res = await http.post("/v1/cylinder-types", headers=office, json={"code": "ZZ-x", "label": "x"})
    assert res.status_code == 403
