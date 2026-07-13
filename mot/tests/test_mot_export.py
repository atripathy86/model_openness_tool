from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from model_openness_tool.assessment import EvaluationRun
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AccessStatus,
    CollectionResult,
    ComponentFinding,
    EvidenceClaim,
    EvidenceItem,
    EvidenceReport,
    HuggingFaceSnapshot,
)
from model_openness_tool.model_yaml import load_model_yaml
from model_openness_tool.mot_export import (
    evaluation_evidence,
    evaluation_review_source_id,
    export_reviewed_mot_yaml,
)
from model_openness_tool.review_store import ReviewDecision, ReviewStore


def _run(evidence: tuple[EvidenceItem, ...]) -> EvaluationRun:
    report = EvidenceReport(
        snapshot=HuggingFaceSnapshot(
            snapshot_id="snapshot",
            model_id="example/model",
            source_url="https://huggingface.co/example/model/tree/abc",
            requested_revision="main",
            resolved_revision="abc",
            retrieved_at=datetime(2026, 7, 12, tzinfo=UTC),
            private=False,
            gated=False,
            pipeline_tag=None,
            tags=(),
            declared_license=None,
            files=(),
        ),
        evidence=evidence,
        findings=tuple(
            ComponentFinding(
                component_id=component_id,
                component_name=name,
                availability="unknown",
                confidence=0,
                rationale="fixture",
            )
            for component_id, name in ((7, "Training code"), (8, "Inference code"))
        ),
    )
    return EvaluationRun(
        collection=CollectionResult(
            model_id="example/model",
            access_status=AccessStatus.AVAILABLE,
            report=report,
        )
    )


def _evidence(
    evidence_id: str, component_id: int, claim: EvidenceClaim, value: str
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        component_id=component_id,
        claim=claim,
        value=value,
        source_url="https://github.com/example/model/tree/abc",
        revision="abc",
        path=value if claim == EvidenceClaim.ARTIFACT_EXISTS else "LICENSE",
        extraction_method="fixture",
        confidence=0.99,
    )


def test_export_includes_only_accepted_artifact_exists_and_component_license(
    tmp_path: Path, catalog: FrameworkCatalog
) -> None:
    evidence = (
        _evidence("training", 7, EvidenceClaim.ARTIFACT_EXISTS, "train.py"),
        _evidence("training-license", 7, EvidenceClaim.LICENSE_DECLARED, "Apache-2.0"),
        _evidence("inference", 8, EvidenceClaim.ARTIFACT_EXISTS, "inference.py"),
        _evidence("mention", 21, EvidenceClaim.ARTIFACT_MENTIONED, "evaluation results"),
    )
    run = _run(evidence)
    store = ReviewStore(tmp_path / "review.db")
    store.import_evidence(evaluation_review_source_id(run), evaluation_evidence(run))
    for evidence_id in ("training", "training-license", "mention"):
        store.append_decision(
            evidence_id,
            decision=ReviewDecision.ACCEPT,
            reviewer="reviewer@example.com",
            reason="Verified against the pinned source.",
        )

    output = tmp_path / "model.yml"
    result = export_reviewed_mot_yaml(run, catalog, store, output)
    payload = yaml.safe_load(output.read_text())

    assert result.component_count == 1
    assert result.evidence_ids == ("training", "training-license")
    assert payload["release"]["components"] == [
        {
            "name": "Training code",
            "description": "Code used for training the model",
            "component_path": "train.py",
            "license": "Apache-2.0",
            "license_path": "LICENSE",
        }
    ]
    parsed = load_model_yaml(output, catalog)
    assert parsed.included_component_ids == frozenset({7})
    assert parsed.component_licenses == {7: "Apache-2.0"}
    with pytest.raises(ValueError, match="already exists"):
        export_reviewed_mot_yaml(run, catalog, store, output)


def test_export_marks_accepted_artifact_without_accepted_license_unlicensed(
    tmp_path: Path, catalog: FrameworkCatalog
) -> None:
    artifact = _evidence("inference", 8, EvidenceClaim.ARTIFACT_EXISTS, "inference.py")
    run = _run((artifact,))
    store = ReviewStore(tmp_path / "review.db")
    store.import_evidence(evaluation_review_source_id(run), (artifact,))
    store.append_decision(
        artifact.evidence_id,
        decision=ReviewDecision.ACCEPT,
        reviewer="reviewer@example.com",
        reason="Verified against the pinned source.",
    )

    output = tmp_path / "model.yml"
    export_reviewed_mot_yaml(run, catalog, store, output)

    assert load_model_yaml(output, catalog).component_licenses == {8: None}
