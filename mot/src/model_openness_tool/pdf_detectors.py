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

PDF_DETECTOR_VERSION = "bounded-pdf-v1"


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
    evidence = EvidenceItem(
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
    findings = tuple(
        ComponentFinding(
            component_id=component.id,
            component_name=component.name,
            availability=AvailabilityStatus.UNKNOWN,
            confidence=0.0,
            rationale=(
                "The PDF is retrievable and has extractable text, but no deterministic rule "
                "proves that it is this specific MOF artifact."
            ),
        )
        for component in catalog.components
    )
    return PdfEvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=PDF_DETECTOR_VERSION,
        evidence=(evidence,),
        findings=findings,
    )
