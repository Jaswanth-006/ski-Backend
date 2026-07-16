"""Sales schemas (Phase 3)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class SaleLineIn(BaseModel):
    cylinder_type_id: uuid.UUID
    qty: int = Field(ge=1)


class DenominationIn(BaseModel):
    note_value: int = Field(gt=0)
    note_count: int = Field(ge=0)


class SaleCreate(BaseModel):
    delivery_id: uuid.UUID | None = None  # a delivery boy…
    customer_id: uuid.UUID | None = None  # …or a corporate customer (exactly one)
    business_date: dt.date
    lines: list[SaleLineIn] = Field(min_length=1)
    denominations: list[DenominationIn] = Field(default_factory=list)
    upi_total: Decimal = Field(ge=0, default=Decimal(0))
    online_total: Decimal = Field(ge=0, default=Decimal(0))  # paid direct to the company
    balance_total: Decimal = Field(ge=0, default=Decimal(0))  # uncollected — the boy owes it

    @model_validator(mode="after")
    def _one_party(self) -> SaleCreate:
        if (self.delivery_id is None) == (self.customer_id is None):
            raise ValueError("provide exactly one of delivery_id or customer_id")
        return self


class SaleLineOut(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    qty: int
    unit_price: Decimal  # base cylinder price
    other_sales_per_unit: Decimal  # per-boy extra on top
    line_total: Decimal  # (unit_price + other_sales_per_unit) × qty


class SaleOut(BaseModel):
    id: uuid.UUID
    delivery_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    party_kind: str  # 'delivery' | 'customer'
    party_name: str
    business_date: dt.date
    status: str
    submitted_via: str
    created_at: dt.datetime
    lines: list[SaleLineOut]
    cash_total: Decimal
    upi_total: Decimal
    online_total: Decimal
    balance_total: Decimal  # uncollected — added to the boy's balance
    revenue_total: Decimal
    settled_total: Decimal  # cash + upi handed in
