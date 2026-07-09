"""Auth routes: login, refresh, logout, and the current-user profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import rate_limit
from app.db.models import User
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenPair, UserOut
from app.services import auth as auth_service

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenPair)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    if await rate_limit.is_login_blocked(body.phone):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many failed attempts — try again later",
        )
    try:
        user = await auth_service.authenticate_user(db, body.phone, body.password)
    except auth_service.AuthError as exc:
        await rate_limit.record_login_failure(body.phone)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials") from exc
    await rate_limit.clear_login_failures(body.phone)
    access, refresh = await auth_service.issue_token_pair(db, user)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    try:
        access, new_refresh = await auth_service.rotate_refresh_token(db, body.refresh_token)
    except auth_service.AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, db: AsyncSession = Depends(get_db)) -> None:
    await auth_service.logout(db, body.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
