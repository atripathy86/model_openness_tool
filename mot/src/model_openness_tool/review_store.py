"""Local SQLite review queue with append-only decision audit events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from model_openness_tool.evidence import EvidenceItem
from model_openness_tool.llm_extraction import LlmExtractionReport

SCHEMA_VERSION = 1


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class ReviewEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    evidence_id: str
    decision: ReviewDecision
    reviewer: str
    reason: str
    created_at: datetime


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    extraction_id: str
    component_id: int
    evidence: EvidenceItem
    queued_at: datetime
    status: ReviewStatus
    latest_event: ReviewEvent | None = None


class ReviewImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    extraction_id: str
    proposed_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    existing_count: int = Field(ge=0)


class ReviewListResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: str
    items: tuple[ReviewItem, ...]


class ReviewStore:
    def __init__(
        self,
        database: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.database = database
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_id_factory = event_id_factory or (lambda: str(uuid.uuid4()))

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_metadata(key, value)
                    VALUES ('schema_version', '1');

                CREATE TABLE IF NOT EXISTS review_items (
                    evidence_id TEXT PRIMARY KEY,
                    extraction_id TEXT NOT NULL,
                    component_id INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    queued_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    evidence_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject')),
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES review_items(evidence_id)
                );

                CREATE TRIGGER IF NOT EXISTS review_items_no_update
                BEFORE UPDATE ON review_items BEGIN
                    SELECT RAISE(ABORT, 'review items are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS review_items_no_delete
                BEFORE DELETE ON review_items BEGIN
                    SELECT RAISE(ABORT, 'review items are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS review_events_no_update
                BEFORE UPDATE ON review_events BEGIN
                    SELECT RAISE(ABORT, 'review events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS review_events_no_delete
                BEFORE DELETE ON review_events BEGIN
                    SELECT RAISE(ABORT, 'review events are append-only');
                END;
                """
            )

    def import_report(self, report: LlmExtractionReport) -> ReviewImportResult:
        self.initialize()
        queued_at = self._clock().isoformat()
        imported = 0
        with self._connect() as connection:
            for evidence in report.evidence:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO review_items(
                        evidence_id, extraction_id, component_id, evidence_json, queued_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        evidence.evidence_id,
                        report.extraction_id,
                        evidence.component_id,
                        evidence.model_dump_json(),
                        queued_at,
                    ),
                )
                imported += cursor.rowcount
        proposed = len(report.evidence)
        return ReviewImportResult(
            extraction_id=report.extraction_id,
            proposed_count=proposed,
            imported_count=imported,
            existing_count=proposed - imported,
        )

    def append_decision(
        self,
        evidence_id: str,
        *,
        decision: ReviewDecision,
        reviewer: str,
        reason: str,
    ) -> ReviewEvent:
        reviewer = reviewer.strip()
        reason = reason.strip()
        if not reviewer:
            raise ValueError("Reviewer must not be empty")
        if not reason:
            raise ValueError("Review reason must not be empty")
        self.initialize()
        event = ReviewEvent(
            event_id=self._event_id_factory(),
            evidence_id=evidence_id,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
            created_at=self._clock(),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO review_events(
                        event_id, evidence_id, decision, reviewer, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.evidence_id,
                        event.decision.value,
                        event.reviewer,
                        event.reason,
                        event.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Unknown evidence ID: {evidence_id}") from error
        return event

    def list_items(self, status: ReviewStatus | None = None) -> tuple[ReviewItem, ...]:
        self.initialize()
        query = """
            SELECT
                item.evidence_id,
                item.extraction_id,
                item.component_id,
                item.evidence_json,
                item.queued_at,
                event.event_id,
                event.decision,
                event.reviewer,
                event.reason,
                event.created_at
            FROM review_items AS item
            LEFT JOIN review_events AS event
              ON event.sequence = (
                SELECT latest.sequence
                FROM review_events AS latest
                WHERE latest.evidence_id = item.evidence_id
                ORDER BY latest.sequence DESC
                LIMIT 1
              )
            ORDER BY item.queued_at, item.evidence_id
        """
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        items = tuple(self._item(row) for row in rows)
        if status is None:
            return items
        return tuple(item for item in items if item.status == status)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _item(row: sqlite3.Row | tuple[object, ...]) -> ReviewItem:
        values = tuple(row)
        evidence = EvidenceItem.model_validate_json(str(values[3]))
        latest_event = None
        status = ReviewStatus.PENDING
        if values[5] is not None:
            decision = ReviewDecision(str(values[6]))
            latest_event = ReviewEvent(
                event_id=str(values[5]),
                evidence_id=str(values[0]),
                decision=decision,
                reviewer=str(values[7]),
                reason=str(values[8]),
                created_at=datetime.fromisoformat(str(values[9])),
            )
            status = (
                ReviewStatus.ACCEPTED
                if decision == ReviewDecision.ACCEPT
                else ReviewStatus.REJECTED
            )
        return ReviewItem(
            evidence_id=str(values[0]),
            extraction_id=str(values[1]),
            component_id=int(str(values[2])),
            evidence=evidence,
            queued_at=datetime.fromisoformat(str(values[4])),
            status=status,
            latest_event=latest_event,
        )


def load_extraction_report(path: Path) -> LlmExtractionReport:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("report"), dict):
        raise ValueError("LLM extraction result does not contain a report")
    return LlmExtractionReport.model_validate(payload["report"])
