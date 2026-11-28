"""Per-delivery-boy 'other sales' config schemas (Phase C)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class DeliveryOtherSalesOut(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    amount_per_cylinder: Decimal
    # The date this amount has applied from (None = never set).
    effective_date: dt.date | None = None


class DeliveryOtherSalesSet(BaseModel):
    amount_per_cylinder: Decimal = Field(ge=0)
    # Applies to sales from this date on (default: today). Earlier sales keep their extra.
    effective_date: dt.date | None = None
