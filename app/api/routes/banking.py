"""Banking master-data routes (Phase 8-B) — banks, bank accounts, vendors.

GET is available to owner + office (they drive the deposit form); create/edit/(de)activate
are owner-only. Soft-delete keeps history intact.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import Bank, User, Vendor
from app.schemas.banking import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankCreate,
    BankOut,
    BankUpdate,
    VendorCreate,
    VendorOut,
    VendorUpdate,
)
from app.services import banking as banking_service

router = APIRouter(tags=["banking"])

_OFFICE = ("super_admin", "office_admin")
_OWNER = ("super_admin",)


# ---- Banks ----
@router.get("/banks", response_model=list[BankOut])
async def list_banks(
    active: str = "true",
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> list[Bank]:
    return await banking_service.list_banks(db, active=active)


@router.post("/banks", response_model=BankOut, status_code=status.HTTP_201_CREATED)
async def create_bank(
    body: BankCreate,
    _: User = Depends(require_roles(*_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> Bank:
    try:
        return await banking_service.create_bank(db, body)
    except banking_service.NameAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a bank with this name exists"
        ) from exc


@router.patch("/banks/{bank_id}", response_model=BankOut)
async def update_bank(
    bank_id: uuid.UUID,
    body: BankUpdate,
    _: User = Depends(require_roles(*_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> Bank:
    try:
        row = await banking_service.update_bank(db, bank_id, body)
    except banking_service.NameAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a bank with this name exists"
        ) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bank not found")
    return row


# ---- Bank accounts ----
@router.get("/bank-accounts", response_model=list[BankAccountOut])
async def list_bank_accounts(
    active: str = "true",
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> list[BankAccountOut]:
    return await banking_service.list_bank_accounts(db, active=active)


@router.post("/bank-accounts", response_model=BankAccountOut, status_code=status.HTTP_201_CREATED)
async def create_bank_account(
    body: BankAccountCreate,
    _: User = Depends(require_roles(*_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> BankAccountOut:
    try:
        return await banking_service.create_bank_account(db, body)
    except banking_service.InvalidBank as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid bank") from exc


@router.patch("/bank-accounts/{account_id}", response_model=BankAccountOut)
async def update_bank_account(
    account_id: uuid.UUID,
    body: BankAccountUpdate,
    _: User = Depends(require_roles(*_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> BankAccountOut:
    row = await banking_service.update_bank_account(db, account_id, body)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bank account not found")
    return row


# ---- Vendors ----
@router.get("/vendors", response_model=list[VendorOut])
async def list_vendors(
    active: str = "true",
    _: User = Depends(require_roles(*_OFFICE)),
    db: AsyncSession = Depends(get_db),
) -> list[Vendor]:
    return await banking_service.list_vendors(db, active=active)


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: VendorCreate,
    _: User = Depends(require_roles(*_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> Vendor:
    try:
        return await banking_service.create_vendor(db, body)
    except banking_service.NameAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a vendor with this name exists"
        ) from exc


@router.patch("/vendors/{vendor_id}", response_model=VendorOut)
async def update_vendor(
    vendor_id: uuid.UUID,
    body: VendorUpdate,
    _: User = Depends(require_roles(*_OWNER)),
    db: AsyncSession = Depends(get_db),
) -> Vendor:
    try:
        row = await banking_service.update_vendor(db, vendor_id, body)
    except banking_service.NameAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="a vendor with this name exists"
        ) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return row
