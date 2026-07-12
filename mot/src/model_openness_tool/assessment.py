"""Conservative evidence-to-assessment mapping for unreviewed model snapshots."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict

from model_openness_tool.domain import ContentType, FrameworkCatalog, ModelInput, ScoreReport
from model_openness_tool.evidence import (
    AvailabilityStatus,
    CollectionResult,
    ComponentFinding,
    DatasetCollectionResult,
    EvidenceClaim,
    EvidenceReport,
    GitHubCollectionResult,
)
from model_openness_tool.licenses import LicenseRegistry
from model_openness_tool.scoring import ModelEvaluator

ASSESSOR_VERSION = "provisional-v1"
DISCLAIMER = (
    "This automated assessment is provisional and is not legal advice. "
    "Human review is required before reporting a verified MOF classification."
)


class AssessmentKind(StrEnum):
    PROVISIONAL = "provisional"
    VERIFIED = "verified"


class SatisfactionStatus(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    REVIEW_REQUIRED = "review_required"


class LicenseIdentityStatus(StrEnum):
    RECOGNIZED = "recognized"
    ABSENT = "absent"
    CUSTOM_OR_UNKNOWN = "custom_or_unknown"


class LicenseApplicabilityStatus(StrEnum):
    AMBIGUOUS = "ambiguous"
    COMPONENT_SPECIFIC = "component_specific"
    NOT_EVALUATED = "not_evaluated"


class LicenseDecisionStatus(StrEnum):
    OPEN_TYPE_APPROPRIATE = "open_type_appropriate"
    OPEN_NOT_TYPE_APPROPRIATE = "open_not_type_appropriate"
    CLOSED = "closed"
    UNLICENSED = "unlicensed"
    REVIEW_REQUIRED = "review_required"


class ComponentDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    component_id: int
    component_name: str
    availability: AvailabilityStatus
    satisfaction: SatisfactionStatus
    license_identity: LicenseIdentityStatus
    license_applicability: LicenseApplicabilityStatus
    license_decision: LicenseDecisionStatus
    declared_license: str | None
    normalized_license: str | None
    type_appropriate: bool | None
    evidence_ids: tuple[str, ...]
    rationale: str


class ScoreSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    classification: int
    classification_label: str
    progress: dict[int, float]
    total_progress: float

    @classmethod
    def from_report(cls, report: ScoreReport) -> ScoreSummary:
        return cls(
            classification=report.classification,
            classification_label=report.classification_label,
            progress=report.progress,
            total_progress=report.total_progress,
        )


class ProvisionalAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: str
    kind: AssessmentKind
    assessor_version: str
    model_id: str
    resolved_revision: str
    framework_version: str
    catalog_version: str
    catalog_sha256: str
    license_catalog_sha256: str
    declared_license: str | None
    normalized_license: str | None
    license_identity: LicenseIdentityStatus
    license_evidence_ids: tuple[str, ...]
    decisions: tuple[ComponentDecision, ...]
    confirmed: ScoreSummary
    evidence_supported_potential: ScoreSummary
    review_required_component_ids: tuple[int, ...]
    warnings: tuple[str, ...]
    disclaimer: str = DISCLAIMER


class EvaluationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    collection: CollectionResult
    linked_github: tuple[GitHubCollectionResult, ...] = ()
    linked_datasets: tuple[DatasetCollectionResult, ...] = ()
    assessment: ProvisionalAssessment | None = None


class ProvisionalEvaluator:
    def __init__(self, catalog: FrameworkCatalog, licenses: LicenseRegistry) -> None:
        self.catalog = catalog
        self.licenses = licenses
        self.scorer = ModelEvaluator(catalog, licenses)

    def assess(self, report: EvidenceReport) -> ProvisionalAssessment:
        declared_license = report.snapshot.declared_license
        normalized_license = (
            self.licenses.normalize(declared_license) if declared_license is not None else None
        )
        if declared_license is None:
            identity = LicenseIdentityStatus.ABSENT
        elif normalized_license is None:
            identity = LicenseIdentityStatus.CUSTOM_OR_UNKNOWN
        else:
            identity = LicenseIdentityStatus.RECOGNIZED

        findings = {finding.component_id: finding for finding in report.findings}
        decisions = tuple(
            self._decision_from_report(
                report=report,
                finding=(
                    findings.get(component.id)
                    or ComponentFinding(
                        component_id=component.id,
                        component_name=component.name,
                        availability=AvailabilityStatus.UNKNOWN,
                        confidence=0.0,
                        rationale="The evidence report has no finding for this catalog component.",
                    )
                ),
                global_declared_license=declared_license,
                global_normalized_license=normalized_license,
                global_identity=identity,
            )
            for component in self.catalog.components
        )
        confirmed_ids = frozenset(
            decision.component_id
            for decision in decisions
            if decision.satisfaction == SatisfactionStatus.SATISFIED
        )
        potential_ids = frozenset(
            decision.component_id
            for decision in decisions
            if decision.availability == AvailabilityStatus.PRESENT
            and decision.normalized_license is not None
            and self.licenses.is_open(decision.normalized_license)
        )
        global_licenses: dict[str, str | None] = (
            {"distribution": normalized_license} if normalized_license is not None else {}
        )
        confirmed = self.scorer.score(
            ModelInput(
                name=report.snapshot.model_id,
                included_component_ids=confirmed_ids,
                global_licenses=global_licenses,
                component_licenses={
                    decision.component_id: decision.normalized_license
                    for decision in decisions
                    if decision.component_id in confirmed_ids
                },
            )
        )
        potential = self.scorer.score(
            ModelInput(
                name=report.snapshot.model_id,
                included_component_ids=potential_ids,
                global_licenses=global_licenses,
                component_licenses={
                    decision.component_id: decision.normalized_license
                    for decision in decisions
                    if decision.component_id in potential_ids
                },
            )
        )
        license_evidence_ids = tuple(
            item.evidence_id
            for item in report.evidence
            if item.claim in {EvidenceClaim.LICENSE_DECLARED, EvidenceClaim.LICENSE_FILE_EXISTS}
        )
        warnings = list(report.snapshot.warnings)
        if report.catalog_sha256 and report.catalog_sha256 != self.catalog.catalog_sha256:
            warnings.append(
                "The evidence report used a different component catalog and requires review."
            )
        if declared_license is not None:
            warnings.append(
                "The declared model license has ambiguous component scope and requires review."
            )
        assessment_id = self._assessment_id(report)
        return ProvisionalAssessment(
            assessment_id=assessment_id,
            kind=AssessmentKind.PROVISIONAL,
            assessor_version=ASSESSOR_VERSION,
            model_id=report.snapshot.model_id,
            resolved_revision=report.snapshot.resolved_revision,
            framework_version=self.catalog.framework.version,
            catalog_version=self.catalog.catalog_version,
            catalog_sha256=self.catalog.catalog_sha256,
            license_catalog_sha256=self.licenses.catalog_sha256,
            declared_license=declared_license,
            normalized_license=normalized_license,
            license_identity=identity,
            license_evidence_ids=license_evidence_ids,
            decisions=decisions,
            confirmed=ScoreSummary.from_report(confirmed),
            evidence_supported_potential=ScoreSummary.from_report(potential),
            review_required_component_ids=tuple(
                decision.component_id
                for decision in decisions
                if decision.satisfaction == SatisfactionStatus.REVIEW_REQUIRED
            ),
            warnings=tuple(warnings),
        )

    def _decision_from_report(
        self,
        *,
        report: EvidenceReport,
        finding: ComponentFinding,
        global_declared_license: str | None,
        global_normalized_license: str | None,
        global_identity: LicenseIdentityStatus,
    ) -> ComponentDecision:
        declared_items = [
            item
            for item in report.evidence
            if item.component_id == finding.component_id
            and item.claim == EvidenceClaim.LICENSE_DECLARED
        ]
        license_items = [
            item
            for item in report.evidence
            if item.component_id == finding.component_id
            and item.claim in {EvidenceClaim.LICENSE_DECLARED, EvidenceClaim.LICENSE_FILE_EXISTS}
        ]
        declared_values = tuple(dict.fromkeys(item.value for item in declared_items))
        declared_license: str | None
        normalized_license: str | None
        if len(declared_values) == 1:
            declared_license = declared_values[0]
            normalized_license = self.licenses.normalize(declared_license)
            identity = (
                LicenseIdentityStatus.RECOGNIZED
                if normalized_license is not None
                else LicenseIdentityStatus.CUSTOM_OR_UNKNOWN
            )
            applicability = LicenseApplicabilityStatus.COMPONENT_SPECIFIC
        elif len(declared_values) > 1:
            declared_license = "; ".join(declared_values)
            normalized_license = None
            identity = LicenseIdentityStatus.CUSTOM_OR_UNKNOWN
            applicability = LicenseApplicabilityStatus.COMPONENT_SPECIFIC
        else:
            declared_license = global_declared_license
            normalized_license = global_normalized_license
            identity = global_identity
            applicability = (
                LicenseApplicabilityStatus.AMBIGUOUS
                if declared_license is not None
                else LicenseApplicabilityStatus.NOT_EVALUATED
            )
        return self._decision(
            finding=finding,
            declared_license=declared_license,
            normalized_license=normalized_license,
            identity=identity,
            applicability=applicability,
            license_evidence_ids=tuple(item.evidence_id for item in license_items),
        )

    def _decision(
        self,
        *,
        finding: ComponentFinding,
        declared_license: str | None,
        normalized_license: str | None,
        identity: LicenseIdentityStatus,
        applicability: LicenseApplicabilityStatus,
        license_evidence_ids: tuple[str, ...],
    ) -> ComponentDecision:
        component = self.catalog.component(finding.component_id)
        evidence_ids = tuple(dict.fromkeys([*finding.evidence_ids, *license_evidence_ids]))
        if finding.availability == AvailabilityStatus.ABSENT:
            return ComponentDecision(
                component_id=component.id,
                component_name=component.name,
                availability=finding.availability,
                satisfaction=SatisfactionStatus.NOT_SATISFIED,
                license_identity=identity,
                license_applicability=LicenseApplicabilityStatus.NOT_EVALUATED,
                license_decision=LicenseDecisionStatus.REVIEW_REQUIRED,
                declared_license=declared_license,
                normalized_license=normalized_license,
                type_appropriate=None,
                evidence_ids=evidence_ids,
                rationale="The artifact is absent, so the MOF component is not satisfied.",
            )

        license_decision, type_appropriate = self._license_decision(
            normalized_license,
            component.content_type,
        )
        if finding.availability == AvailabilityStatus.PRESENT:
            rationale = (
                "The artifact is present, but license scope must be reviewed before it can be "
                "counted in a verified MOF classification."
            )
        elif finding.availability == AvailabilityStatus.MENTIONED_ONLY:
            rationale = (
                "The artifact is mentioned but its released availability and license "
                "require review."
            )
        else:
            rationale = "Artifact availability and licensing require review."
        return ComponentDecision(
            component_id=component.id,
            component_name=component.name,
            availability=finding.availability,
            satisfaction=SatisfactionStatus.REVIEW_REQUIRED,
            license_identity=identity,
            license_applicability=applicability,
            license_decision=license_decision,
            declared_license=declared_license,
            normalized_license=normalized_license,
            type_appropriate=type_appropriate,
            evidence_ids=evidence_ids,
            rationale=rationale,
        )

    def _license_decision(
        self,
        normalized_license: str | None,
        content_type: ContentType,
    ) -> tuple[LicenseDecisionStatus, bool | None]:
        if normalized_license is None:
            return LicenseDecisionStatus.REVIEW_REQUIRED, None
        type_appropriate = self.licenses.is_type_appropriate(normalized_license, content_type)
        if not self.licenses.is_open(normalized_license):
            return LicenseDecisionStatus.CLOSED, type_appropriate
        if type_appropriate:
            return LicenseDecisionStatus.OPEN_TYPE_APPROPRIATE, True
        return LicenseDecisionStatus.OPEN_NOT_TYPE_APPROPRIATE, False

    def _assessment_id(self, report: EvidenceReport) -> str:
        identity = json.dumps(
            {
                "snapshot": report.snapshot.snapshot_id,
                "catalog": self.catalog.catalog_sha256,
                "licenses": self.licenses.catalog_sha256,
                "assessor": ASSESSOR_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(identity.encode()).hexdigest()
