"""Security tests: primitives (no DB) + hardening (headers, rate limit, RBAC)."""

from __future__ import annotations

import uuid

import jwt
import pytest
from app.core import rate_limit, security
from app.core.config import settings
from httpx import AsyncClient

from tests.conftest import TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers


def test_password_hash_roundtrip() -> None:
    hashed = security.hash_password("s3cret!")
    assert hashed != "s3cret!"  # never stored in the clear
    assert security.verify_password(hashed, "s3cret!") is True
    assert security.verify_password(hashed, "wrong") is False


def test_access_token_roundtrip() -> None:
    uid = uuid.uuid4()
    token = security.create_access_token(uid, "super_admin")
    payload = security.decode_access_token(token)
    assert payload["sub"] == str(uid)
    assert payload["role"] == "super_admin"
    assert payload["type"] == "access"


def test_decode_rejects_bad_signature() -> None:
    token = security.create_access_token(uuid.uuid4(), "delivery")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(security.TokenError):
        security.decode_access_token(tampered)


def test_decode_rejects_non_access_token() -> None:
    # A token minted without type="access" must be refused by decode_access_token.
    other = jwt.encode(
        {"sub": "x", "type": "refresh"}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(other)


def test_refresh_token_hash_is_deterministic_and_opaque() -> None:
    raw = security.generate_refresh_token()
    assert security.hash_refresh_token(raw) == security.hash_refresh_token(raw)
    assert raw != security.hash_refresh_token(raw)
    assert security.generate_refresh_token() != security.generate_refresh_token()


# ---- Hardening (Phase 7-B) ----
async def test_security_headers_present(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    res = await http.get("/livez")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "max-age=" in res.headers["strict-transport-security"]


async def test_login_throttled_after_repeated_failures(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    phone = "9111111111"  # not a seeded user → every attempt fails
    await rate_limit.clear_login_failures(phone)
    try:
        for _ in range(settings.login_rate_limit_max):
            res = await http.post("/v1/auth/login", json={"phone": phone, "password": "nope"})
            assert res.status_code == 401
        # Next attempt is blocked before credentials are even checked.
        blocked = await http.post("/v1/auth/login", json={"phone": phone, "password": "nope"})
        assert blocked.status_code == 429
    finally:
        await rate_limit.clear_login_failures(phone)


async def test_office_admin_blocked_from_owner_endpoint(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    http, _ = client
    login = await http.post(
        "/v1/auth/login", json={"phone": TEST_OFFICE_PHONE, "password": TEST_PASSWORD}
    )
    office = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # Owner-only: creating a bank must be refused for office_admin.
    res = await http.post("/v1/banks", headers=office, json={"name": "ZZ Nope"})
    assert res.status_code == 403
    # Sanity: the owner can.
    admin_login = await http.post(
        "/v1/auth/login", json={"phone": TEST_ADMIN_PHONE, "password": TEST_PASSWORD}
    )
    assert admin_login.status_code == 200
