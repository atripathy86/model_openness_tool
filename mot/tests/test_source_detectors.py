from datetime import UTC, datetime

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AvailabilityStatus,
    ComponentFinding,
    EvidenceClaim,
    EvidenceReport,
    GitHubEvidenceReport,
    GitHubSnapshot,
    HuggingFaceSnapshot,
    RepositoryFile,
)
from model_openness_tool.source_detectors import (
    detect_github_evidence,
    merge_evidence_reports,
)


def _github_snapshot() -> GitHubSnapshot:
    return GitHubSnapshot(
        snapshot_id="github-snapshot",
        repository="example/model",
        source_url="https://github.com/example/model/tree/b",
        requested_revision=None,
        resolved_revision="b" * 40,
        default_branch="main",
        retrieved_at=datetime(2026, 7, 12, tzinfo=UTC),
        private=False,
        archived=False,
        declared_license="MIT",
        files=(
            RepositoryFile(path="model.py", size=10, blob_id="model"),
            RepositoryFile(path="scripts/train_model.py", size=10, blob_id="train"),
            RepositoryFile(path="inference.py", size=10, blob_id="inference"),
            RepositoryFile(path="evaluate.py", size=10, blob_id="evaluate"),
            RepositoryFile(path="prepare_data.py", size=10, blob_id="data"),
            RepositoryFile(path="requirements.txt", size=10, blob_id="requirements"),
            RepositoryFile(path="tests/train_model.py", size=10, blob_id="test"),
            RepositoryFile(path="LICENSE", size=10, blob_id="license"),
        ),
    )


def _finding(
    report: GitHubEvidenceReport | EvidenceReport,
    component_id: int,
) -> ComponentFinding:
    return next(item for item in report.findings if item.component_id == component_id)


def test_detects_high_precision_source_components(catalog: FrameworkCatalog) -> None:
    report = detect_github_evidence(_github_snapshot(), catalog)

    for component_id in (7, 8, 9, 16, 18, 22):
        assert _finding(report, component_id).availability == AvailabilityStatus.PRESENT
    training = _finding(report, 7)
    assert len(training.evidence_ids) == 2
    assert any(item.path == "LICENSE" for item in report.evidence)
    source_licenses = [
        item
        for item in report.evidence
        if item.claim == EvidenceClaim.LICENSE_DECLARED and item.component_id is not None
    ]
    assert {item.component_id for item in source_licenses} == {7, 8, 9, 16, 18, 22}
    assert {item.value for item in source_licenses} == {"MIT"}
    assert all(item.revision == "b" * 40 for item in report.evidence)


def test_merges_linked_source_evidence_without_promoting_unknowns(
    catalog: FrameworkCatalog,
) -> None:
    primary = EvidenceReport(
        snapshot=HuggingFaceSnapshot(
            snapshot_id="hf",
            model_id="example/model",
            source_url="https://huggingface.co/example/model/tree/a",
            requested_revision="main",
            resolved_revision="a" * 40,
            retrieved_at=datetime(2026, 7, 12, tzinfo=UTC),
            private=False,
            gated=False,
            pipeline_tag=None,
            tags=(),
            declared_license="mit",
            files=(),
        ),
        catalog_version=catalog.catalog_version,
        catalog_sha256=catalog.catalog_sha256,
        detector_version="hf",
        evidence=(),
        findings=tuple(
            ComponentFinding(
                component_id=component.id,
                component_name=component.name,
                availability=AvailabilityStatus.UNKNOWN,
                confidence=0.0,
                rationale="unknown",
            )
            for component in catalog.components
        ),
    )
    github = detect_github_evidence(_github_snapshot(), catalog)

    merged = merge_evidence_reports(primary, (github,))

    assert _finding(merged, 7).availability == AvailabilityStatus.PRESENT
    assert _finding(merged, 10).availability == AvailabilityStatus.UNKNOWN
    assert merged.detector_version == "hf+github-manifest-v2"
    assert len(merged.evidence) == len(github.evidence)
