"""Banking master-data schemas (Phase 8-B) — banks, bank accounts, vendors."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class BankCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class BankUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class BankOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool


class BankAccountCreate(BaseModel):
    bank_id: uuid.UUID
    account_type: str = Field(min_length=1, max_length=60)
    label: str | None = Field(default=None, max_length=120)


class BankAccountUpdate(BaseModel):
    account_type: str | None = Field(default=None, min_length=1, max_length=60)
    label: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class BankAccountOut(BaseModel):
    id: uuid.UUID
    bank_id: uuid.UUID
    bank_name: str
    account_type: str
    label: str | None
    is_active: bool
    balance: Decimal  # running balance from transfers in/out


class VendorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class VendorOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
