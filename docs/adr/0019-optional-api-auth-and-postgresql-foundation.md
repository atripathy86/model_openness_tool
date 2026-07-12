# ADR 0019: Optional API authentication and PostgreSQL foundation

## Status

Accepted

## Context

Phase 5 introduces an HTTP service and durable operational persistence. Local and
single-user deployments should not be forced to configure authentication, while exposed
deployments need a minimal bearer-token option. Production persistence must move toward
PostgreSQL without coupling domain logic to a particular deployment environment.

## Decision

- Add a FastAPI application with public health and readiness endpoints and versioned API
  routes.
- Leave authentication disabled when `MOT_API_BEARER_TOKEN` is unset or blank. When it is
  configured, require a bearer token on versioned routes and compare credentials using a
  constant-time operation. Keep health and readiness probes public.
- Configure PostgreSQL exclusively through `DATABASE_URL` and use SQLAlchemy 2 as the
  persistence boundary, psycopg as the PostgreSQL driver, and Alembic for migrations.
- Include a local Docker Compose PostgreSQL service with environment-overridable database,
  user, password, and port values plus a health check and named volume.
- Track `example.env` with all supported variables and keep the populated local `.env`
  ignored by Git. Blank values disable optional credentials.
- Permit the API to start without a database so `/health` remains useful, but report not
  ready until a configured database responds.
- Use FastAPI lifespan cleanup to dispose database connections.
- Defer durable job tables and worker behavior to the next Phase 5 slice.
- Do not introduce Prefect. Reconsider an external orchestrator only if scheduling,
  distributed execution, or infrastructure-specific work pools become demonstrated needs.

## Consequences

The service runs locally with minimal configuration and can enable a basic authentication
boundary without changing code. Bearer tokens supplied through one shared environment
value are not a replacement for user identity, token rotation, scopes, or OIDC; those may
be added later. PostgreSQL migrations and Compose establish a production-shaped storage
path, while readiness prevents an unconfigured database from being mistaken for an
operational service.
