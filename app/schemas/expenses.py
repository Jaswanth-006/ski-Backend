"""Expense schemas (Phase 4-C)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class ExpenseCreate(BaseModel):
    business_date: dt.date
    item_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    method: str
    note: str | None = Field(default=None, max_length=280)
    delivery_id: uuid.UUID | None = None  # attribute this expense to a delivery boy

    @field_validator("method")
    @classmethod
    def check_method(cls, value: str) -> str:
        if value not in ("cash", "digital"):
            raise ValueError("method must be 'cash' or 'digital'")
        return value


class ExpenseOut(BaseModel):
    id: uuid.UUID
    business_date: dt.date
    item_id: uuid.UUID
    item_name: str
    amount: Decimal
    method: str
    note: str | None
    delivery_id: uuid.UUID | None
    delivery_name: str | None
    created_at: dt.datetime
