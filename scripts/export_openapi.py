"""Export the canonical OpenAPI spec from the FastAPI app to ``openapi.yaml``.

This file is the single source of truth for the API contract (00-MAIN-PRD §7). Run it
whenever the API changes:

    python scripts/export_openapi.py

The contract test (tests/test_openapi_contract.py) fails if the committed spec drifts
from the app, so regenerating is not optional.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from app.main import app

OUTPUT = Path(__file__).resolve().parent.parent / "openapi.yaml"


def main() -> None:
    spec = app.openapi()
    OUTPUT.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT} ({len(spec.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
