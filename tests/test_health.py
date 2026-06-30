"""Smoke tests for the Phase 0-A skeleton: the app boots and probes answer."""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_livez() -> None:
    res = client.get("/livez")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readyz() -> None:
    res = client.get("/readyz")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}


def test_root() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["name"] == "ski-backend"
