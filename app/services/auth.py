"""Authentication service: verify credentials and manage the rotating refresh-token
family (00-MAIN-PRD §8.1).

Login issues an access JWT + an opaque refresh token (new family). Refresh rotates:
the presented token is revoked and a fresh one issued in the same family. Presenting an
already-revoked token is treated as theft — the **entire family** is revoked.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.models import RefreshToken, User


class AuthError(Exception):
    """Invalid credentials or invalid/expired/reused refresh token."""


async def authenticate_user(db: AsyncSession, phone: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.phone == phone))
    if user is None or not user.is_active:
        raise AuthError("invalid credentials")
    if not security.verify_password(user.password_hash, password):
        raise AuthError("invalid credentials")
    return user


async def _create_refresh_token(db: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID) -> str:
    raw = security.generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id,
            token_hash=security.hash_refresh_token(raw),
            expires_at=security.refresh_expiry(),
        )
    )
    return raw


async def issue_token_pair(db: AsyncSession, user: User) -> tuple[str, str]:
    """Fresh login: new family, new access + refresh tokens."""
    family_id = uuid.uuid4()
    raw_refresh = await _create_refresh_token(db, user.id, family_id)
    await db.commit()
    access = security.create_access_token(user.id, user.role)
    return access, raw_refresh


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> tuple[str, str]:
    """Exchange a valid refresh token for a new pair; detect + punish reuse."""
    token_hash = security.hash_refresh_token(raw_token)
    row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        raise AuthError("invalid refresh token")

    # Reuse of an already-revoked token → assume compromise, revoke the whole family.
    if row.revoked:
        await _revoke_family(db, row.family_id)
        await db.commit()
        raise AuthError("refresh token reuse detected")

    if row.expires_at <= dt.datetime.now(tz=dt.UTC):
        raise AuthError("refresh token expired")

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("user inactive")

    row.revoked = True  # rotate: retire the presented token
    raw_refresh = await _create_refresh_token(db, user.id, row.family_id)
    await db.commit()
    access = security.create_access_token(user.id, user.role)
    return access, raw_refresh


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )


async def logout(db: AsyncSession, raw_token: str) -> None:
    """Revoke the family the presented refresh token belongs to (idempotent)."""
    token_hash = security.hash_refresh_token(raw_token)
    row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is not None:
        await _revoke_family(db, row.family_id)
        await db.commit()
