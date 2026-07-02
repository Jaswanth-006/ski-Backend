"""Minimal user read endpoints — the protected surface that proves the RBAC and
row-level guards (00-MAIN-PRD §2). Full user management (create/deactivate) is Phase 1-B.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_can_access_user, get_current_user, get_db, require_roles
from app.db.models import User
from app.schemas.auth import UserOut

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    _: User = Depends(require_roles("super_admin", "office_admin")),  # RBAC: delivery blocked
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    result = await db.scalars(select(User).order_by(User.created_at))
    return list(result)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    ensure_can_access_user(current_user, user_id)  # row-level: delivery → self only
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    return user
