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

## Database & migrations
```bash
docker compose up -d postgres      # local Postgres 16 (see docker-compose.yml)
alembic upgrade head               # build the schema + seed cylinder types & super_admin
alembic downgrade base             # tear it all down (migrations are reversible)
```
Schema is defined as ORM models in `app/db/models.py` (14 v1 tables; `jobs` lands in Phase 0-F)
and built by the Alembic migrations in `migrations/versions/`. The DB URL is read from
`DATABASE_URL` (never from `alembic.ini`). The seed creates the Indane cylinder varieties and one
`super_admin` (`SEED_ADMIN_PHONE` / `SEED_ADMIN_PASSWORD` — **rotate the password after first login**).

## Async infrastructure (workers)
```bash
docker compose up -d postgres redis minio     # dependencies
# API:
uvicorn app.main:app --reload
# Worker (all queues; --pool=solo on Windows):
celery -A app.workers.celery_app worker -Q core,ml,ai --pool=solo
```
Background work runs on **Celery** over **Redis** with three bulkheaded queues — `core`
(live: exports/notifications), `ml` and `ai` (provisioned, empty until Future Work). Every
job gets a row in `jobs`; poll it via `GET /v1/jobs/{id}`. `POST /v1/jobs/ping` is a demo
round-trip. Analytics reads use the **read replica** session (`get_replica_db`, falls back to
primary locally). Generated files go to **S3-compatible object storage** (MinIO locally) via
pre-signed URLs (`app/core/storage.py`).

## API contract
`openapi.yaml` is the canonical contract (00-MAIN-PRD §7), exported from FastAPI and
committed. Regenerate it whenever the API changes:
```bash
python scripts/export_openapi.py
```
A contract snapshot test (`tests/test_openapi_contract.py`) fails if the committed spec
drifts from the app, so it stays accurate. The web app generates its typed client from this
file (see `ski-frontend`, orval).

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
