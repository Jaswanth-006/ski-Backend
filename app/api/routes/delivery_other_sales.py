"""Per-delivery-boy 'other sales' config routes (Phase C). Owner writes; office+owner read."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.delivery_other_sales import DeliveryOtherSalesOut, DeliveryOtherSalesSet
from app.services import delivery_other_sales as service

router = APIRouter(tags=["delivery-other-sales"])


@router.get("/delivery-other-sales", response_model=list[DeliveryOtherSalesOut])
async def list_delivery_other_sales(
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[DeliveryOtherSalesOut]:
    return await service.list_all(db)


@router.put("/delivery-other-sales/{delivery_id}", response_model=DeliveryOtherSalesOut)
async def set_delivery_other_sales(
    delivery_id: uuid.UUID,
    body: DeliveryOtherSalesSet,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> DeliveryOtherSalesOut:
    return await service.set_amount(db, delivery_id, body.amount_per_cylinder)
