"""Sales routes (Phase 3). In v1 a web sale is created and posted in one transaction."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.sales import SaleCancel, SaleCreate, SaleEdit, SaleOut
from app.services import sales as sales_service

router = APIRouter(tags=["sales"])

_OFFICE = ("super_admin", "office_admin")


@router.post("/sales", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
async def create_sale(
    body: SaleCreate,
    idempotency_key: uuid.UUID = Header(alias="Idempotency-Key"),
    current_user: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> SaleOut:
    try:
        return await sales_service.create_and_post_sale(db, body, idempotency_key, current_user)
    except sales_service.SaleError as exc:
        raise _http_error(exc) from exc


@router.post("/sales/{sale_id}/cancel", response_model=SaleOut)
async def cancel_sale(
    sale_id: uuid.UUID,
    body: SaleCancel,
    current_user: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> SaleOut:
    try:
        return await sales_service.cancel_sale(db, sale_id, body.reason, current_user)
    except sales_service.SaleError as exc:
        raise _http_error(exc) from exc


@router.post("/sales/{sale_id}/edit", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
async def edit_sale(
    sale_id: uuid.UUID,
    body: SaleEdit,
    idempotency_key: uuid.UUID = Header(alias="Idempotency-Key"),
    current_user: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> SaleOut:
    """Replace a sale with a corrected one: the original is cancelled, the new one posted."""
    try:
        return await sales_service.replace_sale(
            db, sale_id, body.reason, body.sale, idempotency_key, current_user
        )
    except sales_service.SaleError as exc:
        raise _http_error(exc) from exc


def _http_error(exc: sales_service.SaleError) -> HTTPException:
    if isinstance(exc, sales_service.SaleNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="sale not found")
    if isinstance(exc, sales_service.SaleNotCancellable):
        return HTTPException(status.HTTP_409_CONFLICT, detail="this sale is already cancelled")
    if isinstance(exc, sales_service.DuplicateInvoice):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, sales_service.DayClosed):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail="the day sheet is closed — only the owner can change it"
            if exc.owner_can_change
            else "the day sheet is closed",
        )
    if isinstance(exc, sales_service.NoPriceForDate):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, sales_service.InsufficientStock):
        return HTTPException(status.HTTP_409_CONFLICT, detail=f"insufficient stock for {exc.code}")
    if isinstance(exc, sales_service.ReconciliationFailed):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"flags": exc.flags})
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/sales", response_model=list[SaleOut])
async def list_sales(
    date: dt.date | None = None,
    status_filter: str | None = None,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[SaleOut]:
    return await sales_service.list_sales(db, business_date=date, status=status_filter)


@router.get("/sales/{sale_id}", response_model=SaleOut)
async def get_sale(
    sale_id: uuid.UUID,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> SaleOut:
    sale = await sales_service.get_sale(db, sale_id)
    if sale is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="sale not found")
    return sale
