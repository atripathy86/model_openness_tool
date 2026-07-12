from datetime import UTC, datetime

import pytest

from model_openness_tool.assessment import (
    AssessmentKind,
    ComponentDecision,
    LicenseApplicabilityStatus,
    LicenseDecisionStatus,
    LicenseIdentityStatus,
    ProvisionalAssessment,
    ProvisionalEvaluator,
    SatisfactionStatus,
)
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    EvidenceClaim,
    EvidenceItem,
    EvidenceReport,
    HuggingFaceSnapshot,
)
from model_openness_tool.licenses import LicenseRegistry


def _report(
    catalog: FrameworkCatalog,
    *,
    declared_license: str | None = "apache-2.0",
) -> EvidenceReport:
    availability = {
        10: AvailabilityStatus.PRESENT,
        13: AvailabilityStatus.PRESENT,
        14: AvailabilityStatus.ABSENT,
        21: AvailabilityStatus.MENTIONED_ONLY,
    }
    findings = tuple(
        ComponentFinding(
            component_id=component.id,
            component_name=component.name,
            availability=availability.get(component.id, AvailabilityStatus.UNKNOWN),
            confidence=0.9 if component.id in availability else 0.0,
            evidence_ids=(f"component-{component.id}",) if component.id in availability else (),
            rationale="fixture",
        )
        for component in catalog.components
    )
    evidence: tuple[EvidenceItem, ...] = ()
    if declared_license is not None:
        evidence = (
            EvidenceItem(
                evidence_id="license-evidence",
                component_id=None,
                claim=EvidenceClaim.LICENSE_DECLARED,
                value=declared_license,
                source_url="https://huggingface.co/example/model/blob/a/README.md#metadata",
                revision="a" * 40,
                path="README.md#metadata",
                extraction_method="fixture",
                confidence=0.99,
            ),
        )
    return EvidenceReport(
        snapshot=HuggingFaceSnapshot(
            snapshot_id="snapshot",
            model_id="example/model",
            source_url="https://huggingface.co/example/model/tree/a",
            requested_revision="main",
            resolved_revision="a" * 40,
            retrieved_at=datetime(2026, 7, 12, tzinfo=UTC),
            private=False,
            gated=False,
            pipeline_tag="text-generation",
            tags=(),
            declared_license=declared_license,
            files=(),
        ),
        evidence=evidence,
        findings=findings,
    )


def _decision(assessment: ProvisionalAssessment, component_id: int) -> ComponentDecision:
    return next(item for item in assessment.decisions if item.component_id == component_id)


def test_provisional_assessment_separates_confirmed_and_potential_scores(
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
) -> None:
    evaluator = ProvisionalEvaluator(catalog, license_registry)

    assessment = evaluator.assess(_report(catalog))

    assert assessment.kind == AssessmentKind.PROVISIONAL
    assert assessment.normalized_license == "Apache-2.0"
    assert assessment.license_identity == LicenseIdentityStatus.RECOGNIZED
    assert assessment.license_evidence_ids == ("license-evidence",)
    assert assessment.confirmed.classification == 0
    assert assessment.confirmed.progress == {1: 0.0, 2: 0.0, 3: 0.0}
    assert assessment.evidence_supported_potential.classification == 0
    assert assessment.evidence_supported_potential.progress[3] == pytest.approx(100 / 3)
    assert _decision(assessment, 10).license_decision == (
        LicenseDecisionStatus.OPEN_NOT_TYPE_APPROPRIATE
    )
    assert _decision(assessment, 13).license_decision == (
        LicenseDecisionStatus.OPEN_TYPE_APPROPRIATE
    )
    assert _decision(assessment, 14).satisfaction == SatisfactionStatus.NOT_SATISFIED
    assert _decision(assessment, 21).satisfaction == SatisfactionStatus.REVIEW_REQUIRED
    assert set(assessment.review_required_component_ids) == {
        component.id for component in catalog.components if component.id != 14
    }
    assert evaluator.assess(_report(catalog)).assessment_id == assessment.assessment_id


def test_missing_license_does_not_inflate_potential_score(
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
) -> None:
    assessment = ProvisionalEvaluator(catalog, license_registry).assess(
        _report(catalog, declared_license=None)
    )

    assert assessment.license_identity == LicenseIdentityStatus.ABSENT
    assert assessment.normalized_license is None
    assert assessment.evidence_supported_potential.progress == {1: 0.0, 2: 0.0, 3: 0.0}
    assert assessment.evidence_supported_potential.classification == 0


def test_component_specific_dataset_license_overrides_ambiguous_model_license(
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
) -> None:
    report = _report(catalog)
    report = report.model_copy(
        update={
            "evidence": (
                *report.evidence,
                EvidenceItem(
                    evidence_id="dataset-license",
                    component_id=15,
                    claim=EvidenceClaim.LICENSE_DECLARED,
                    value="cc-by-4.0",
                    source_url="https://huggingface.co/datasets/example/data/blob/d/README.md",
                    revision="d" * 40,
                    path="README.md#metadata",
                    extraction_method="fixture",
                    confidence=0.98,
                ),
            ),
            "findings": tuple(
                finding.model_copy(
                    update={
                        "availability": AvailabilityStatus.PRESENT,
                        "confidence": 0.98,
                        "evidence_ids": ("dataset-artifact",),
                    }
                )
                if finding.component_id == 15
                else finding
                for finding in report.findings
            ),
        }
    )

    assessment = ProvisionalEvaluator(catalog, license_registry).assess(report)
    decision = _decision(assessment, 15)

    assert decision.declared_license == "cc-by-4.0"
    assert decision.normalized_license == "CC-BY-4.0"
    assert decision.license_applicability == LicenseApplicabilityStatus.COMPONENT_SPECIFIC
    assert decision.license_decision == LicenseDecisionStatus.OPEN_NOT_TYPE_APPROPRIATE
    assert decision.satisfaction == SatisfactionStatus.REVIEW_REQUIRED
