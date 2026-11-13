"""Expense routes (Phase 4-C)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.expenses import ExpenseCreate, ExpenseOut
from app.services import day_lock
from app.services import expenses as expenses_service

router = APIRouter(tags=["expenses"])


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def create_expense(
    body: ExpenseCreate,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> ExpenseOut:
    await day_lock.ensure_open(db, body.business_date, current_user)
    try:
        return await expenses_service.create_expense(db, body, current_user.id)
    except expenses_service.InvalidDeliveryPerson as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="delivery person not found") from exc
    except expenses_service.InvalidExpenseItem as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid expense item") from exc


@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(
    date: dt.date | None = None,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> list[ExpenseOut]:
    return await expenses_service.list_expenses(db, on_date=date)
