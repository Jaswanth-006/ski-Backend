"""Sales routes (Phase 3). In v1 a web sale is created and posted in one transaction."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.sales import SaleCreate, SaleOut
from app.services import sales as sales_service

router = APIRouter(tags=["sales"])


@router.post("/sales", response_model=SaleOut, status_code=status.HTTP_201_CREATED)
async def create_sale(
    body: SaleCreate,
    idempotency_key: uuid.UUID = Header(alias="Idempotency-Key"),
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> SaleOut:
    try:
        return await sales_service.create_and_post_sale(db, body, idempotency_key, current_user)
    except sales_service.DayClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="the day sheet is closed") from exc
    except sales_service.NoPriceForDate as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except sales_service.InsufficientStock as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"insufficient stock for {exc.code}"
        ) from exc
    except sales_service.ReconciliationFailed as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"flags": exc.flags}
        ) from exc


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
