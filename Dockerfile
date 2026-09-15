# Runtime únicamente: fastapi/uvicorn/jinja2/pydantic/anthropic (grupo por
# defecto de pyproject.toml). Los grupos "etl" y "dev" (pandas, docling,
# pytest) NUNCA entran a la imagen — el ETL corre local y sólo catalog.db
# viaja (doc 07 §1, CLAUDE.md).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Capa de dependencias: cachea mientras no cambien pyproject.toml/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Código de la app + catalog.db horneado (el único artefacto que produce el
# ETL local; nunca se genera dentro de la imagen).
COPY app ./app
COPY catalog.db ./catalog.db

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080

# Cloud Run inyecta $PORT1; nunca se hardcodea 8080 (doc 07 §5.3).
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT1:-8080}"]
