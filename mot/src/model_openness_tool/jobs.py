"""Durable SQLAlchemy evaluation jobs and atomic worker claiming."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from model_openness_tool.persistence import Base, Database


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvaluationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    revision: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class EvaluationJobRow(Base):
    __tablename__ = "evaluation_jobs"
    __table_args__ = (Index("ix_evaluation_jobs_claim", "status", "available_at", "created_at"),)

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvaluationJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    status: JobStatus
    request: EvaluationJobRequest
    result: dict[str, Any] | None
    error: str | None
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    available_at: datetime
    locked_at: datetime | None
    worker_id: str | None
    created_at: datetime
    updated_at: datetime


class EvaluationJobSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    status: JobStatus
    model_id: str
    revision: str | None
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    result_available: bool
    error: str | None
    worker_id: str | None
    available_at: datetime
    created_at: datetime
    updated_at: datetime


class WorkerResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    processed: bool
    job_id: str | None = None
    status: JobStatus | None = None
    attempts: int | None = Field(default=None, ge=0)
    error: str | None = None


class RecoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    recovered_job_ids: tuple[str, ...]
    requeued_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class JobQueue:
    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] | None = None,
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._database = database
        self._clock = clock or (lambda: datetime.now(UTC))
        self._job_id_factory = job_id_factory or (lambda: str(uuid.uuid4()))

    def submit(self, request: EvaluationJobRequest) -> EvaluationJob:
        now = self._clock()
        row = EvaluationJobRow(
            job_id=self._job_id_factory(),
            status=JobStatus.QUEUED.value,
            request_json=request.model_dump(mode="json"),
            max_attempts=request.max_attempts,
            attempts=0,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        with self._database.session() as session:
            session.add(row)
        return _job(row)

    def get(self, job_id: str) -> EvaluationJob | None:
        with self._database.session() as session:
            row = session.get(EvaluationJobRow, job_id)
            return _job(row) if row is not None else None

    def list(
        self, status: JobStatus | None = None, *, limit: int = 100
    ) -> tuple[EvaluationJob, ...]:
        query = select(EvaluationJobRow).order_by(EvaluationJobRow.created_at.desc()).limit(limit)
        if status is not None:
            query = query.where(EvaluationJobRow.status == status.value)
        with self._database.session() as session:
            rows = session.scalars(query).all()
            return tuple(_job(row) for row in rows)

    def claim(self, worker_id: str) -> EvaluationJob | None:
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("Worker ID must not be empty")
        now = self._clock()
        with self._database.session() as session:
            row = session.scalar(
                select(EvaluationJobRow)
                .where(
                    EvaluationJobRow.status == JobStatus.QUEUED.value,
                    EvaluationJobRow.available_at <= now,
                )
                .order_by(EvaluationJobRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = JobStatus.RUNNING.value
            row.attempts += 1
            row.locked_at = now
            row.worker_id = worker_id
            row.updated_at = now
            session.flush()
            return _job(row)

    def succeed(self, job_id: str, result: dict[str, Any]) -> EvaluationJob:
        now = self._clock()
        with self._database.session() as session:
            row = _running_job(session, job_id)
            row.status = JobStatus.SUCCEEDED.value
            row.result_json = result
            row.error = None
            row.locked_at = None
            row.updated_at = now
            session.flush()
            return _job(row)

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        now = self._clock()
        with self._database.session() as session:
            row = session.get(EvaluationJobRow, job_id, with_for_update=True)
            if row is None or row.status != JobStatus.RUNNING.value or row.worker_id != worker_id:
                return False
            row.locked_at = now
            row.updated_at = now
            return True

    def recover_stale(self, stale_after: timedelta) -> RecoveryResult:
        if stale_after <= timedelta(0):
            raise ValueError("Stale duration must be positive")
        now = self._clock()
        cutoff = now - stale_after
        recovered = []
        requeued = 0
        failed = 0
        with self._database.session() as session:
            rows = session.scalars(
                select(EvaluationJobRow)
                .where(
                    EvaluationJobRow.status == JobStatus.RUNNING.value,
                    EvaluationJobRow.locked_at <= cutoff,
                )
                .order_by(EvaluationJobRow.locked_at)
                .with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                recovered.append(row.job_id)
                row.error = "Worker heartbeat expired; recovered stale running job"
                row.locked_at = None
                row.worker_id = None
                row.updated_at = now
                if row.attempts < row.max_attempts:
                    row.status = JobStatus.QUEUED.value
                    row.available_at = now
                    requeued += 1
                else:
                    row.status = JobStatus.FAILED.value
                    failed += 1
        return RecoveryResult(
            recovered_job_ids=tuple(recovered),
            requeued_count=requeued,
            failed_count=failed,
        )

    def fail(self, job_id: str, error: str) -> EvaluationJob:
        now = self._clock()
        with self._database.session() as session:
            row = _running_job(session, job_id)
            row.error = error[:2000]
            row.locked_at = None
            row.updated_at = now
            if row.attempts < row.max_attempts:
                row.status = JobStatus.QUEUED.value
                row.available_at = now + _retry_delay(row.attempts)
                row.worker_id = None
            else:
                row.status = JobStatus.FAILED.value
            session.flush()
            return _job(row)


def _running_job(session: Session, job_id: str) -> EvaluationJobRow:
    row = session.get(EvaluationJobRow, job_id, with_for_update=True)
    if row is None:
        raise ValueError(f"Unknown job ID: {job_id}")
    if row.status != JobStatus.RUNNING.value:
        raise ValueError(f"Job is not running: {job_id}")
    return row


def _retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 30 * (2 ** max(0, attempt - 1))))


def _job(row: EvaluationJobRow) -> EvaluationJob:
    return EvaluationJob(
        job_id=row.job_id,
        status=JobStatus(row.status),
        request=EvaluationJobRequest.model_validate(row.request_json),
        result=row.result_json,
        error=row.error,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        available_at=row.available_at,
        locked_at=row.locked_at,
        worker_id=row.worker_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def summarize_job(job: EvaluationJob) -> EvaluationJobSummary:
    return EvaluationJobSummary(
        job_id=job.job_id,
        status=job.status,
        model_id=job.request.model_id,
        revision=job.request.revision,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        result_available=job.result is not None,
        error=job.error,
        worker_id=job.worker_id,
        available_at=job.available_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
