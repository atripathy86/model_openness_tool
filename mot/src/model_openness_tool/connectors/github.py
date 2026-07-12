"""Revision-pinned, metadata-only GitHub repository collection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from model_openness_tool.catalog import load_catalog
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AccessStatus,
    GitHubCollectionResult,
    GitHubSnapshot,
    RepositoryFile,
)
from model_openness_tool.links import normalize_github_repository
from model_openness_tool.source_detectors import detect_github_evidence


@dataclass(frozen=True)
class GitHubRepositoryMetadata:
    identifier: str
    default_branch: str
    private: bool
    archived: bool


@dataclass(frozen=True)
class GitHubTreeEntry:
    path: str
    size: int
    blob_id: str


@dataclass(frozen=True)
class GitHubTree:
    entries: tuple[GitHubTreeEntry, ...]
    truncated: bool


class GitHubClient(Protocol):
    def get_repository(self, owner: str, repository: str) -> GitHubRepositoryMetadata: ...

    def resolve_commit(self, owner: str, repository: str, revision: str) -> str: ...

    def get_tree(self, owner: str, repository: str, revision: str) -> GitHubTree: ...


class GitHubSourceError(RuntimeError):
    def __init__(self, status: AccessStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class GitHubRestClient:
    """Typed boundary around the GitHub REST API."""

    def __init__(
        self,
        token: str | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "model-openness-tool",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if client is None:
            self._client = httpx.Client(
                base_url="https://api.github.com",
                headers=headers,
                timeout=20.0,
                follow_redirects=False,
            )
        else:
            client.headers.update(headers)
            self._client = client

    def get_repository(self, owner: str, repository: str) -> GitHubRepositoryMetadata:
        payload = self._get_json(f"/repos/{owner}/{repository}")
        default_branch = payload.get("default_branch")
        full_name = payload.get("full_name")
        if not isinstance(default_branch, str) or not isinstance(full_name, str):
            raise GitHubSourceError(AccessStatus.ERROR, "Invalid GitHub repository response")
        return GitHubRepositoryMetadata(
            identifier=full_name,
            default_branch=default_branch,
            private=bool(payload.get("private", False)),
            archived=bool(payload.get("archived", False)),
        )

    def resolve_commit(self, owner: str, repository: str, revision: str) -> str:
        encoded_revision = quote(revision, safe="")
        payload = self._get_json(f"/repos/{owner}/{repository}/commits/{encoded_revision}")
        commit_sha = payload.get("sha")
        if not isinstance(commit_sha, str):
            raise GitHubSourceError(AccessStatus.ERROR, "Invalid GitHub commit response")
        return commit_sha

    def get_tree(self, owner: str, repository: str, revision: str) -> GitHubTree:
        payload = self._get_json(
            f"/repos/{owner}/{repository}/git/trees/{revision}",
            params={"recursive": "1"},
        )
        raw_tree = payload.get("tree")
        if not isinstance(raw_tree, list):
            raise GitHubSourceError(AccessStatus.ERROR, "Invalid GitHub tree response")
        entries = []
        for raw_entry in raw_tree:
            if not isinstance(raw_entry, dict) or raw_entry.get("type") != "blob":
                continue
            path = raw_entry.get("path")
            blob_id = raw_entry.get("sha")
            size = raw_entry.get("size", 0)
            if not isinstance(path, str) or not isinstance(blob_id, str):
                continue
            entries.append(
                GitHubTreeEntry(
                    path=path,
                    size=size if isinstance(size, int) else 0,
                    blob_id=blob_id,
                )
            )
        return GitHubTree(
            entries=tuple(entries),
            truncated=bool(payload.get("truncated", False)),
        )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as error:
            raise GitHubSourceError(AccessStatus.ERROR, "GitHub API request failed") from error
        if response.status_code == 404:
            raise GitHubSourceError(
                AccessStatus.MISSING,
                "GitHub repository or revision was not found or is not accessible",
            )
        if response.status_code in {401, 403}:
            raise GitHubSourceError(
                AccessStatus.ERROR,
                "GitHub request was unauthorized, forbidden, or rate limited",
            )
        try:
            response.raise_for_status()
            payload: object = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise GitHubSourceError(AccessStatus.ERROR, "Invalid GitHub API response") from error
        if not isinstance(payload, dict):
            raise GitHubSourceError(AccessStatus.ERROR, "Invalid GitHub API response")
        return payload


class GitHubConnector:
    def __init__(
        self,
        client: GitHubClient,
        *,
        max_files: int = 100_000,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._max_files = max_files
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, repository_url: str, revision: str | None = None) -> GitHubCollectionResult:
        source = normalize_github_repository(repository_url)
        if source is None:
            return GitHubCollectionResult(
                repository_url=repository_url,
                access_status=AccessStatus.ERROR,
                error="Input is not a valid GitHub repository URL",
            )
        owner, repository = source.identifier.split("/", maxsplit=1)
        try:
            metadata = self._client.get_repository(owner, repository)
            requested = revision or metadata.default_branch
            resolved = self._client.resolve_commit(owner, repository, requested)
            tree = self._client.get_tree(owner, repository, resolved)
            if tree.truncated:
                raise GitHubSourceError(
                    AccessStatus.ERROR,
                    "GitHub returned a truncated repository tree",
                )
            files = self._files(tree.entries)
            snapshot_id = sha256(f"github:{metadata.identifier}:{resolved}".encode()).hexdigest()
            snapshot = GitHubSnapshot(
                snapshot_id=snapshot_id,
                repository=metadata.identifier,
                source_url=f"https://github.com/{metadata.identifier}/tree/{resolved}",
                requested_revision=revision,
                resolved_revision=resolved,
                default_branch=metadata.default_branch,
                retrieved_at=self._clock(),
                private=metadata.private,
                archived=metadata.archived,
                files=files,
            )
            return GitHubCollectionResult(
                repository_url=source.canonical_url,
                access_status=AccessStatus.AVAILABLE,
                snapshot=snapshot,
                evidence_report=detect_github_evidence(snapshot, self._catalog),
            )
        except GitHubSourceError as error:
            return GitHubCollectionResult(
                repository_url=source.canonical_url,
                access_status=error.status,
                error=str(error),
            )

    def _files(self, entries: Iterable[GitHubTreeEntry]) -> tuple[RepositoryFile, ...]:
        files = []
        for position, entry in enumerate(entries, start=1):
            if position > self._max_files:
                raise GitHubSourceError(
                    AccessStatus.ERROR,
                    f"Repository exceeds the {self._max_files}-file collection limit",
                )
            files.append(RepositoryFile(path=entry.path, size=entry.size, blob_id=entry.blob_id))
        return tuple(sorted(files, key=lambda item: item.path))
