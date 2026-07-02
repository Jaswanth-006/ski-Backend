"""Unit tests for security primitives (no DB required)."""

from __future__ import annotations

import uuid

import jwt
import pytest
from app.core import security
from app.core.config import settings


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
