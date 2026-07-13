"""Export reviewer-accepted evidence as conservative MOT-compatible YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from model_openness_tool.assessment import EvaluationRun
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import EvidenceClaim, EvidenceItem
from model_openness_tool.review_store import ReviewStatus, ReviewStore


class MotYamlExportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    output: str
    model_id: str
    component_count: int = Field(ge=0)
    evidence_ids: tuple[str, ...]


def load_evaluation_run(path: Path) -> EvaluationRun:
    return EvaluationRun.model_validate_json(path.read_text(encoding="utf-8"))


def evaluation_evidence(run: EvaluationRun) -> tuple[EvidenceItem, ...]:
    collected: list[EvidenceItem] = []
    if run.collection.report is not None:
        collected.extend(run.collection.report.evidence)
    for result in (
        *run.linked_github,
        *run.linked_datasets,
        *run.linked_papers,
        *run.linked_documentation,
    ):
        if result.evidence_report is not None:
            collected.extend(result.evidence_report.evidence)
    unique: dict[str, EvidenceItem] = {}
    for evidence in collected:
        existing = unique.get(evidence.evidence_id)
        if existing is not None and existing != evidence:
            raise ValueError(f"Conflicting evidence ID in evaluation run: {evidence.evidence_id}")
        unique[evidence.evidence_id] = evidence
    return tuple(unique.values())


def evaluation_review_source_id(run: EvaluationRun) -> str:
    if run.assessment is not None:
        return run.assessment.assessment_id
    if run.collection.report is not None:
        return run.collection.report.snapshot.snapshot_id
    return run.collection.model_id


def reviewable_evaluation_evidence(run: EvaluationRun) -> tuple[EvidenceItem, ...]:
    return tuple(item for item in evaluation_evidence(run) if item.component_id is not None)


def export_reviewed_mot_yaml(
    run: EvaluationRun,
    catalog: FrameworkCatalog,
    review_store: ReviewStore,
    output: Path,
) -> MotYamlExportResult:
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    run_evidence = {item.evidence_id: item for item in evaluation_evidence(run)}
    source_id = evaluation_review_source_id(run)
    accepted = tuple(
        item
        for item in review_store.list_items(ReviewStatus.ACCEPTED)
        if item.extraction_id == source_id and item.evidence_id in run_evidence
    )
    accepted_evidence = tuple(run_evidence[item.evidence_id] for item in accepted)
    existence = {
        item.component_id: item
        for item in accepted_evidence
        if item.component_id is not None and item.claim == EvidenceClaim.ARTIFACT_EXISTS
    }
    licenses: dict[int, list[EvidenceItem]] = {}
    for item in accepted_evidence:
        if item.component_id is not None and item.claim == EvidenceClaim.LICENSE_DECLARED:
            licenses.setdefault(item.component_id, []).append(item)

    components: list[dict[str, Any]] = []
    used_evidence_ids: list[str] = []
    for component in catalog.components:
        artifact = existence.get(component.id)
        if artifact is None:
            continue
        component_licenses = licenses.get(component.id, [])
        license_values = {item.value for item in component_licenses}
        if len(license_values) > 1:
            raise ValueError(f"Conflicting accepted licenses for component: {component.name}")
        record: dict[str, Any] = {
            "name": component.name,
            "description": component.description,
            "component_path": artifact.path,
        }
        used_evidence_ids.append(artifact.evidence_id)
        if component_licenses:
            license_evidence = component_licenses[0]
            record["license"] = license_evidence.value
            record["license_path"] = license_evidence.path
            used_evidence_ids.extend(item.evidence_id for item in component_licenses)
        else:
            record["license"] = "unlicensed"
        components.append(record)

    payload = {
        "framework": {
            "name": catalog.framework.name,
            "version": catalog.framework.version,
            "date": catalog.framework.date.isoformat(),
        },
        "release": {
            "name": run.collection.model_id,
            "version": (
                run.collection.report.snapshot.resolved_revision
                if run.collection.report is not None
                else ""
            ),
            "license": {},
            "origin": (
                run.collection.report.snapshot.source_url
                if run.collection.report is not None
                else ""
            ),
            "producer": "",
            "components": components,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return MotYamlExportResult(
        output=str(output),
        model_id=run.collection.model_id,
        component_count=len(components),
        evidence_ids=tuple(used_evidence_ids),
    )
