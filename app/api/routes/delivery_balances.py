"""Delivery-boy balance routes (Phase K). Office + owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.delivery_balances import (
    DeliveryBalanceCreate,
    DeliveryBalanceEntryOut,
    DeliveryBalanceSummaryOut,
)
from app.services import delivery_balances as service

router = APIRouter(tags=["delivery-balances"])


@router.get("/delivery-balances/summary", response_model=list[DeliveryBalanceSummaryOut])
async def balance_summary(
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryBalanceSummaryOut]:
    return await service.summary(db)


@router.get("/delivery-balances", response_model=list[DeliveryBalanceEntryOut])
async def list_balance_entries(
    delivery_id: uuid.UUID,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryBalanceEntryOut]:
    return await service.list_entries(db, delivery_id)


@router.post(
    "/delivery-balances",
    response_model=DeliveryBalanceEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_balance_entry(
    body: DeliveryBalanceCreate,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> DeliveryBalanceEntryOut:
    return await service.create_entry(db, body, current_user.id)
