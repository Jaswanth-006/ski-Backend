"""Deposit / transfer routes (Phase 8-C)."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.transfers import TransferCreate, TransferOut
from app.services import day_lock, idempotency
from app.services import transfers as transfers_service

router = APIRouter(tags=["transfers"])

_OFFICE = ("super_admin", "office_admin")


@router.post("/transfers", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    body: TransferCreate,
    idempotency_key: uuid.UUID | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> TransferOut:
    async def save() -> TransferOut:
        await day_lock.ensure_open(db, body.business_date, current_user)
        try:
            return await transfers_service.create_transfer(db, body, current_user.id)
        except transfers_service.InvalidReference as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"invalid {exc}") from exc

    try:
        result: TransferOut = await idempotency.run_once(db, idempotency_key, "transfer", save)
    except idempotency.KeyConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return result


@router.get("/transfers", response_model=list[TransferOut])
async def list_transfers(
    start: dt.date | None = None,
    end: dt.date | None = None,
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> list[TransferOut]:
    return await transfers_service.list_transfers(db, start=start, end=end)
