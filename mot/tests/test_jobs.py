from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from model_openness_tool.jobs import (
    EvaluationJobRequest,
    JobQueue,
    JobStatus,
)
from model_openness_tool.persistence import Base, Database


def _database(path: Path) -> Database:
    database = Database(f"sqlite+pysqlite:///{path}")
    Base.metadata.create_all(database.engine)
    return database


def test_job_lifecycle_retries_then_succeeds(tmp_path: Path) -> None:
    now = [datetime(2026, 7, 12, tzinfo=UTC)]
    database = _database(tmp_path / "jobs.db")
    queue = JobQueue(
        database,
        clock=lambda: now[0],
        job_id_factory=lambda: "job-1",
    )

    submitted = queue.submit(EvaluationJobRequest(model_id="example/model", max_attempts=3))
    claimed = queue.claim("worker-1")
    assert claimed is not None
    retried = queue.fail(claimed.job_id, "temporary source failure")

    assert submitted.status == JobStatus.QUEUED
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempts == 1
    assert retried.status == JobStatus.QUEUED
    assert retried.available_at == now[0] + timedelta(seconds=30)
    assert queue.claim("worker-2") is None

    now[0] += timedelta(seconds=30)
    claimed_again = queue.claim("worker-2")
    assert claimed_again is not None
    completed = queue.succeed(claimed_again.job_id, {"kind": "evaluation"})

    assert completed.status == JobStatus.SUCCEEDED
    assert completed.attempts == 2
    assert completed.result == {"kind": "evaluation"}
    listed = queue.list(JobStatus.SUCCEEDED)
    assert len(listed) == 1
    assert listed[0].job_id == completed.job_id
    assert listed[0].result == completed.result
    database.dispose()


def test_job_reaches_terminal_failure_and_validates_transitions(tmp_path: Path) -> None:
    database = _database(tmp_path / "jobs.db")
    queue = JobQueue(database, job_id_factory=lambda: "job-1")
    queue.submit(EvaluationJobRequest(model_id="example/model", max_attempts=1))
    claimed = queue.claim("worker")
    assert claimed is not None

    failed = queue.fail(claimed.job_id, "permanent failure")

    assert failed.status == JobStatus.FAILED
    assert failed.error == "permanent failure"
    assert queue.claim("worker") is None
    with pytest.raises(ValueError, match="not running"):
        queue.succeed(failed.job_id, {})
    with pytest.raises(ValueError, match="Worker ID"):
        queue.claim(" ")
    database.dispose()
