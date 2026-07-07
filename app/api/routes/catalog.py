"""Master-data catalog routes — cylinder varieties (Phase 1-C).

GET is available to any authenticated user (it powers the sales dropdown); create/edit/
(de)activate are owner-only. Soft-delete keeps history intact (01-BACKEND-PRD §8.2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.db.models import CylinderType, ExpenseItem, User
from app.schemas.catalog import (
    CylinderTypeCreate,
    CylinderTypeOut,
    CylinderTypeUpdate,
    ExpenseItemCreate,
    ExpenseItemOut,
    ExpenseItemUpdate,
)
from app.services import catalog as catalog_service

router = APIRouter(tags=["catalog"])


@router.get("/cylinder-types", response_model=list[CylinderTypeOut])
async def list_cylinder_types(
    active: str = "true",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CylinderType]:
    return await catalog_service.list_cylinder_types(db, active=active)


@router.post("/cylinder-types", response_model=CylinderTypeOut, status_code=status.HTTP_201_CREATED)
async def create_cylinder_type(
    body: CylinderTypeCreate,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> CylinderType:
    try:
        return await catalog_service.create_cylinder_type(db, body)
    except catalog_service.CodeAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a cylinder type with this code already exists"
        ) from exc


@router.patch("/cylinder-types/{type_id}", response_model=CylinderTypeOut)
async def update_cylinder_type(
    type_id: uuid.UUID,
    body: CylinderTypeUpdate,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> CylinderType:
    try:
        row = await catalog_service.update_cylinder_type(db, type_id, body)
    except catalog_service.CodeAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a cylinder type with this code already exists"
        ) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="cylinder type not found")
    return row


# ---- Expense items (Phase 1-D) ----
@router.get("/expense-items", response_model=list[ExpenseItemOut])
async def list_expense_items(
    active: str = "true",
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[ExpenseItem]:
    return await catalog_service.list_expense_items(db, active=active)


@router.post("/expense-items", response_model=ExpenseItemOut, status_code=status.HTTP_201_CREATED)
async def create_expense_item(
    body: ExpenseItemCreate,
    current_user: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> ExpenseItem:
    try:
        return await catalog_service.create_expense_item(db, body, current_user.id)
    except catalog_service.NameAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="an expense item with this name already exists"
        ) from exc


@router.patch("/expense-items/{item_id}", response_model=ExpenseItemOut)
async def update_expense_item(
    item_id: uuid.UUID,
    body: ExpenseItemUpdate,
    _: User = Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
) -> ExpenseItem:
    row = await catalog_service.update_expense_item(db, item_id, body)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="expense item not found")
    return row
