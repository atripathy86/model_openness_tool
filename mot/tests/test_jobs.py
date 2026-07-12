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


def test_heartbeat_refreshes_lease_and_stale_recovery_requeues(tmp_path: Path) -> None:
    now = [datetime(2026, 7, 12, tzinfo=UTC)]
    database = _database(tmp_path / "jobs.db")
    queue = JobQueue(database, clock=lambda: now[0], job_id_factory=lambda: "job-1")
    queue.submit(EvaluationJobRequest(model_id="example/model", max_attempts=2))
    claimed = queue.claim("worker-1")
    assert claimed is not None

    now[0] += timedelta(minutes=4)
    assert queue.heartbeat(claimed.job_id, "different-worker") is False
    assert queue.heartbeat(claimed.job_id, "worker-1") is True
    now[0] += timedelta(minutes=4)

    fresh = queue.recover_stale(timedelta(minutes=5))
    assert fresh.recovered_job_ids == ()

    now[0] += timedelta(minutes=2)
    recovered = queue.recover_stale(timedelta(minutes=5))
    job = queue.get(claimed.job_id)
    assert job is not None
    assert recovered.recovered_job_ids == ("job-1",)
    assert recovered.requeued_count == 1
    assert recovered.failed_count == 0
    assert job.status == JobStatus.QUEUED
    assert job.worker_id is None
    assert job.error == "Worker heartbeat expired; recovered stale running job"
    database.dispose()


def test_stale_recovery_fails_job_with_exhausted_attempts(tmp_path: Path) -> None:
    now = [datetime(2026, 7, 12, tzinfo=UTC)]
    database = _database(tmp_path / "jobs.db")
    queue = JobQueue(database, clock=lambda: now[0], job_id_factory=lambda: "job-1")
    queue.submit(EvaluationJobRequest(model_id="example/model", max_attempts=1))
    claimed = queue.claim("worker-1")
    assert claimed is not None

    now[0] += timedelta(hours=2)
    recovered = queue.recover_stale(timedelta(hours=1))
    job = queue.get(claimed.job_id)
    assert job is not None
    assert recovered.failed_count == 1
    assert recovered.requeued_count == 0
    assert job.status == JobStatus.FAILED
    assert job.worker_id is None
    with pytest.raises(ValueError, match="positive"):
        queue.recover_stale(timedelta(0))
    database.dispose()
