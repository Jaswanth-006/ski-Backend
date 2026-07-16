"""Accessory catalog schemas (stock v2)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AccessoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class AccessoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class AccessoryOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
