"""Opening stock: what was on hand when the app started being used (Master Catalog)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OpeningStockLine(BaseModel):
    """One item: a cylinder type (full or empty) or an accessory."""

    cylinder_type_id: uuid.UUID | None = None
    accessory_id: uuid.UUID | None = None
    condition: Literal["full", "empty"] | None = None  # cylinders only
    qty: int = Field(ge=0)

    @model_validator(mode="after")
    def _one_item(self) -> OpeningStockLine:
        if (self.cylinder_type_id is None) == (self.accessory_id is None):
            raise ValueError("give exactly one of cylinder_type_id or accessory_id")
        if self.cylinder_type_id is not None and self.condition is None:
            raise ValueError("a cylinder line needs full or empty")
        if self.accessory_id is not None:
            self.condition = None
        return self


class OpeningStockSet(BaseModel):
    """The whole opening stock as on ``as_of`` (stock at the start of that day).

    Replaces any opening stock saved before; items left out (or 0) have none."""

    as_of: dt.date
    lines: list[OpeningStockLine]
    reason: str | None = Field(default=None, max_length=280)


class OpeningStockRow(BaseModel):
    cylinder_type_id: uuid.UUID | None
    accessory_id: uuid.UUID | None
    condition: Literal["full", "empty"] | None
    label: str
    qty: int


class OpeningStockOut(BaseModel):
    as_of: dt.date | None  # None until an opening stock is saved
    rows: list[OpeningStockRow]  # every active cylinder type (full, empty) and accessory
