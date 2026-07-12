"""Evidence and source snapshot contracts for automated collection."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AccessStatus(StrEnum):
    AVAILABLE = "available"
    GATED = "gated"
    PRIVATE = "private"
    MISSING = "missing"
    ERROR = "error"


class AvailabilityStatus(StrEnum):
    PRESENT = "present"
    MENTIONED_ONLY = "mentioned_only"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    INACCESSIBLE = "inaccessible"


class LinkedSourceType(StrEnum):
    GITHUB_REPOSITORY = "github_repository"
    HUGGINGFACE_DATASET = "huggingface_dataset"
    HUGGINGFACE_MODEL = "huggingface_model"
    PAPER = "paper"
    DOCUMENTATION = "documentation"


class EvidenceClaim(StrEnum):
    ARTIFACT_EXISTS = "artifact_exists"
    ARTIFACT_MENTIONED = "artifact_mentioned"
    LICENSE_DECLARED = "license_declared"
    LICENSE_FILE_EXISTS = "license_file_exists"


class RepositoryFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size: int = Field(ge=0)
    blob_id: str
    lfs_sha256: str | None = None
    lfs_size: int | None = Field(default=None, ge=0)


class TextArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    content_sha256: str
    content: str


class HuggingFaceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    model_id: str
    source_url: str
    requested_revision: str | None
    resolved_revision: str
    retrieved_at: datetime
    private: bool
    gated: bool
    pipeline_tag: str | None
    tags: tuple[str, ...]
    declared_license: str | None
    referenced_datasets: tuple[str, ...] = ()
    files: tuple[RepositoryFile, ...]
    model_card: TextArtifact | None = None
    text_artifacts: tuple[TextArtifact, ...] = ()
    warnings: tuple[str, ...] = ()


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    component_id: int | None
    claim: EvidenceClaim
    value: str
    source_url: str
    revision: str
    path: str
    extraction_method: str
    confidence: float = Field(ge=0, le=1)
    excerpt: str | None = None


class ComponentFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    component_id: int
    component_name: str
    availability: AvailabilityStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...] = ()
    rationale: str


class LinkedSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: LinkedSourceType
    identifier: str
    canonical_url: str
    discovered_in: str
    confidence: float = Field(ge=0, le=1)


class EvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: HuggingFaceSnapshot
    catalog_version: str = "unknown"
    catalog_sha256: str = ""
    detector_version: str = "unknown"
    evidence: tuple[EvidenceItem, ...]
    findings: tuple[ComponentFinding, ...]
    linked_sources: tuple[LinkedSource, ...] = ()


class CollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    access_status: AccessStatus
    error: str | None = None
    report: EvidenceReport | None = None


class GitHubSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    repository: str
    source_url: str
    requested_revision: str | None
    resolved_revision: str
    default_branch: str
    retrieved_at: datetime
    private: bool
    archived: bool
    declared_license: str | None = None
    files: tuple[RepositoryFile, ...]
    warnings: tuple[str, ...] = ()


class GitHubEvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: GitHubSnapshot
    catalog_version: str
    catalog_sha256: str
    detector_version: str
    evidence: tuple[EvidenceItem, ...]
    findings: tuple[ComponentFinding, ...]


class GitHubCollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_url: str
    access_status: AccessStatus
    error: str | None = None
    snapshot: GitHubSnapshot | None = None
    evidence_report: GitHubEvidenceReport | None = None


class DatasetSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    dataset_id: str
    source_url: str
    requested_revision: str | None
    resolved_revision: str
    retrieved_at: datetime
    private: bool
    gated: bool
    tags: tuple[str, ...]
    declared_licenses: tuple[str, ...]
    files: tuple[RepositoryFile, ...]
    text_artifacts: tuple[TextArtifact, ...] = ()
    warnings: tuple[str, ...] = ()


class DatasetEvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: DatasetSnapshot
    catalog_version: str
    catalog_sha256: str
    detector_version: str
    evidence: tuple[EvidenceItem, ...]
    findings: tuple[ComponentFinding, ...]


class DatasetCollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_url: str
    access_status: AccessStatus
    error: str | None = None
    snapshot: DatasetSnapshot | None = None
    evidence_report: DatasetEvidenceReport | None = None


class PaperSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    paper_id: str
    source_url: str
    requested_revision: str | None
    resolved_revision: str
    retrieved_at: datetime
    title: str
    authors: tuple[str, ...]
    abstract: str
    published_at: datetime
    updated_at: datetime
    declared_license: str | None = None


class PaperEvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: PaperSnapshot
    catalog_version: str
    catalog_sha256: str
    detector_version: str
    evidence: tuple[EvidenceItem, ...]
    findings: tuple[ComponentFinding, ...]


class PaperCollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    paper_url: str
    access_status: AccessStatus
    error: str | None = None
    snapshot: PaperSnapshot | None = None
    evidence_report: PaperEvidenceReport | None = None


class DocumentationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    source_url: str
    final_url: str
    resolved_revision: str
    retrieved_at: datetime
    content_type: str
    title: str | None = None
    text: TextArtifact
    warnings: tuple[str, ...] = ()


class DocumentationEvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: DocumentationSnapshot
    catalog_version: str
    catalog_sha256: str
    detector_version: str
    evidence: tuple[EvidenceItem, ...]
    findings: tuple[ComponentFinding, ...]


class DocumentationCollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    documentation_url: str
    access_status: AccessStatus
    error: str | None = None
    snapshot: DocumentationSnapshot | None = None
    evidence_report: DocumentationEvidenceReport | None = None
