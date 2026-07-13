# ADR 0022: Manual job retry and cursor pagination

## Status

Accepted

## Context

Operators need a controlled way to revisit terminal failures after correcting an external
condition. API clients also need to traverse growing job collections without duplicate or
missing records caused by numeric-offset movement.

## Decision

- Permit manual retry only for terminally failed jobs.
- Preserve the job identity and accumulated attempt count, clear terminal execution state,
  make the job immediately available, and grant exactly one additional attempt.
- Expose retry through `mot job-retry` and `POST /v1/jobs/{job_id}/retry`. Return conflict
  for jobs that are not terminally failed and not-found for unknown identifiers.
- Order job pages by creation timestamp and job ID, both descending. Encode the final
  ordering key as an opaque URL-safe cursor and request one extra row to determine whether
  another page exists.
- Return `next_cursor` beside API list items. Clients pass that value unchanged through the
  next request's `cursor` query parameter.

## Consequences

Retry is explicit and bounded rather than an unrestricted attempt reset. Cursor pages remain
stable when newer jobs arrive, while callers must treat cursors as opaque implementation
details. This does not yet provide a separate append-only operational event history.
