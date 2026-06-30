"""FastAPI application factory.

Phase 0-A skeleton: app boots, exposes liveness/readiness probes, and auto-generates
the OpenAPI contract. Business routers (auth, stock, sales, ...) arrive in later phases.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ski — API",
        version=settings.version,
        description="System of record for an LPG distributorship. See 01-BACKEND-PRD.",
    )

    @app.get("/livez", tags=["health"])
    async def livez() -> dict[str, str]:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, str]:
        """Readiness: ready to serve traffic. Dependency checks land in Phase 0-F."""
        return {"status": "ready"}

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": settings.version, "env": settings.environment}

    return app


app = create_app()
