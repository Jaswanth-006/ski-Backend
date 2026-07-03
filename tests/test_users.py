"""User management tests (Phase 1-B): create → login → deactivate, and RBAC."""

from __future__ import annotations

from app.core.config import settings
from app.db.models import RefreshToken, User
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import (
    TEST_ADMIN_PHONE,
    TEST_OFFICE_PHONE,
    TEST_PASSWORD,
    SeededUsers,
)

CREATED_PHONE = "7900000001"
CREATED_PASSWORD = "Driver@123"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup_created() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        ids = (await db.scalars(select(User.id).where(User.phone == CREATED_PHONE))).all()
        if ids:
            await db.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(list(ids))))
            await db.execute(delete(User).where(User.id.in_(list(ids))))
            await db.commit()
    await engine.dispose()


async def test_create_delivery_then_login_then_deactivate(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    await _cleanup_created()
    admin = await _token(http, TEST_ADMIN_PHONE)
    headers = {"Authorization": f"Bearer {admin}"}
    try:
        # Owner creates a delivery account.
        created = await http.post(
            "/v1/users",
            headers=headers,
            json={
                "name": "New Driver",
                "phone": CREATED_PHONE,
                "role": "delivery",
                "password": CREATED_PASSWORD,
            },
        )
        assert created.status_code == 201, created.text
        user_id = created.json()["id"]
        assert created.json()["role"] == "delivery"

        # The new user can log in (the Phase 1-B "done when").
        ok = await http.post(
            "/v1/auth/login", json={"phone": CREATED_PHONE, "password": CREATED_PASSWORD}
        )
        assert ok.status_code == 200

        # Duplicate phone is rejected.
        dup = await http.post(
            "/v1/users",
            headers=headers,
            json={
                "name": "Dup",
                "phone": CREATED_PHONE,
                "role": "delivery",
                "password": CREATED_PASSWORD,
            },
        )
        assert dup.status_code == 409

        # Deactivate → the user can no longer log in.
        patched = await http.patch(
            f"/v1/users/{user_id}", headers=headers, json={"is_active": False}
        )
        assert patched.status_code == 200
        assert patched.json()["is_active"] is False

        denied = await http.post(
            "/v1/auth/login", json={"phone": CREATED_PHONE, "password": CREATED_PASSWORD}
        )
        assert denied.status_code == 401
    finally:
        await _cleanup_created()


async def test_office_cannot_create_users(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    office = await _token(http, TEST_OFFICE_PHONE)
    res = await http.post(
        "/v1/users",
        headers={"Authorization": f"Bearer {office}"},
        json={
            "name": "Blocked",
            "phone": "7900000099",
            "role": "delivery",
            "password": CREATED_PASSWORD,
        },
    )
    assert res.status_code == 403
