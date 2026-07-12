"""Credit (receivables) routes (Phase E). Office + owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.credits import CreditCreate, CreditOut
from app.services import credits as credits_service

router = APIRouter(tags=["credits"])


@router.get("/credits", response_model=list[CreditOut])
async def list_credits(
    settled: bool | None = None,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[CreditOut]:
    return await credits_service.list_credits(db, settled=settled)


@router.post("/credits", response_model=CreditOut, status_code=status.HTTP_201_CREATED)
async def create_credit(
    body: CreditCreate,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> CreditOut:
    return await credits_service.create_credit(db, body, current_user.id)


@router.post("/credits/{credit_id}/settle", response_model=CreditOut)
async def settle_credit(
    credit_id: uuid.UUID,
    settled: bool = True,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> CreditOut:
    try:
        return await credits_service.settle_credit(db, credit_id, settled=settled)
    except credits_service.CreditNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="credit not found") from exc
