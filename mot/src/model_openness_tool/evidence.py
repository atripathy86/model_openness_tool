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


class EvidenceClaim(StrEnum):
    ARTIFACT_EXISTS = "artifact_exists"
    ARTIFACT_MENTIONED = "artifact_mentioned"
    LICENSE_DECLARED = "license_declared"


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
    files: tuple[RepositoryFile, ...]
    model_card: TextArtifact | None = None
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


class EvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: HuggingFaceSnapshot
    evidence: tuple[EvidenceItem, ...]
    findings: tuple[ComponentFinding, ...]


class CollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    access_status: AccessStatus
    error: str | None = None
    report: EvidenceReport | None = None
