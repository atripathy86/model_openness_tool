import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from model_openness_tool.evidence import EvidenceClaim, EvidenceItem
from model_openness_tool.llm_extraction import LlmExtractionReport, LlmUsage
from model_openness_tool.review_store import (
    ReviewDecision,
    ReviewStatus,
    ReviewStore,
)


def _report() -> LlmExtractionReport:
    return LlmExtractionReport(
        extraction_id="extraction",
        source_url="https://docs.example.com/model",
        source_revision="sha256:source",
        source_content_sha256="content",
        source_truncated=False,
        provider="openai-compatible",
        endpoint="http://provider.invalid/v1",
        model="test-model",
        prompt_version="prompt-v1",
        extractor_version="extractor-v1",
        created_at=datetime(2026, 7, 12, tzinfo=UTC),
        duration_ms=100,
        usage=LlmUsage(total_tokens=10),
        evidence=(
            EvidenceItem(
                evidence_id="evidence-1",
                component_id=7,
                claim=EvidenceClaim.ARTIFACT_MENTIONED,
                value="training code",
                source_url="https://docs.example.com/model",
                revision="sha256:source",
                path="doc#line-1",
                extraction_method="llm",
                confidence=0.9,
                excerpt="training code",
            ),
        ),
        rejected=(),
    )


def test_import_is_idempotent_and_decisions_are_append_only(tmp_path: Path) -> None:
    timestamps = iter(
        (
            datetime(2026, 7, 12, 1, tzinfo=UTC),
            datetime(2026, 7, 12, 2, tzinfo=UTC),
            datetime(2026, 7, 12, 3, tzinfo=UTC),
            datetime(2026, 7, 12, 4, tzinfo=UTC),
        )
    )
    event_ids = iter(("event-1", "event-2"))
    store = ReviewStore(
        tmp_path / "review.db",
        clock=lambda: next(timestamps),
        event_id_factory=lambda: next(event_ids),
    )

    imported = store.import_report(_report())
    repeated = store.import_report(_report())
    accepted = store.append_decision(
        "evidence-1",
        decision=ReviewDecision.ACCEPT,
        reviewer="reviewer@example.com",
        reason="Citation and component mapping verified.",
    )
    rejected = store.append_decision(
        "evidence-1",
        decision=ReviewDecision.REJECT,
        reviewer="reviewer@example.com",
        reason="Superseding review found the claim too broad.",
    )

    assert imported.imported_count == 1
    assert repeated.imported_count == 0
    assert repeated.existing_count == 1
    assert accepted.event_id == "event-1"
    assert rejected.event_id == "event-2"
    items = store.list_items()
    assert len(items) == 1
    assert items[0].status == ReviewStatus.REJECTED
    assert items[0].latest_event == rejected
    assert store.list_items(ReviewStatus.PENDING) == ()

    with (
        sqlite3.connect(store.database) as connection,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        connection.execute("DELETE FROM review_events")


def test_decision_requires_existing_evidence_and_audit_fields(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "review.db")

    with pytest.raises(ValueError, match="Reviewer"):
        store.append_decision(
            "missing",
            decision=ReviewDecision.ACCEPT,
            reviewer=" ",
            reason="reason",
        )
    with pytest.raises(ValueError, match="reason"):
        store.append_decision(
            "missing",
            decision=ReviewDecision.ACCEPT,
            reviewer="reviewer",
            reason=" ",
        )
    with pytest.raises(ValueError, match="Unknown evidence ID"):
        store.append_decision(
            "missing",
            decision=ReviewDecision.ACCEPT,
            reviewer="reviewer",
            reason="reason",
        )
