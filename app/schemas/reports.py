"""Date-range report schemas (Phase 8-E)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel


class StockReportRow(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    bought: int  # intake
    sold: int
    loaded: int
    returned: int


class DeliveryReportRow(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    sold: int
    loaded: int
    returned: int


class ExpenseReportRow(BaseModel):
    item_id: uuid.UUID
    item_name: str
    total: Decimal
    count: int


class DepositReportRow(BaseModel):
    kind: str  # vendor | person | bank_account
    recipient: str
    total: Decimal
    count: int
