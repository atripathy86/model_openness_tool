# ADR 0017: SQLite review queue and append-only audit

## Status

Accepted

## Context

Citation-validated LLM proposals still require human review. Phase 4 needs a local,
testable queue before Phase 5 introduces PostgreSQL, authentication, and service APIs.
Review history must preserve superseded decisions rather than mutating prior audit data.

## Decision

- Use Python's standard SQLite support for the local Phase 4 review queue.
- Import only accepted, citation-validated evidence from an LLM extraction report.
  Imports are idempotent by evidence ID.
- Store immutable review items containing the extraction ID, component ID, complete
  evidence JSON, and queue timestamp.
- Record every accept or reject action as a new append-only event with a unique event ID,
  reviewer identity, required rationale, and timestamp.
- Derive current status from the latest event while retaining all earlier events.
- Install SQLite triggers that reject updates or deletes to review items and events.
- Keep the database local and ignored by Git. Provide JSON CLI output for import, list,
  and decision operations so the workflow can later move behind an API.
- Version the SQLite schema explicitly. Migrate the domain model to PostgreSQL/Alembic in
  Phase 5 without treating the local database file as production persistence.

## Consequences

Review behavior is auditable and usable from the CLI without introducing a service or
new runtime dependency. Local SQLite does not provide multi-user authentication,
authorization, durable backups, or distributed concurrency; those remain Phase 5
requirements. Reviewer identity is asserted by the CLI operator until authenticated API
boundaries exist.
