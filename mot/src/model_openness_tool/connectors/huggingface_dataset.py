"""Revision-pinned Hugging Face dataset collection without data downloads."""

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
from model_openness_tool.dataset_detectors import detect_dataset_evidence
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AccessStatus,
    DatasetCollectionResult,
    DatasetSnapshot,
    LinkedSourceType,
    RepositoryFile,
    TextArtifact,
)
from model_openness_tool.links import normalize_linked_source


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    revision: str
    private: bool
    gated: bool
    tags: tuple[str, ...]
    declared_licenses: tuple[str, ...]


@dataclass(frozen=True)
class DatasetFileMetadata:
    path: str
    size: int
    blob_id: str
    lfs_sha256: str | None = None
    lfs_size: int | None = None


class DatasetClient(Protocol):
    def get_dataset(self, dataset_id: str, revision: str | None) -> DatasetMetadata: ...

    def list_files(self, dataset_id: str, revision: str) -> Iterable[DatasetFileMetadata]: ...

    def download_file(
        self,
        dataset_id: str,
        revision: str,
        path: str,
        cache_dir: Path,
    ) -> Path: ...


class DatasetSourceError(RuntimeError):
    def __init__(self, status: AccessStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class HuggingFaceDatasetSdkClient:
    def __init__(self, token: str | None = None) -> None:
        self._api = HfApi(token=token)
        self._token = token

    def get_dataset(self, dataset_id: str, revision: str | None) -> DatasetMetadata:
        try:
            info = self._api.dataset_info(dataset_id, revision=revision, token=self._token)
        except GatedRepoError as error:
            raise DatasetSourceError(AccessStatus.GATED, "Dataset repository is gated") from error
        except RepositoryNotFoundError as error:
            raise DatasetSourceError(
                AccessStatus.MISSING,
                "Dataset repository was not found or is not accessible",
            ) from error
        except RevisionNotFoundError as error:
            raise DatasetSourceError(
                AccessStatus.MISSING,
                "Requested dataset revision was not found",
            ) from error
        except HfHubHTTPError as error:
            raise DatasetSourceError(AccessStatus.ERROR, "Dataset API request failed") from error
        if not info.sha:
            raise DatasetSourceError(
                AccessStatus.ERROR, "Hugging Face did not return a dataset SHA"
            )
        raw_license: object = (
            getattr(info.card_data, "license", None) if info.card_data is not None else None
        )
        licenses: tuple[str, ...]
        if isinstance(raw_license, str):
            licenses = (raw_license,)
        elif isinstance(raw_license, list):
            licenses = tuple(item for item in raw_license if isinstance(item, str))
        else:
            licenses = ()
        return DatasetMetadata(
            dataset_id=info.id,
            revision=info.sha,
            private=bool(info.private),
            gated=bool(info.gated),
            tags=tuple(sorted(info.tags or [])),
            declared_licenses=licenses,
        )

    def list_files(self, dataset_id: str, revision: str) -> Iterable[DatasetFileMetadata]:
        try:
            entries = self._api.list_repo_tree(
                dataset_id,
                recursive=True,
                expand=True,
                revision=revision,
                repo_type="dataset",
                token=self._token,
            )
            for entry in entries:
                if not isinstance(entry, RepoFile):
                    continue
                yield DatasetFileMetadata(
                    path=entry.path,
                    size=entry.size,
                    blob_id=entry.blob_id,
                    lfs_sha256=entry.lfs.sha256 if entry.lfs else None,
                    lfs_size=entry.lfs.size if entry.lfs else None,
                )
        except GatedRepoError as error:
            raise DatasetSourceError(AccessStatus.GATED, "Dataset tree is gated") from error
        except HfHubHTTPError as error:
            raise DatasetSourceError(AccessStatus.ERROR, "Could not list dataset files") from error

    def download_file(
        self,
        dataset_id: str,
        revision: str,
        path: str,
        cache_dir: Path,
    ) -> Path:
        try:
            downloaded = hf_hub_download(
                repo_id=dataset_id,
                filename=path,
                repo_type="dataset",
                revision=revision,
                cache_dir=cache_dir,
                token=self._token,
            )
        except HfHubHTTPError as error:
            raise DatasetSourceError(
                AccessStatus.ERROR,
                f"Could not download dataset text file: {path}",
            ) from error
        if not isinstance(downloaded, str):
            raise DatasetSourceError(AccessStatus.ERROR, f"Unexpected download result: {path}")
        return Path(downloaded)


class HuggingFaceDatasetConnector:
    def __init__(
        self,
        client: DatasetClient,
        cache_dir: Path,
        *,
        max_files: int = 100_000,
        max_text_bytes: int = 1_000_000,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._max_files = max_files
        self._max_text_bytes = max_text_bytes
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, dataset_url: str, revision: str | None = None) -> DatasetCollectionResult:
        source = normalize_linked_source(dataset_url, discovered_in="direct-input")
        if source is None or source.source_type != LinkedSourceType.HUGGINGFACE_DATASET:
            return DatasetCollectionResult(
                dataset_url=dataset_url,
                access_status=AccessStatus.ERROR,
                error="Input is not a valid Hugging Face dataset URL",
            )
        try:
            metadata = self._client.get_dataset(source.identifier, revision)
            files = self._files(metadata)
            text_artifacts, warnings = self._text_artifacts(metadata, files)
            snapshot_id = sha256(
                f"huggingface:dataset:{metadata.dataset_id}:{metadata.revision}".encode()
            ).hexdigest()
            snapshot = DatasetSnapshot(
                snapshot_id=snapshot_id,
                dataset_id=metadata.dataset_id,
                source_url=(
                    f"https://huggingface.co/datasets/{metadata.dataset_id}/tree/"
                    f"{metadata.revision}"
                ),
                requested_revision=revision,
                resolved_revision=metadata.revision,
                retrieved_at=self._clock(),
                private=metadata.private,
                gated=metadata.gated,
                tags=metadata.tags,
                declared_licenses=metadata.declared_licenses,
                files=files,
                text_artifacts=text_artifacts,
                warnings=warnings,
            )
            return DatasetCollectionResult(
                dataset_url=source.canonical_url,
                access_status=AccessStatus.AVAILABLE,
                snapshot=snapshot,
                evidence_report=detect_dataset_evidence(snapshot, self._catalog),
            )
        except DatasetSourceError as error:
            return DatasetCollectionResult(
                dataset_url=source.canonical_url,
                access_status=error.status,
                error=str(error),
            )

    def _files(self, metadata: DatasetMetadata) -> tuple[RepositoryFile, ...]:
        files = []
        for position, item in enumerate(
            self._client.list_files(metadata.dataset_id, metadata.revision),
            start=1,
        ):
            if position > self._max_files:
                raise DatasetSourceError(
                    AccessStatus.ERROR,
                    f"Dataset exceeds the {self._max_files}-file collection limit",
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

    def _text_artifacts(
        self,
        metadata: DatasetMetadata,
        files: tuple[RepositoryFile, ...],
    ) -> tuple[tuple[TextArtifact, ...], tuple[str, ...]]:
        selected = [
            file
            for file in files
            if file.path.casefold() in {"readme.md", "license", "license.md", "license.txt"}
        ]
        artifacts = []
        warnings = []
        for file in selected:
            if file.size > self._max_text_bytes:
                warnings.append(f"{file.path} exceeds the bounded text-file limit")
                continue
            try:
                path = self._client.download_file(
                    metadata.dataset_id,
                    metadata.revision,
                    file.path,
                    self._cache_dir,
                )
                with path.open("rb") as handle:
                    raw = handle.read(self._max_text_bytes + 1)
            except (DatasetSourceError, OSError) as error:
                warnings.append(f"Could not read {file.path}: {error}")
                continue
            if len(raw) > self._max_text_bytes:
                warnings.append(f"{file.path} exceeds the bounded text-file limit")
                continue
            artifacts.append(
                TextArtifact(
                    path=file.path,
                    content_sha256=sha256(raw).hexdigest(),
                    content=raw.decode("utf-8", errors="replace"),
                )
            )
        return tuple(artifacts), tuple(warnings)
