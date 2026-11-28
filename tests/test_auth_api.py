"""Integration tests for auth + RBAC + row-level guards (require a database)."""

from __future__ import annotations

import datetime as dt

from app.core import security
from app.core.config import settings
from app.db.models import RefreshToken
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_DELIVERY_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers


async def _login(client: AsyncClient, phone: str) -> dict[str, str]:
    res = await client.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    assert res.status_code == 200, res.text
    tokens: dict[str, str] = res.json()
    return tokens


async def test_login_success_and_me(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    tokens = await _login(http, TEST_OFFICE_PHONE)
    assert tokens["access_token"] and tokens["refresh_token"]

    me = await http.get("/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "office_admin"


async def test_login_wrong_password(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    res = await http.post("/v1/auth/login", json={"phone": TEST_OFFICE_PHONE, "password": "nope"})
    assert res.status_code == 401


async def test_protected_endpoint_requires_token(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    assert (await http.get("/v1/me")).status_code == 401  # no bearer credentials


async def test_rbac_delivery_cannot_list_users(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    tokens = await _login(http, TEST_DELIVERY_PHONE)
    res = await http.get("/v1/users", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 403  # wrong role


async def test_rbac_office_can_list_users(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    tokens = await _login(http, TEST_OFFICE_PHONE)
    res = await http.get("/v1/users", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


async def test_row_level_delivery_only_self(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, users = client
    tokens = await _login(http, TEST_DELIVERY_PHONE)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    other = await http.get(f"/v1/users/{users.office_id}", headers=headers)
    assert other.status_code == 403  # cross-user access blocked

    own = await http.get(f"/v1/users/{users.delivery_id}", headers=headers)
    assert own.status_code == 200


async def test_refresh_rotation_and_reuse_detection(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    tokens = await _login(http, TEST_OFFICE_PHONE)
    r1 = tokens["refresh_token"]

    # First rotation succeeds and returns a new refresh token.
    ok = await http.post("/v1/auth/refresh", json={"refresh_token": r1})
    assert ok.status_code == 200
    r2 = ok.json()["refresh_token"]
    assert r2 != r1

    # Seconds later the same browser renewing twice at once (two tabs / racing requests):
    # refused, but nobody is logged out — r2 still works.
    race = await http.post("/v1/auth/refresh", json={"refresh_token": r1})
    assert race.status_code == 401
    ok = await http.post("/v1/auth/refresh", json={"refresh_token": r2})
    assert ok.status_code == 200
    r3 = ok.json()["refresh_token"]

    # Long after the rotation, reusing a retired token is theft → the whole family is revoked.
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine)() as db:
        family = await db.scalar(
            select(RefreshToken.family_id).where(
                RefreshToken.token_hash == security.hash_refresh_token(r1)
            )
        )
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family)
            .values(created_at=dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=5))
        )
        await db.commit()
    await engine.dispose()
    reuse = await http.post("/v1/auth/refresh", json={"refresh_token": r1})
    assert reuse.status_code == 401

    # r3 belonged to the now-revoked family, so it no longer works either.
    after = await http.post("/v1/auth/refresh", json={"refresh_token": r3})
    assert after.status_code == 401
