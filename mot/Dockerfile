# Minimal image for the MOT FastAPI service and database migrations only.
#
# It deliberately installs just the runtime dependencies the API process
# imports (see docs/CLI.md). In particular, MinerU is NOT installed: it is an
# optional, externally provided inference service that MOT reaches over HTTP
# via MINERU_SERVER_URL, and the API process never calls it. When no MinerU
# server is configured or reachable, PDF collection automatically falls back
# to bounded pypdf extraction instead of failing; point MINERU_SERVER_URL at
# an external server for higher-quality extraction. Evidence collection and
# workers (`mot worker`) need the full dependency set and run outside this
# image (e.g. from a local uv environment).
FROM python:3.12-slim

WORKDIR /app

# Runtime dependencies for the API service, matching pyproject.toml bounds.
RUN pip install --no-cache-dir \
    "alembic>=1.16,<2" \
    "fastapi>=0.116,<1" \
    "pydantic>=2.11,<3" \
    "pyyaml>=6.0,<7" \
    "psycopg[binary]>=3.2,<4" \
    "sqlalchemy>=2.0,<3" \
    "uvicorn>=0.35,<1"

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations

# Install the package itself without dependencies; the minimal set above is
# everything the API and migrations import.
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000

# Apply migrations before serving; DATABASE_URL is provided by the environment.
CMD ["sh", "-c", "alembic upgrade head && uvicorn model_openness_tool.api:app_factory --factory --host 0.0.0.0 --port 8000"]
