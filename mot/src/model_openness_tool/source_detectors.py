"""High-precision component detection in pinned source repository manifests."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import quote

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    DatasetEvidenceReport,
    DocumentationEvidenceReport,
    EvidenceClaim,
    EvidenceItem,
    EvidenceReport,
    GitHubEvidenceReport,
    GitHubSnapshot,
    PaperEvidenceReport,
)

GITHUB_DETECTOR_VERSION = "github-manifest-v1"
CODE_SUFFIXES = frozenset({".ipynb", ".py", ".sh"})
DEPENDENCY_FILES = frozenset(
    {
        "environment.yml",
        "package-lock.json",
        "poetry.lock",
        "pyproject.toml",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
        "uv.lock",
    }
)
RULES = {
    7: re.compile(r"^(?:fine_?tune|pretrain|train|training)(?:_|$)"),
    8: re.compile(r"^(?:generate|generation|infer|inference|predict|prediction)(?:_|$)"),
    18: re.compile(r"^(?:benchmark|eval|evaluate|evaluation)(?:_|$)"),
    16: re.compile(r"^(?:data_?process|prepare_?data|preprocess|preprocessing)(?:_|$)"),
}


def detect_github_evidence(
    snapshot: GitHubSnapshot,
    catalog: FrameworkCatalog,
) -> GitHubEvidenceReport:
    evidence: list[EvidenceItem] = []
    component_evidence: dict[int, list[EvidenceItem]] = {}

    for file in snapshot.files:
        path = PurePosixPath(file.path.casefold())
        if any(part in {"test", "tests"} for part in path.parts):
            continue
        component_ids: set[int] = set()
        if path.name in DEPENDENCY_FILES:
            component_ids.add(22)
        if path.suffix in CODE_SUFFIXES:
            if path.name in {"model.py", "modeling.py"} or (
                path.name.startswith("modeling_") and path.suffix == ".py"
            ):
                component_ids.add(9)
            for component_id, pattern in RULES.items():
                if pattern.search(path.stem):
                    component_ids.add(component_id)
        for component_id in sorted(component_ids):
            item = _github_evidence_item(snapshot, component_id, file.path)
            evidence.append(item)
            component_evidence.setdefault(component_id, []).append(item)

        if path.name in {"license", "license.md", "license.txt"}:
            evidence.append(
                _github_evidence_item(
                    snapshot,
                    None,
                    file.path,
                    claim=EvidenceClaim.LICENSE_FILE_EXISTS,
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
            rationale=(
                "Pinned GitHub file metadata matches a high-precision source artifact rule."
                if component_evidence.get(component.id)
                else "No high-confidence source artifact rule matched the GitHub manifest."
            ),
        )
        for component in catalog.components
    )
    return GitHubEvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=GITHUB_DETECTOR_VERSION,
        evidence=tuple(evidence),
        findings=findings,
    )


def merge_evidence_reports(
    primary: EvidenceReport,
    linked: tuple[
        GitHubEvidenceReport
        | DatasetEvidenceReport
        | PaperEvidenceReport
        | DocumentationEvidenceReport,
        ...,
    ],
) -> EvidenceReport:
    for report in linked:
        if report.catalog_sha256 != primary.catalog_sha256:
            raise ValueError("Cannot merge evidence produced with different component catalogs")

    all_evidence = {item.evidence_id: item for item in primary.evidence}
    finding_sets: dict[int, list[ComponentFinding]] = {}
    for finding in primary.findings:
        finding_sets.setdefault(finding.component_id, []).append(finding)
    for report in linked:
        all_evidence.update({item.evidence_id: item for item in report.evidence})
        for finding in report.findings:
            finding_sets.setdefault(finding.component_id, []).append(finding)

    merged_findings = []
    for primary_finding in primary.findings:
        candidates = finding_sets[primary_finding.component_id]
        present = [item for item in candidates if item.availability == AvailabilityStatus.PRESENT]
        mentioned = [
            item for item in candidates if item.availability == AvailabilityStatus.MENTIONED_ONLY
        ]
        selected = present or mentioned or [primary_finding]
        availability = (
            AvailabilityStatus.PRESENT
            if present
            else AvailabilityStatus.MENTIONED_ONLY
            if mentioned
            else primary_finding.availability
        )
        evidence_ids = tuple(
            dict.fromkeys(evidence_id for item in selected for evidence_id in item.evidence_ids)
        )
        merged_findings.append(
            ComponentFinding(
                component_id=primary_finding.component_id,
                component_name=primary_finding.component_name,
                availability=availability,
                confidence=max(item.confidence for item in selected),
                evidence_ids=evidence_ids,
                rationale=(
                    "Evidence was combined across the Hugging Face model and pinned linked sources."
                    if linked
                    else primary_finding.rationale
                ),
            )
        )

    detector_versions = "+".join(
        dict.fromkeys([primary.detector_version, *(report.detector_version for report in linked)])
    )
    return primary.model_copy(
        update={
            "detector_version": detector_versions,
            "evidence": tuple(all_evidence.values()),
            "findings": tuple(merged_findings),
        }
    )


def _github_evidence_item(
    snapshot: GitHubSnapshot,
    component_id: int | None,
    path: str,
    *,
    claim: EvidenceClaim = EvidenceClaim.ARTIFACT_EXISTS,
) -> EvidenceItem:
    identity = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "component": component_id,
            "claim": claim.value,
            "path": path,
            "method": GITHUB_DETECTOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return EvidenceItem(
        evidence_id=sha256(identity.encode()).hexdigest(),
        component_id=component_id,
        claim=claim,
        value=path,
        source_url=(
            f"https://github.com/{snapshot.repository}/blob/"
            f"{snapshot.resolved_revision}/{quote(path, safe='/')}"
        ),
        revision=snapshot.resolved_revision,
        path=path,
        extraction_method=GITHUB_DETECTOR_VERSION,
        confidence=0.95,
    )
