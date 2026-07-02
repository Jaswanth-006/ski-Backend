"""Shared FastAPI dependencies: DB session, current user, and authorization guards.

Authorization is enforced in two layers (00-MAIN-PRD §2):
  - RBAC (`require_roles`) — gateway-level role check.
  - Row-level (`ensure_can_access_user`) — a `delivery` user resolves only to its own rows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_access_token
from app.db.models import User
from app.db.session import SessionLocal

_bearer = HTTPBearer(auto_error=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid subject") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="user not found or inactive")
    return user


def require_roles(*roles: str) -> Callable[[User], Awaitable[User]]:
    """Gateway RBAC guard: allow only the listed roles."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return user

    return dependency


def ensure_can_access_user(current_user: User, target_user_id: uuid.UUID) -> None:
    """Row-level guard: a delivery user may only access its own rows."""
    if current_user.role == "delivery" and current_user.id != target_user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="cannot access another user's data")
