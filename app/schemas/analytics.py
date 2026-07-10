"""EOD analytics schema (Phase 4-E). Aggregation only — no ML."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class EodOut(BaseModel):
    business_date: dt.date
    cylinders_sold: int
    gross_cash: Decimal
    upi_total: Decimal
    expenses_total: Decimal
    # Owner-only; null for office_admin (margins are hidden).
    net_profit: Decimal | None


class CollectionPoint(BaseModel):
    business_date: dt.date
    total: Decimal  # cash + UPI collected that day


class CollectionsTrendOut(BaseModel):
    points: list[CollectionPoint]  # oldest first, ending on the requested date


class CylinderMovementRow(BaseModel):
    code: str
    label: str
    loaded: int  # cylinders loaded out to drivers that day
    sold: int  # cylinders sold that day
    left: int  # warehouse cylinders on hand at end of day


class CylinderMovementOut(BaseModel):
    business_date: dt.date
    rows: list[CylinderMovementRow]  # one per active cylinder type
