"""User management (Phase 1-B) — list, create, deactivate/update; plus the RBAC/row-level
demonstrator from Phase 0-C. Owner (super_admin) manages users; office may only list/read.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_can_access_user, get_current_user, get_db, require_roles
from app.db.models import User
from app.schemas.auth import UserOut
from app.schemas.users import UserCreate, UserUpdate
from app.services import users as users_service

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    active: bool | None = None,
    role: str | None = None,
    _: User = Depends(require_roles("super_admin", "office_admin")),  # RBAC: delivery blocked
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    return await users_service.list_users(db, active=active, role=role)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        return await users_service.create_user(db, body)
    except users_service.PhoneAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a user with this phone already exists"
        ) from exc


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await users_service.update_user(db, user_id, body)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


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
