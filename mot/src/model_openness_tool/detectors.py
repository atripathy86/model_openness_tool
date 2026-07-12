"""High-precision repository evidence detectors."""

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
    EvidenceClaim,
    EvidenceItem,
    EvidenceReport,
    HuggingFaceSnapshot,
    RepositoryFile,
)

DETECTOR_VERSION = "repository-files-v1"
WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".ckpt")
METADATA_NAMES = frozenset({"config.json", "model_config.json", "configuration.json"})
INFERENCE_STEMS = frozenset({"inference", "generate", "generation", "predict", "prediction"})


def detect_repository_evidence(
    snapshot: HuggingFaceSnapshot,
    catalog: FrameworkCatalog,
) -> EvidenceReport:
    evidence: list[EvidenceItem] = []
    component_evidence: dict[int, list[EvidenceItem]] = {}

    def add_file_evidence(component_id: int, file: RepositoryFile, confidence: float) -> None:
        item = _evidence_item(
            snapshot=snapshot,
            component_id=component_id,
            claim=EvidenceClaim.ARTIFACT_EXISTS,
            value=file.path,
            path=file.path,
            confidence=confidence,
        )
        evidence.append(item)
        component_evidence.setdefault(component_id, []).append(item)

    for file in snapshot.files:
        lower_path = file.path.casefold()
        name = PurePosixPath(lower_path).name
        stem = PurePosixPath(lower_path).stem

        if lower_path.endswith(WEIGHT_SUFFIXES):
            add_file_evidence(10, file, 0.99)
        if name in METADATA_NAMES:
            add_file_evidence(17, file, 0.98)
        if name == "readme.md":
            add_file_evidence(13, file, 0.99)
        if name == "modeling.py" or (name.startswith("modeling_") and name.endswith(".py")):
            add_file_evidence(9, file, 0.92)
        if stem in INFERENCE_STEMS and PurePosixPath(lower_path).suffix in {".py", ".ipynb"}:
            add_file_evidence(8, file, 0.88)

    if snapshot.declared_license:
        evidence.append(
            _evidence_item(
                snapshot=snapshot,
                component_id=None,
                claim=EvidenceClaim.LICENSE_DECLARED,
                value=snapshot.declared_license,
                path="README.md#metadata",
                confidence=0.98,
            )
        )

    for file in snapshot.files:
        if file.path.casefold() not in {"license", "license.md", "license.txt"}:
            continue
        evidence.append(
            _evidence_item(
                snapshot=snapshot,
                component_id=None,
                claim=EvidenceClaim.LICENSE_FILE_EXISTS,
                value=file.path,
                path=file.path,
                confidence=0.99,
            )
        )

    _add_model_card_mentions(snapshot, evidence, component_evidence)

    findings = []
    for component in catalog.components:
        items = component_evidence.get(component.id, [])
        present = [item for item in items if item.claim == EvidenceClaim.ARTIFACT_EXISTS]
        mentioned = [item for item in items if item.claim == EvidenceClaim.ARTIFACT_MENTIONED]
        if present:
            status = AvailabilityStatus.PRESENT
            selected = present
            rationale = "Repository file evidence matches a high-precision artifact rule."
        elif mentioned:
            status = AvailabilityStatus.MENTIONED_ONLY
            selected = mentioned
            rationale = (
                "The model card mentions the artifact, but release availability is unverified."
            )
        else:
            status = AvailabilityStatus.UNKNOWN
            selected = []
            rationale = (
                "No high-confidence evidence was found in the Hugging Face repository snapshot."
            )
        findings.append(
            ComponentFinding(
                component_id=component.id,
                component_name=component.name,
                availability=status,
                confidence=max((item.confidence for item in selected), default=0.0),
                evidence_ids=tuple(item.evidence_id for item in selected),
                rationale=rationale,
            )
        )

    return EvidenceReport(
        snapshot=snapshot,
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version=DETECTOR_VERSION,
        evidence=tuple(evidence),
        findings=tuple(findings),
    )


def _add_model_card_mentions(
    snapshot: HuggingFaceSnapshot,
    evidence: list[EvidenceItem],
    component_evidence: dict[int, list[EvidenceItem]],
) -> None:
    if snapshot.model_card is None:
        return
    content = snapshot.model_card.content
    mention_rules = (
        (21, re.compile(r"(?:arxiv\.org|doi\.org)", re.IGNORECASE), 0.85),
        (
            15,
            re.compile(
                r"(?:huggingface\.co/datasets/|^datasets?:)",
                re.IGNORECASE | re.MULTILINE,
            ),
            0.8,
        ),
        (11, re.compile(r"technical\s+report", re.IGNORECASE), 0.75),
        (12, re.compile(r"(?:evaluation\s+results|benchmark\s+results)", re.IGNORECASE), 0.7),
    )
    for component_id, pattern, confidence in mention_rules:
        match = pattern.search(content)
        if match is None:
            continue
        item = _evidence_item(
            snapshot=snapshot,
            component_id=component_id,
            claim=EvidenceClaim.ARTIFACT_MENTIONED,
            value=match.group(0),
            path=snapshot.model_card.path,
            confidence=confidence,
            excerpt=_excerpt(content, match.start(), match.end()),
        )
        evidence.append(item)
        component_evidence.setdefault(component_id, []).append(item)


def _evidence_item(
    *,
    snapshot: HuggingFaceSnapshot,
    component_id: int | None,
    claim: EvidenceClaim,
    value: str,
    path: str,
    confidence: float,
    excerpt: str | None = None,
) -> EvidenceItem:
    identity = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "component": component_id,
            "claim": claim.value,
            "path": path,
            "value": value,
            "method": DETECTOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    source_url = (
        f"https://huggingface.co/{snapshot.model_id}/blob/"
        f"{snapshot.resolved_revision}/{quote(path, safe='/#')}"
    )
    return EvidenceItem(
        evidence_id=sha256(identity.encode()).hexdigest(),
        component_id=component_id,
        claim=claim,
        value=value,
        source_url=source_url,
        revision=snapshot.resolved_revision,
        path=path,
        extraction_method=DETECTOR_VERSION,
        confidence=confidence,
        excerpt=excerpt,
    )


def _excerpt(content: str, start: int, end: int, radius: int = 100) -> str:
    excerpt = content[max(0, start - radius) : min(len(content), end + radius)]
    return " ".join(excerpt.split())
