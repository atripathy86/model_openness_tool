"""Revision-pinned Hugging Face model collection without weight downloads."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import (
    GatedRepoError,
    HfHubHTTPError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
)
from huggingface_hub.hf_api import RepoFile

from model_openness_tool.catalog import load_catalog
from model_openness_tool.detectors import detect_repository_evidence
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AccessStatus,
    CollectionResult,
    HuggingFaceSnapshot,
    RepositoryFile,
    TextArtifact,
)


@dataclass(frozen=True)
class HubModelMetadata:
    model_id: str
    revision: str
    private: bool
    gated: bool
    pipeline_tag: str | None
    tags: tuple[str, ...]
    declared_license: str | None


@dataclass(frozen=True)
class HubFileMetadata:
    path: str
    size: int
    blob_id: str
    lfs_sha256: str | None = None
    lfs_size: int | None = None


class HubClient(Protocol):
    def get_model(self, model_id: str, revision: str | None) -> HubModelMetadata: ...

    def list_files(self, model_id: str, revision: str) -> Iterable[HubFileMetadata]: ...

    def download_file(self, model_id: str, revision: str, path: str, cache_dir: Path) -> Path: ...


class HubSourceError(RuntimeError):
    def __init__(self, status: AccessStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class HuggingFaceSdkClient:
    """Small typed adapter around huggingface_hub for easy mocking."""

    def __init__(self, token: str | None = None) -> None:
        self._api = HfApi(token=token)
        self._token = token

    def get_model(self, model_id: str, revision: str | None) -> HubModelMetadata:
        try:
            info = self._api.model_info(
                model_id,
                revision=revision,
                files_metadata=False,
                token=self._token,
            )
        except GatedRepoError as error:
            raise HubSourceError(AccessStatus.GATED, "Model repository is gated") from error
        except RepositoryNotFoundError as error:
            raise HubSourceError(
                AccessStatus.MISSING,
                "Model repository was not found or is not accessible",
            ) from error
        except RevisionNotFoundError as error:
            raise HubSourceError(
                AccessStatus.MISSING,
                "Requested revision was not found",
            ) from error
        except HfHubHTTPError as error:
            raise HubSourceError(AccessStatus.ERROR, "Hugging Face API request failed") from error

        if not info.sha:
            raise HubSourceError(AccessStatus.ERROR, "Hugging Face did not return a revision SHA")
        raw_license: object = (
            getattr(info.card_data, "license", None) if info.card_data is not None else None
        )
        declared_license = raw_license if isinstance(raw_license, str) else None
        return HubModelMetadata(
            model_id=info.id,
            revision=info.sha,
            private=bool(info.private),
            gated=bool(info.gated),
            pipeline_tag=info.pipeline_tag,
            tags=tuple(sorted(info.tags or [])),
            declared_license=declared_license,
        )

    def list_files(self, model_id: str, revision: str) -> Iterable[HubFileMetadata]:
        try:
            entries = self._api.list_repo_tree(
                model_id,
                recursive=True,
                expand=True,
                revision=revision,
                repo_type="model",
                token=self._token,
            )
            for entry in entries:
                if not isinstance(entry, RepoFile):
                    continue
                yield HubFileMetadata(
                    path=entry.path,
                    size=entry.size,
                    blob_id=entry.blob_id,
                    lfs_sha256=entry.lfs.sha256 if entry.lfs else None,
                    lfs_size=entry.lfs.size if entry.lfs else None,
                )
        except GatedRepoError as error:
            raise HubSourceError(AccessStatus.GATED, "Model repository tree is gated") from error
        except HfHubHTTPError as error:
            raise HubSourceError(
                AccessStatus.ERROR,
                "Could not list model repository files",
            ) from error

    def download_file(self, model_id: str, revision: str, path: str, cache_dir: Path) -> Path:
        try:
            downloaded = hf_hub_download(
                repo_id=model_id,
                filename=path,
                repo_type="model",
                revision=revision,
                cache_dir=cache_dir,
                token=self._token,
            )
        except GatedRepoError as error:
            raise HubSourceError(AccessStatus.GATED, f"File is gated: {path}") from error
        except HfHubHTTPError as error:
            raise HubSourceError(
                AccessStatus.ERROR,
                f"Could not download text file: {path}",
            ) from error
        if not isinstance(downloaded, str):
            raise HubSourceError(AccessStatus.ERROR, f"Unexpected download result for: {path}")
        return Path(downloaded)


class HuggingFaceConnector:
    def __init__(
        self,
        client: HubClient,
        cache_dir: Path,
        *,
        max_model_card_bytes: int = 1_000_000,
        max_files: int = 100_000,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._max_model_card_bytes = max_model_card_bytes
        self._max_files = max_files
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, model_id: str, revision: str | None = None) -> CollectionResult:
        try:
            metadata = self._client.get_model(model_id, revision)
            files = self._load_files(model_id, metadata.revision)
            model_card, warnings = self._load_model_card(metadata, files)
            source_url = f"https://huggingface.co/{metadata.model_id}/tree/{metadata.revision}"
            snapshot_id = sha256(
                f"huggingface:model:{metadata.model_id}:{metadata.revision}".encode()
            ).hexdigest()
            snapshot = HuggingFaceSnapshot(
                snapshot_id=snapshot_id,
                model_id=metadata.model_id,
                source_url=source_url,
                requested_revision=revision,
                resolved_revision=metadata.revision,
                retrieved_at=self._clock(),
                private=metadata.private,
                gated=metadata.gated,
                pipeline_tag=metadata.pipeline_tag,
                tags=metadata.tags,
                declared_license=metadata.declared_license,
                files=files,
                model_card=model_card,
                warnings=warnings,
            )
            return CollectionResult(
                model_id=model_id,
                access_status=AccessStatus.AVAILABLE,
                report=detect_repository_evidence(snapshot, self._catalog),
            )
        except HubSourceError as error:
            return CollectionResult(
                model_id=model_id,
                access_status=error.status,
                error=str(error),
            )

    def _load_files(self, model_id: str, revision: str) -> tuple[RepositoryFile, ...]:
        files: list[RepositoryFile] = []
        for position, item in enumerate(self._client.list_files(model_id, revision), start=1):
            if position > self._max_files:
                raise HubSourceError(
                    AccessStatus.ERROR,
                    f"Repository exceeds the {self._max_files}-file collection limit",
                )
            files.append(
                RepositoryFile(
                    path=item.path,
                    size=item.size,
                    blob_id=item.blob_id,
                    lfs_sha256=item.lfs_sha256,
                    lfs_size=item.lfs_size,
                )
            )
        return tuple(sorted(files, key=lambda item: item.path))

    def _load_model_card(
        self,
        metadata: HubModelMetadata,
        files: tuple[RepositoryFile, ...],
    ) -> tuple[TextArtifact | None, tuple[str, ...]]:
        readme = next((item for item in files if item.path.casefold() == "readme.md"), None)
        if readme is None:
            return None, ()
        if readme.size > self._max_model_card_bytes:
            return None, (f"README.md exceeds the {self._max_model_card_bytes}-byte limit",)

        try:
            path = self._client.download_file(
                metadata.model_id,
                metadata.revision,
                readme.path,
                self._cache_dir,
            )
            with path.open("rb") as handle:
                raw = handle.read(self._max_model_card_bytes + 1)
        except (HubSourceError, OSError) as error:
            return None, (f"Could not read README.md: {error}",)

        if len(raw) > self._max_model_card_bytes:
            return None, (f"README.md exceeds the {self._max_model_card_bytes}-byte limit",)

        return (
            TextArtifact(
                path=readme.path,
                content_sha256=sha256(raw).hexdigest(),
                content=raw.decode("utf-8", errors="replace"),
            ),
            (),
        )
