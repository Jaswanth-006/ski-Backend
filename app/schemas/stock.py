"""Stock v2 schemas — ac4 (received), erv (empty return), return (damaged/lost), overview."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Ac4CylinderLine(BaseModel):
    cylinder_type_id: uuid.UUID
    qty: int = Field(ge=1)


class Ac4AccessoryLine(BaseModel):
    accessory_id: uuid.UUID
    qty: int = Field(ge=1)


class Ac4Request(BaseModel):
    """Stock received from the plant: full cylinders and/or accessories added to stock."""

    business_date: dt.date | None = None  # defaults to today
    cylinders: list[Ac4CylinderLine] = Field(default_factory=list)
    accessories: list[Ac4AccessoryLine] = Field(default_factory=list)


class ErvLine(BaseModel):
    cylinder_type_id: uuid.UUID
    qty: int = Field(ge=1)


class ErvRequest(BaseModel):
    """Empty cylinders returned to the plant: reduces empty stock."""

    business_date: dt.date | None = None  # defaults to today
    lines: list[ErvLine] = Field(min_length=1)


class ReturnLine(BaseModel):
    """One damaged/lost item: a cylinder (full or empty) or an accessory."""

    cylinder_type_id: uuid.UUID | None = None
    accessory_id: uuid.UUID | None = None
    condition: Literal["full", "empty"] | None = None  # cylinders only
    qty: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=200)  # e.g. "damaged", "lost"

    @model_validator(mode="after")
    def _one_item(self) -> ReturnLine:
        if (self.cylinder_type_id is None) == (self.accessory_id is None):
            raise ValueError("give exactly one of cylinder_type_id or accessory_id")
        if self.cylinder_type_id is not None and self.condition is None:
            raise ValueError("condition (full/empty) is required for a cylinder")
        if self.accessory_id is not None and self.condition is not None:
            raise ValueError("accessories have no condition")
        return self


class ReturnRequest(BaseModel):
    """Damaged or lost items taken out of stock."""

    business_date: dt.date | None = None  # defaults to today
    lines: list[ReturnLine] = Field(min_length=1)


class CylinderStockRow(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    # Full cylinders
    full_opening: int  # carried in from prior days
    full_received: int  # ac4 today
    full_sold: int  # sold today (from sales; stock v2 phase B)
    full_closing: int
    # Empty cylinders
    empty_opening: int
    empty_returned_by_customers: int  # +empty from sales today (phase B)
    empty_sent_to_plant: int  # erv today
    empty_closing: int


class AccessoryStockRow(BaseModel):
    accessory_id: uuid.UUID
    name: str
    opening: int
    received: int  # ac4 today
    sold: int  # sold today (phase B)
    closing: int


class StockOverview(BaseModel):
    business_date: dt.date
    cylinders: list[CylinderStockRow]
    accessories: list[AccessoryStockRow]
