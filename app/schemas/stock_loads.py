"""Per-driver stock load/return schemas (Phase 8-D)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class StockLoadUpsert(BaseModel):
    business_date: dt.date
    delivery_id: uuid.UUID
    cylinder_type_id: uuid.UUID
    loaded_qty: int = Field(ge=0)
    returned_qty: int = Field(default=0, ge=0)


class StockLoadOut(BaseModel):
    id: uuid.UUID
    business_date: dt.date
    delivery_id: uuid.UUID
    delivery_name: str
    cylinder_type_id: uuid.UUID
    code: str
    loaded_qty: int
    returned_qty: int
