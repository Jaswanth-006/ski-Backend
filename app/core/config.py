"""Application configuration.

All values come from the environment (or a local ``.env`` for development only).
Secrets are never committed — see ``.env.example`` for the contract. Full config
catalog lives in 01-BACKEND-PRD §14; Phase 0-A only needs the basics to boot.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ski-backend"
    environment: str = "dev"
    version: str = "0.1.0"


settings = Settings()
