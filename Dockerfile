# ski-backend — single image for the API process (Celery worker process type arrives in Phase 0-F).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# Liveness probe target: GET /livez
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
