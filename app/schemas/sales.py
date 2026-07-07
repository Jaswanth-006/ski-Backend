"""Sales schemas (Phase 3)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class SaleLineIn(BaseModel):
    cylinder_type_id: uuid.UUID
    qty: int = Field(ge=1)


class DenominationIn(BaseModel):
    note_value: int = Field(gt=0)
    note_count: int = Field(ge=0)


class SaleCreate(BaseModel):
    delivery_id: uuid.UUID
    business_date: dt.date
    lines: list[SaleLineIn] = Field(min_length=1)
    denominations: list[DenominationIn] = Field(default_factory=list)
    upi_total: Decimal = Field(ge=0, default=Decimal(0))


class SaleLineOut(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    qty: int
    unit_price: Decimal
    line_total: Decimal


class SaleOut(BaseModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    delivery_name: str
    business_date: dt.date
    status: str
    submitted_via: str
    created_at: dt.datetime
    lines: list[SaleLineOut]
    cash_total: Decimal
    upi_total: Decimal
    revenue_total: Decimal
