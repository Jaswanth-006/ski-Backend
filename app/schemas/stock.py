"""Stock v2 schemas — ac4 (received), erv (empty return), and the daily overview."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


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
