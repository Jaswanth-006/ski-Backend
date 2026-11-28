"""Customer balance routes. Office + owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.customer_balances import (
    CustomerBalanceCreate,
    CustomerBalanceEntryOut,
    CustomerBalanceSummaryOut,
)
from app.services import customer_balances as service
from app.services import day_lock, idempotency
from app.services import transfers as transfers_service

router = APIRouter(tags=["customer-balances"])


@router.get("/customer-balances/summary", response_model=list[CustomerBalanceSummaryOut])
async def customer_balance_summary(
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[CustomerBalanceSummaryOut]:
    return await service.summary(db)


@router.get("/customer-balances", response_model=list[CustomerBalanceEntryOut])
async def list_customer_balance_entries(
    customer_id: uuid.UUID,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[CustomerBalanceEntryOut]:
    return await service.list_entries(db, customer_id)


@router.post(
    "/customer-balances",
    response_model=CustomerBalanceEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_balance_entry(
    body: CustomerBalanceCreate,
    idempotency_key: uuid.UUID | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> CustomerBalanceEntryOut:
    async def save() -> CustomerBalanceEntryOut:
        await day_lock.ensure_open(db, body.entry_date, current_user)
        try:
            return await service.create_entry(db, body, current_user.id)
        except service.InvalidCustomer as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid customer") from exc
        except transfers_service.InvalidReference as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid bank account") from exc

    try:
        result: CustomerBalanceEntryOut = await idempotency.run_once(
            db, idempotency_key, "customer_balance", save
        )
    except idempotency.KeyConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return result
