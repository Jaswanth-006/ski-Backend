"""User management schemas (Phase 1-B)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

ROLES = {"super_admin", "office_admin", "delivery"}


def _validate_role(value: str) -> str:
    if value not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    return value


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=3, max_length=20)
    role: str
    password: str = Field(min_length=8, max_length=200)

    @field_validator("role")
    @classmethod
    def check_role(cls, value: str) -> str:
        return _validate_role(value)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)

    @field_validator("role")
    @classmethod
    def check_role(cls, value: str | None) -> str | None:
        return None if value is None else _validate_role(value)
