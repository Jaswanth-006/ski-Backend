"""Customer catalog schemas (Phase I) — corporate direct-warehouse buyers."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
