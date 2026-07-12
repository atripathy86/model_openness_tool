"""Neutral evidence generation for bounded PDF snapshots."""

from __future__ import annotations

import json
from hashlib import sha256

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    EvidenceClaim,
    EvidenceItem,
    PdfEvidenceReport,
    PdfSnapshot,
)
from model_openness_tool.semantic_detectors import extract_semantic_mentions

PDF_DETECTOR_VERSION = "bounded-pdf-v2"


def detect_pdf_evidence(snapshot: PdfSnapshot, catalog: FrameworkCatalog) -> PdfEvidenceReport:
    identity = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "claim": EvidenceClaim.ARTIFACT_EXISTS.value,
            "method": PDF_DETECTOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    existence = EvidenceItem(
        evidence_id=sha256(identity.encode()).hexdigest(),
        component_id=None,
        claim=EvidenceClaim.ARTIFACT_EXISTS,
        value=snapshot.final_url,
        source_url=snapshot.final_url,
        revision=snapshot.resolved_revision,
        path=snapshot.final_url,
        extraction_method=PDF_DETECTOR_VERSION,
        confidence=0.99,
    )
    mentions = extract_semantic_mentions(
        snapshot.text.content,
        snapshot_id=snapshot.snapshot_id,
        source_url=snapshot.final_url,
        revision=snapshot.resolved_revision,
        path=snapshot.text.path,
        extraction_method=PDF_DETECTOR_VERSION,
    )
    component_evidence = {item.component_id: item for item in mentions}
    findings = tuple(
        ComponentFinding(
            component_id=component.id,
            component_name=component.name,
            availability=(
                AvailabilityStatus.MENTIONED_ONLY
                if component.id in component_evidence
                else AvailabilityStatus.UNKNOWN
            ),
            confidence=(
                component_evidence[component.id].confidence
                if component.id in component_evidence
                else 0.0
            ),
            evidence_ids=(
                (component_evidence[component.id].evidence_id,)
                if component.id in component_evidence
                else ()
            ),
            rationale=(
                "The PDF text explicitly mentions this artifact, but does not prove that the "
                "artifact is released."
                if component.id in component_evidence
                else "The PDF is retrievable and has extractable text, but no deterministic "
                "rule proves that it is this specific MOF artifact."
            ),
        )
        for component in catalog.components
    )
    return PdfEvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=PDF_DETECTOR_VERSION,
        evidence=(existence, *mentions),
        findings=findings,
    )
