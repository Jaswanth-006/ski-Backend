"""Stock & inventory schemas (Phase 2)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class StockIntakeLine(BaseModel):
    cylinder_type_id: uuid.UUID
    qty: int = Field(ge=1)


class StockIntake(BaseModel):
    lines: list[StockIntakeLine] = Field(min_length=1)


class InventoryOut(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    quantity: int
    version: int


class InventoryAdjust(BaseModel):
    quantity: int = Field(ge=0)
