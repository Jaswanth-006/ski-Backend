"""Contract snapshot test (01-BACKEND-PRD §16): the committed openapi.yaml must match
the live app, so any API change is an intentional, reviewable spec change.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from app.main import app

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi.yaml"


def test_committed_openapi_matches_app() -> None:
    assert SPEC_PATH.exists(), "openapi.yaml missing — run: python scripts/export_openapi.py"
    committed = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    live = yaml.safe_load(yaml.safe_dump(app.openapi()))  # normalize tuples/ordering
    assert committed == live, "openapi.yaml is out of date — run: python scripts/export_openapi.py"


def test_core_endpoints_present() -> None:
    paths = app.openapi()["paths"]
    for expected in ("/v1/auth/login", "/v1/auth/refresh", "/v1/me", "/v1/users"):
        assert expected in paths
