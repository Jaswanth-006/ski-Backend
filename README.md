# ski-backend

System of record for Ski — FastAPI (Python 3.12). One image serves the API process (the
Celery worker process type arrives in Phase 0-F). See the PRDs in the parent `IOC/`
workspace: `00-MAIN-PRD`, `01-BACKEND-PRD`, `04-IMPLEMENTATION-PLAN`.

> **Status: Phase 0-A (Foundations — Repos & CI/CD).** Skeleton only: the app boots,
> exposes health probes, and CI runs lint → typecheck → test → build green. Schema,
> auth, and business features land in later phases.

## Requirements
- Python 3.12

## Setup
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate    |  macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Run
```bash
uvicorn app.main:app --reload
# http://127.0.0.1:8000/livez   → {"status":"ok"}
# http://127.0.0.1:8000/docs    → OpenAPI / Swagger UI
```

## Quality gates (same as CI)
```bash
ruff check .          # lint
ruff format --check . # format
mypy                  # typecheck (strict)
pytest                # tests
docker build -t ski-backend .   # build
```

## CI/CD
`.github/workflows/ci.yml` runs on every push/PR to `main`:
`quality` (lint, format, typecheck, test) → `build` (docker) → `deploy-dev` (on `main`).

**Deploy:** the `deploy-dev` job posts to a deploy hook. Set the `DEV_DEPLOY_HOOK` repo
secret (e.g. a Render/Fly deploy hook URL) under Settings → Secrets → Actions, and a `dev`
GitHub Environment. Until it's set, the step is a green no-op so `main` stays green.

## Layout
```
app/
  main.py          # FastAPI factory + /livez /readyz
  core/config.py   # env-driven settings (pydantic-settings)
tests/             # smoke tests
```
