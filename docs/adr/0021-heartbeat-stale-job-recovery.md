# ADR 0021: Heartbeat-based stale-job recovery

## Status

Accepted

## Context

A worker can exit after claiming a durable evaluation job but before recording success or
failure. Without a lease, that job remains `running` indefinitely. A long model evaluation
must also not be mistaken for an abandoned job merely because it exceeds a fixed runtime.

## Decision

- Treat `locked_at` as a renewable running-job lease timestamp.
- Run a lightweight worker heartbeat thread while evaluation executes. It refreshes the
  lease only while the job remains running and owned by the same worker.
- Recover running jobs whose lease is older than a configurable positive duration. Requeue
  jobs with attempts remaining and terminally fail jobs whose attempt limit is exhausted.
- Perform recovery once when each worker starts and expose the same operation through
  `mot job-recover` for independent operations and maintenance workflows.
- Emit worker claim, completion, failure, recovery, and heartbeat-loss events as structured
  JSON logs on standard error. Keep command results as JSON on standard output.
- Keep recovery transactional and use `FOR UPDATE SKIP LOCKED` so concurrent recovery or
  worker activity does not require a centralized coordinator.

## Consequences

Abandoned jobs return to a deterministic state without penalizing legitimately long-running
evaluations that continue to heartbeat. Operators must configure the stale duration above
the heartbeat interval and supervise continuous worker processes externally. This provides
basic operational logs but intentionally defers a metrics backend and retention policy.
