"""Per-delivery-boy 'other sales' config schemas (Phase C)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class DeliveryOtherSalesOut(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    amount_per_cylinder: Decimal


class DeliveryOtherSalesSet(BaseModel):
    amount_per_cylinder: Decimal = Field(ge=0)
