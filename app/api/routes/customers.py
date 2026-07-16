"""Customer catalog routes (Phase I). Office + owner read; owner manages."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.db.models import User
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate
from app.services import customers as customers_service

router = APIRouter(tags=["customers"])


@router.get("/customers", response_model=list[CustomerOut])
async def list_customers(
    active_only: bool = True,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CustomerOut]:
    return await customers_service.list_customers(db, active_only=active_only)


@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(
    body: CustomerCreate,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> CustomerOut:
    try:
        return await customers_service.create_customer(db, body.name)
    except customers_service.DuplicateCustomer as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="customer already exists") from exc


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> CustomerOut:
    try:
        return await customers_service.update_customer(db, customer_id, body)
    except customers_service.CustomerNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="customer not found") from exc
    except customers_service.DuplicateCustomer as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="customer already exists") from exc
