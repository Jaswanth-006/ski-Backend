"""Deposit / transfer schemas.

Money moves from a source to a destination:
- from: cashier box, own bank account, or a person (a debtor paying back, a creditor lending);
- to: vendor, person, own bank account, or the cashier box.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceKind = Literal["cashier_box", "bank_account", "person"]
DestKind = Literal["vendor", "person", "bank_account", "cashier_box"]


class TransferCreate(BaseModel):
    business_date: dt.date
    amount: Decimal = Field(gt=0)
    source_kind: SourceKind
    source_bank_account_id: uuid.UUID | None = None
    source_person_id: uuid.UUID | None = None
    dest_kind: DestKind
    dest_vendor_id: uuid.UUID | None = None
    dest_bank_account_id: uuid.UUID | None = None
    dest_person_id: uuid.UUID | None = None
    method: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_refs(self) -> TransferCreate:
        if self.source_kind == "bank_account" and self.source_bank_account_id is None:
            raise ValueError("source_bank_account_id required when source is a bank account")
        if self.source_kind == "person" and self.source_person_id is None:
            raise ValueError("source_person_id required when source is a person")
        if self.dest_kind == "vendor" and self.dest_vendor_id is None:
            raise ValueError("dest_vendor_id required")
        if self.dest_kind == "bank_account" and self.dest_bank_account_id is None:
            raise ValueError("dest_bank_account_id required")
        if self.dest_kind == "person" and self.dest_person_id is None:
            raise ValueError("dest_person_id required")
        # Keep only the ids that match the chosen kinds.
        if self.source_kind != "bank_account":
            self.source_bank_account_id = None
        if self.source_kind != "person":
            self.source_person_id = None
        if self.dest_kind != "vendor":
            self.dest_vendor_id = None
        if self.dest_kind != "bank_account":
            self.dest_bank_account_id = None
        if self.dest_kind != "person":
            self.dest_person_id = None
        if self.source_kind == "cashier_box" and self.dest_kind == "cashier_box":
            raise ValueError("source and destination must differ")
        if self.source_kind == "person" and self.dest_kind in ("person", "vendor"):
            raise ValueError("money from a person goes to the cashier box or a bank account")
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
    # "online" = customers paid the vendor online with a sale (recorded by the sale itself)
    source_kind: Literal["cashier_box", "bank_account", "person", "online"]
    source_label: str  # "Cashier box", "SBI · Savings" or a person's name
    source_person_id: uuid.UUID | None = None
    dest_kind: DestKind
    dest_label: str  # vendor / person name, "HDFC · Current" or "Cashier box"
    dest_person_id: uuid.UUID | None = None
    method: str
    note: str | None
    sale_id: uuid.UUID | None = None  # made by a sale — change it by editing that invoice
    created_at: dt.datetime
