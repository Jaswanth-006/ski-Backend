"""Temporal pricing schemas (Phase 1-E)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class PriceSet(BaseModel):
    cylinder_type_id: uuid.UUID
    unit_price: Decimal = Field(ge=0)
    effective_date: dt.date


class PriceBulkItem(BaseModel):
    cylinder_type_id: uuid.UUID
    unit_price: Decimal = Field(ge=0)


class PriceBulkSet(BaseModel):
    effective_date: dt.date
    prices: list[PriceBulkItem] = Field(min_length=1)


class PriceOut(BaseModel):
    """The effective price for one active cylinder type on the requested date
    (unit_price/effective_date are null when no price is set on/before that date)."""

    cylinder_type_id: uuid.UUID
    code: str
    label: str
    unit_price: Decimal | None
    effective_date: dt.date | None
