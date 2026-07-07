"""Master-data catalog schemas — cylinder varieties (Phase 1-C)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CylinderTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=120)


class CylinderTypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class CylinderTypeOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    is_active: bool


class ExpenseItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=120)


class ExpenseItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class ExpenseItemOut(BaseModel):
    id: uuid.UUID
    name: str
    category: str | None
    is_active: bool
