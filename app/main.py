"""FastAPI application factory.

Wires config, structured logging, Sentry, request-context middleware, health probes,
and the /v1 routers. Business routers arrive in later phases.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from app.api.middleware import RequestContextMiddleware
from app.api.routes import audit as audit_routes
from app.api.routes import auth as auth_routes
from app.api.routes import catalog as catalog_routes
from app.api.routes import day_sheet as day_sheet_routes
from app.api.routes import expenses as expenses_routes
from app.api.routes import jobs as jobs_routes
from app.api.routes import pricing as pricing_routes
from app.api.routes import sales as sales_routes
from app.api.routes import stock as stock_routes
from app.api.routes import users as users_routes
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.observability import init_sentry
from app.db.session import engine


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    init_sentry(settings)

    app = FastAPI(
        title="Ski — API",
        version=settings.version,
        description="System of record for an LPG distributorship. See 01-BACKEND-PRD.",
    )

    app.add_middleware(RequestContextMiddleware)

    app.include_router(auth_routes.router, prefix="/v1")
    app.include_router(users_routes.router, prefix="/v1")
    app.include_router(catalog_routes.router, prefix="/v1")
    app.include_router(pricing_routes.router, prefix="/v1")
    app.include_router(stock_routes.router, prefix="/v1")
    app.include_router(sales_routes.router, prefix="/v1")
    app.include_router(day_sheet_routes.router, prefix="/v1")
    app.include_router(expenses_routes.router, prefix="/v1")
    app.include_router(audit_routes.router, prefix="/v1")
    app.include_router(jobs_routes.router, prefix="/v1")

    @app.get("/livez", tags=["health"])
    async def livez() -> dict[str, str]:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, str]:
        """Readiness: the process can reach its database. 503 if not."""
        try:
            async with engine.connect() as conn:
                await conn.scalar(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 — surface any dependency failure as not-ready
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
            ) from exc
        return {"status": "ready"}

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": settings.version, "env": settings.environment}

    return app


app = create_app()
