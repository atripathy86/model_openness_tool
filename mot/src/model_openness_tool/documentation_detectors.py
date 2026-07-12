"""Neutral evidence generation for bounded documentation snapshots."""

from __future__ import annotations

import json
from hashlib import sha256

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    DocumentationEvidenceReport,
    DocumentationSnapshot,
    EvidenceClaim,
    EvidenceItem,
)

DOCUMENTATION_DETECTOR_VERSION = "bounded-document-v1"


def detect_documentation_evidence(
    snapshot: DocumentationSnapshot,
    catalog: FrameworkCatalog,
) -> DocumentationEvidenceReport:
    identity = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "claim": EvidenceClaim.ARTIFACT_EXISTS.value,
            "method": DOCUMENTATION_DETECTOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence = EvidenceItem(
        evidence_id=sha256(identity.encode()).hexdigest(),
        component_id=None,
        claim=EvidenceClaim.ARTIFACT_EXISTS,
        value=snapshot.title or snapshot.final_url,
        source_url=snapshot.final_url,
        revision=snapshot.resolved_revision,
        path=snapshot.final_url,
        extraction_method=DOCUMENTATION_DETECTOR_VERSION,
        confidence=0.99,
    )
    findings = tuple(
        ComponentFinding(
            component_id=component.id,
            component_name=component.name,
            availability=AvailabilityStatus.UNKNOWN,
            confidence=0.0,
            rationale=(
                "The documentation page is retrievable, but no deterministic rule proves "
                "that it is this specific MOF artifact."
            ),
        )
        for component in catalog.components
    )
    return DocumentationEvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=DOCUMENTATION_DETECTOR_VERSION,
        evidence=(evidence,),
        findings=findings,
    )
