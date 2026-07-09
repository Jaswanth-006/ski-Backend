"""Deposit / transfer schemas (Phase 8-C)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceKind = Literal["cashier_box", "bank_account"]
DestKind = Literal["vendor", "person", "bank_account"]


class TransferCreate(BaseModel):
    business_date: dt.date
    amount: Decimal = Field(gt=0)
    source_kind: SourceKind
    source_bank_account_id: uuid.UUID | None = None
    dest_kind: DestKind
    dest_vendor_id: uuid.UUID | None = None
    dest_bank_account_id: uuid.UUID | None = None
    dest_person_name: str | None = Field(default=None, max_length=120)
    method: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_refs(self) -> TransferCreate:
        if self.source_kind == "bank_account" and self.source_bank_account_id is None:
            raise ValueError("source_bank_account_id required when source is a bank account")
        if self.dest_kind == "vendor" and self.dest_vendor_id is None:
            raise ValueError("dest_vendor_id required")
        if self.dest_kind == "bank_account" and self.dest_bank_account_id is None:
            raise ValueError("dest_bank_account_id required")
        if self.dest_kind == "person" and not self.dest_person_name:
            raise ValueError("dest_person_name required")
        if (
            self.source_kind == "bank_account"
            and self.dest_kind == "bank_account"
            and self.source_bank_account_id == self.dest_bank_account_id
        ):
            raise ValueError("source and destination accounts must differ")
        return self


class TransferOut(BaseModel):
    id: uuid.UUID
    business_date: dt.date
    amount: Decimal
    source_kind: SourceKind
    source_label: str  # "Cashier box" or "SBI · Savings"
    dest_kind: DestKind
    dest_label: str  # vendor name / person name / "HDFC · Current"
    method: str
    note: str | None
    created_at: dt.datetime
