"""Tests for logging, request-id propagation, health readiness, and Sentry wiring."""

from __future__ import annotations

import json
import logging

import sentry_sdk
from app.core.config import Settings
from app.core.logging import JsonFormatter, request_id_ctx
from app.core.observability import init_sentry
from httpx import AsyncClient

from tests.conftest import SeededUsers


# ---- JSON logging ----
def test_json_formatter_emits_valid_json() -> None:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)
    out = json.loads(JsonFormatter().format(record))
    assert out["level"] == "INFO"
    assert out["message"] == "hello"
    assert "timestamp" in out


def test_json_formatter_includes_request_id() -> None:
    token = request_id_ctx.set("rid-123")
    try:
        record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hi", None, None)
        out = json.loads(JsonFormatter().format(record))
        assert out["request_id"] == "rid-123"
    finally:
        request_id_ctx.reset(token)


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.LogRecord("app.access", logging.INFO, __file__, 1, "request", None, None)
    record.method = "GET"
    record.status = 200
    out = json.loads(JsonFormatter().format(record))
    assert out["method"] == "GET"
    assert out["status"] == 200


# ---- Sentry ----
def test_sentry_disabled_without_dsn() -> None:
    assert init_sentry(Settings(sentry_dsn=None)) is False


def test_sentry_captures_exception_with_dsn() -> None:
    captured: list[object] = []
    settings = Settings(
        sentry_dsn="https://examplePublicKey@o0.ingest.sentry.io/0", environment="test"
    )
    assert init_sentry(settings, transport=captured.append) is True
    try:
        raise ValueError("boom-observability")
    except ValueError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()
    try:
        assert any("boom-observability" in json.dumps(e, default=str) for e in captured)
    finally:
        sentry_sdk.get_client().close()


# ---- Request id + readiness (DB-backed) ----
async def test_response_has_request_id_header(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    res = await http.get("/v1/me")  # 401, but the middleware still stamps the id
    assert "x-request-id" in {k.lower() for k in res.headers}


async def test_readyz_ok_when_db_reachable(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    res = await http.get("/readyz")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}
