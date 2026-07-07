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
