"""Conservative evidence detection for pinned Hugging Face datasets."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import quote

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    DatasetEvidenceReport,
    DatasetSnapshot,
    EvidenceClaim,
    EvidenceItem,
)

DATASET_DETECTOR_VERSION = "huggingface-dataset-v1"
DATA_SUFFIXES = frozenset({".arrow", ".csv", ".gz", ".jsonl", ".parquet", ".tar", ".tsv", ".zip"})
MAX_DATA_FILE_EVIDENCE = 20


def detect_dataset_evidence(
    snapshot: DatasetSnapshot,
    catalog: FrameworkCatalog,
) -> DatasetEvidenceReport:
    evidence: list[EvidenceItem] = []
    component_evidence: dict[int, list[EvidenceItem]] = {}

    released_data_file_count = 0
    for file in snapshot.files:
        path = PurePosixPath(file.path.casefold())
        if path.suffix in DATA_SUFFIXES and path.name not in {"metadata.jsonl"}:
            released_data_file_count += 1
            if released_data_file_count <= MAX_DATA_FILE_EVIDENCE:
                item = _dataset_evidence_item(
                    snapshot,
                    component_id=15,
                    claim=EvidenceClaim.ARTIFACT_EXISTS,
                    value=file.path,
                    path=file.path,
                    confidence=0.98,
                )
                evidence.append(item)
                component_evidence.setdefault(15, []).append(item)
        if path.name == "readme.md":
            item = _dataset_evidence_item(
                snapshot,
                component_id=14,
                claim=EvidenceClaim.ARTIFACT_EXISTS,
                value=file.path,
                path=file.path,
                confidence=0.98,
            )
            evidence.append(item)
            component_evidence.setdefault(14, []).append(item)
        if path.name in {"license", "license.md", "license.txt"}:
            evidence.append(
                _dataset_evidence_item(
                    snapshot,
                    component_id=15,
                    claim=EvidenceClaim.LICENSE_FILE_EXISTS,
                    value=file.path,
                    path=file.path,
                    confidence=0.99,
                )
            )

    for license_id in snapshot.declared_licenses:
        evidence.append(
            _dataset_evidence_item(
                snapshot,
                component_id=15,
                claim=EvidenceClaim.LICENSE_DECLARED,
                value=license_id,
                path="README.md#metadata",
                confidence=0.98,
            )
        )

    findings = tuple(
        ComponentFinding(
            component_id=component.id,
            component_name=component.name,
            availability=(
                AvailabilityStatus.PRESENT
                if component_evidence.get(component.id)
                else AvailabilityStatus.UNKNOWN
            ),
            confidence=(
                max(item.confidence for item in component_evidence[component.id])
                if component_evidence.get(component.id)
                else 0.0
            ),
            evidence_ids=tuple(
                item.evidence_id for item in component_evidence.get(component.id, [])
            ),
            rationale=_finding_rationale(
                component.id,
                bool(component_evidence.get(component.id)),
                released_data_file_count,
            ),
        )
        for component in catalog.components
    )
    return DatasetEvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=DATASET_DETECTOR_VERSION,
        evidence=tuple(evidence),
        findings=findings,
    )


def _finding_rationale(
    component_id: int,
    is_present: bool,
    released_data_file_count: int,
) -> str:
    if not is_present:
        return "No released dataset artifact rule matched this dataset snapshot."
    if component_id == 15:
        cited_count = min(released_data_file_count, MAX_DATA_FILE_EVIDENCE)
        return (
            f"Pinned dataset metadata lists {released_data_file_count} released data "
            f"file(s); {cited_count} representative path(s) are cited."
        )
    return "Pinned dataset metadata proves that the released artifact exists."


def _dataset_evidence_item(
    snapshot: DatasetSnapshot,
    *,
    component_id: int,
    claim: EvidenceClaim,
    value: str,
    path: str,
    confidence: float,
) -> EvidenceItem:
    identity = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "component": component_id,
            "claim": claim.value,
            "path": path,
            "value": value,
            "method": DATASET_DETECTOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return EvidenceItem(
        evidence_id=sha256(identity.encode()).hexdigest(),
        component_id=component_id,
        claim=claim,
        value=value,
        source_url=(
            f"https://huggingface.co/datasets/{snapshot.dataset_id}/blob/"
            f"{snapshot.resolved_revision}/{quote(path, safe='/#')}"
        ),
        revision=snapshot.resolved_revision,
        path=path,
        extraction_method=DATASET_DETECTOR_VERSION,
        confidence=confidence,
    )
