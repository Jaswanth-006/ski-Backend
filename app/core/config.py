"""Application configuration.

All values come from the environment (or a local ``.env`` for development only).
Secrets are never committed — see ``.env.example`` for the contract. Full config
catalog lives in 01-BACKEND-PRD §14; added incrementally per phase.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ski-backend"
    environment: str = "dev"
    version: str = "0.1.0"

    # Database (Phase 0-B). Primary is read/write; replica is analytics-only and
    # falls back to the primary when unset (single-DB local/dev).
    database_url: str = "postgresql+asyncpg://ski:ski@localhost:5432/ski"
    database_replica_url: str | None = None

    # Seed super_admin created by the seed migration (Phase 0-B). Override in real
    # environments; the default password must be rotated after first login.
    seed_admin_name: str = "R. Kamala"
    seed_admin_phone: str = "9000000001"
    seed_admin_password: str = "ChangeMe@123"

    @property
    def replica_url(self) -> str:
        return self.database_replica_url or self.database_url


settings = Settings()
