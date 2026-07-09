"""Cashier box schema (Phase 8-A) — persistent cash-in-hand."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class CashierBoxOut(BaseModel):
    business_date: dt.date
    opening: Decimal  # carried from the previous day's closing
    collected: Decimal  # cash + UPI collected on this date
    expenses: Decimal  # expenses on this date
    deposited: Decimal  # box-sourced deposits on this date
    closing: Decimal  # opening + collected − expenses − deposited
