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

    # Auth (Phase 0-C). JWT_SECRET MUST be overridden via env in real environments.
    jwt_secret: str = "dev-insecure-secret-change-me-min-32-bytes"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # Observability (Phase 0-D). Sentry is disabled unless a DSN is provided.
    log_level: str = "INFO"
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    # Redis / Celery (Phase 0-F). Broker + result backend default to REDIS_URL.
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Object storage (Phase 0-F) — S3-compatible (MinIO locally). Disabled unless configured.
    object_storage_endpoint: str | None = None
    object_storage_bucket: str = "ski"
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None
    object_storage_region: str = "us-east-1"
    presign_ttl_seconds: int = 3600

    @property
    def replica_url(self) -> str:
        return self.database_replica_url or self.database_url

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


settings = Settings()
