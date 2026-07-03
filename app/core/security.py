"""Security primitives: argon2id password hashing, access-token (JWT) issue/verify,
and opaque refresh-token generation/hashing.

Passwords use argon2id (slow, salted). Access tokens are short-lived JWTs. Refresh
tokens are high-entropy opaque strings stored only as SHA-256 hashes (fast lookup;
the raw value is never persisted). See 00-MAIN-PRD §8, 01-BACKEND-PRD §3.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.config import settings

_hasher = PasswordHasher()


# ---- Passwords ----
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except Argon2Error:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ---- Access tokens (JWT) ----
class TokenError(Exception):
    """Raised when an access token is missing, malformed, expired, or wrong type."""


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    now = dt.datetime.now(tz=dt.UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise TokenError("not an access token")
    return payload


# ---- Refresh tokens (opaque) ----
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def refresh_expiry() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=settings.refresh_token_ttl_days)
