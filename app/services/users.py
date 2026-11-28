"""User management service (Phase 1-B): create/update staff and delivery accounts."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import User
from app.schemas.users import UserCreate, UserUpdate
from app.services.auth import revoke_user_sessions


class PhoneAlreadyExists(Exception):
    """A user with the given phone already exists."""


class OwnerLockout(Exception):
    """The change would leave no active owner (or the owner is locking themselves out)."""


async def list_users(
    db: AsyncSession, active: bool | None = None, role: str | None = None
) -> list[User]:
    stmt = select(User)
    if active is not None:
        stmt = stmt.where(User.is_active == active)
    if role is not None:
        stmt = stmt.where(User.role == role)
    result = await db.scalars(stmt.order_by(User.created_at))
    return list(result)


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    user = User(
        name=data.name,
        phone=data.phone,
        role=data.role,
        password_hash=hash_password(data.password),
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise PhoneAlreadyExists(data.phone) from exc
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession, user_id: uuid.UUID, data: UserUpdate, actor_id: uuid.UUID | None = None
) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    stays_owner = (data.role or user.role) == "super_admin" and (
        user.is_active if data.is_active is None else data.is_active
    )
    if user.role == "super_admin" and user.is_active and not stays_owner:
        if user_id == actor_id:
            raise OwnerLockout("you can't deactivate yourself or remove your own owner role")
        others = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "super_admin", User.is_active.is_(True), User.id != user_id)
        )
        if not others:
            raise OwnerLockout("there must be at least one active owner")
    signs_out = data.password is not None or data.is_active is False
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    if signs_out:
        # A new password or deactivation ends every session they had open (roles are read
        # fresh on each request, so a role change needs no sign-out).
        await revoke_user_sessions(db, user.id)
    await db.commit()
    await db.refresh(user)
    return user
