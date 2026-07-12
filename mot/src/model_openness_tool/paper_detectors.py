"""Conservative evidence detection for resolved research papers."""

from __future__ import annotations

import json
from hashlib import sha256

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    EvidenceClaim,
    EvidenceItem,
    PaperEvidenceReport,
    PaperSnapshot,
)

PAPER_DETECTOR_VERSION = "arxiv-metadata-v1"
RESEARCH_PAPER_COMPONENT_ID = 21


def detect_paper_evidence(
    snapshot: PaperSnapshot,
    catalog: FrameworkCatalog,
) -> PaperEvidenceReport:
    paper = _paper_evidence_item(
        snapshot,
        claim=EvidenceClaim.ARTIFACT_EXISTS,
        value=snapshot.title,
        confidence=0.99,
    )
    evidence = [paper]
    if snapshot.declared_license is not None:
        evidence.append(
            _paper_evidence_item(
                snapshot,
                claim=EvidenceClaim.LICENSE_DECLARED,
                value=snapshot.declared_license,
                confidence=0.98,
            )
        )
    findings = tuple(
        ComponentFinding(
            component_id=component.id,
            component_name=component.name,
            availability=(
                AvailabilityStatus.PRESENT
                if component.id == RESEARCH_PAPER_COMPONENT_ID
                else AvailabilityStatus.UNKNOWN
            ),
            confidence=0.99 if component.id == RESEARCH_PAPER_COMPONENT_ID else 0.0,
            evidence_ids=(paper.evidence_id,)
            if component.id == RESEARCH_PAPER_COMPONENT_ID
            else (),
            rationale=(
                "Resolved arXiv metadata proves that a research paper is publicly available."
                if component.id == RESEARCH_PAPER_COMPONENT_ID
                else "Paper metadata does not prove that this separate artifact is released."
            ),
        )
        for component in catalog.components
    )
    return PaperEvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=PAPER_DETECTOR_VERSION,
        evidence=tuple(evidence),
        findings=findings,
    )


def _paper_evidence_item(
    snapshot: PaperSnapshot,
    *,
    claim: EvidenceClaim,
    value: str,
    confidence: float,
) -> EvidenceItem:
    identity = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "component": RESEARCH_PAPER_COMPONENT_ID,
            "claim": claim.value,
            "value": value,
            "method": PAPER_DETECTOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return EvidenceItem(
        evidence_id=sha256(identity.encode()).hexdigest(),
        component_id=RESEARCH_PAPER_COMPONENT_ID,
        claim=claim,
        value=value,
        source_url=snapshot.source_url,
        revision=snapshot.resolved_revision,
        path="arXiv metadata",
        extraction_method=PAPER_DETECTOR_VERSION,
        confidence=confidence,
        excerpt=snapshot.abstract,
    )
