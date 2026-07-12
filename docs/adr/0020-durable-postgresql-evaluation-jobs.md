# ADR 0020: Durable PostgreSQL evaluation jobs

## Status

Accepted

## Context

Long-running model collection and evaluation should not execute inside API request
processes. Phase 5 needs durable, retryable work without introducing Prefect or another
orchestration service.

## Decision

- Store evaluation jobs in PostgreSQL with immutable job IDs, validated request JSON,
  structured result JSON, bounded errors, attempt limits, availability/lock timestamps,
  worker identity, and created/updated timestamps.
- Submit and inspect jobs through versioned API routes and equivalent CLI commands.
- Claim the oldest available queued job transactionally with `FOR UPDATE SKIP LOCKED`,
  allowing multiple workers to claim distinct jobs without a central coordinator.
- Increment attempts when a worker claims a job. On failure, requeue until the configured
  attempt limit with exponential delays of 30 seconds up to five minutes; then mark the
  job terminally failed.
- Provide `mot worker --once` for controlled execution and `mot worker --loop` for
  continuous polling. Store a supplied worker identity or a host/process default.
- Execute the existing revision-pinned Hugging Face collection and provisional evaluator
  in the worker. Inaccessible sources remain structured successful evaluation results;
  unexpected execution exceptions follow retry policy.
- Keep linked-resource expansion out of the first job request schema. Add bounded options
  only after job/result compatibility is established.
- Do not introduce Prefect. Reassess external orchestration if scheduling, distributed
  infrastructure provisioning, or more complex dependency graphs become requirements.

## Consequences

Jobs survive API and worker restarts, expose observable state, and support concurrent
workers using PostgreSQL primitives. Continuous workers still need process supervision,
and abandoned running jobs are not yet reclaimed automatically; stale-lock recovery and
operational metrics remain subsequent Phase 5 work.
