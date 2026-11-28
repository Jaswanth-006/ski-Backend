"""Banking master-data schemas — banks, bank accounts, vendors, people (debtors / creditors).

Every account, vendor and person carries an opening balance entered when it is added:
- bank account: money in the account at that time;
- vendor: amount already paid to them;
- debtor: what they already owed us; creditor: what we already owed them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from app.schemas.sales import to_paise

PersonKind = Literal["debtor", "creditor"]
Money = Annotated[Decimal, AfterValidator(to_paise)]


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
    opening_balance: Money = Decimal(0)


class BankAccountUpdate(BaseModel):
    account_type: str | None = Field(default=None, min_length=1, max_length=60)
    label: str | None = Field(default=None, max_length=120)
    opening_balance: Money | None = None
    is_active: bool | None = None


class BankAccountOut(BaseModel):
    id: uuid.UUID
    bank_id: uuid.UUID
    bank_name: str
    account_type: str
    label: str | None
    is_active: bool
    opening_balance: Decimal
    balance: Decimal  # opening + money in − money out


class VendorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    opening_balance: Money = Field(default=Decimal(0), ge=0)


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    opening_balance: Money | None = Field(default=None, ge=0)
    is_active: bool | None = None


class VendorOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    opening_balance: Decimal  # paid before the app
    paid: Decimal  # paid through deposits in the app
    total_paid: Decimal  # opening + paid
    used: Decimal  # taken by ac4 purchases
    balance: Decimal  # total_paid − used (below zero: purchases not yet covered)


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: PersonKind
    phone: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=500)
    opening_balance: Money = Field(default=Decimal(0), ge=0)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name required")
        return v


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=500)
    opening_balance: Money | None = Field(default=None, ge=0)
    is_active: bool | None = None


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: PersonKind
    phone: str | None
    note: str | None
    is_active: bool
    opening_balance: Decimal
    given: Decimal  # money we paid out to them
    received: Decimal  # money they paid in to us
    # Debtor: opening + given − received (they owe us).
    # Creditor: opening + received − given (we owe them).
    balance: Decimal
    created_at: dt.datetime
