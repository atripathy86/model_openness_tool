"""Bounded, metadata-only DOI paper collection through Crossref."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

import httpx

from model_openness_tool.catalog import load_catalog
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import AccessStatus, PaperCollectionResult, PaperSnapshot
from model_openness_tool.links import normalize_doi_paper
from model_openness_tool.paper_detectors import detect_paper_evidence

MAX_ABSTRACT_CHARS = 20_000
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class DoiPaperMetadata:
    doi: str
    source_url: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    published_at: datetime
    updated_at: datetime
    declared_license: str | None
    metadata_sha256: str


class DoiClient(Protocol):
    def get_work(self, doi: str) -> DoiPaperMetadata: ...


class DoiSourceError(RuntimeError):
    def __init__(self, status: AccessStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class CrossrefClient:
    """Typed boundary around Crossref works metadata."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url="https://api.crossref.org",
            headers={"User-Agent": "model-openness-tool/0.1 (metadata collection)"},
            timeout=20.0,
            follow_redirects=False,
        )

    def get_work(self, doi: str) -> DoiPaperMetadata:
        try:
            response = self._client.get(f"/works/{doi}")
            if response.status_code == 404:
                raise DoiSourceError(AccessStatus.MISSING, "DOI was not found")
            response.raise_for_status()
        except DoiSourceError:
            raise
        except httpx.HTTPError as error:
            raise DoiSourceError(AccessStatus.ERROR, "Crossref API request failed") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise DoiSourceError(AccessStatus.ERROR, "Invalid Crossref API response") from error
        message = payload.get("message")
        if not isinstance(message, dict):
            raise DoiSourceError(AccessStatus.ERROR, "Invalid Crossref API response")
        return _metadata_from_message(message)


class DoiConnector:
    def __init__(
        self,
        client: DoiClient,
        *,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, paper_url: str) -> PaperCollectionResult:
        source = normalize_doi_paper(paper_url)
        if source is None:
            return PaperCollectionResult(
                paper_url=paper_url,
                access_status=AccessStatus.ERROR,
                error="Input is not a supported DOI paper identifier or URL",
            )
        requested_doi = source.identifier.removeprefix("doi:")
        try:
            metadata = self._client.get_work(requested_doi)
            if metadata.doi.casefold() != requested_doi.casefold():
                raise DoiSourceError(AccessStatus.ERROR, "Crossref returned a different DOI")
            snapshot = PaperSnapshot(
                snapshot_id=sha256(
                    f"doi:{metadata.doi}:{metadata.metadata_sha256}".encode()
                ).hexdigest(),
                paper_id=metadata.doi,
                source_url=metadata.source_url,
                requested_revision=None,
                resolved_revision=f"sha256:{metadata.metadata_sha256}",
                retrieved_at=self._clock(),
                title=metadata.title,
                authors=metadata.authors,
                abstract=metadata.abstract,
                published_at=metadata.published_at,
                updated_at=metadata.updated_at,
                declared_license=metadata.declared_license,
            )
            return PaperCollectionResult(
                paper_url=source.canonical_url,
                access_status=AccessStatus.AVAILABLE,
                snapshot=snapshot,
                evidence_report=detect_paper_evidence(snapshot, self._catalog),
            )
        except DoiSourceError as error:
            return PaperCollectionResult(
                paper_url=source.canonical_url,
                access_status=error.status,
                error=str(error),
            )


def _metadata_from_message(message: dict[str, Any]) -> DoiPaperMetadata:
    doi = _required_string(message, "DOI")
    title = _first_string_or_none(message, "title") or doi
    abstract = _normalize_abstract(message.get("abstract"))
    if len(abstract) > MAX_ABSTRACT_CHARS:
        raise DoiSourceError(
            AccessStatus.ERROR,
            f"Crossref abstract exceeds the {MAX_ABSTRACT_CHARS}-character limit",
        )
    return DoiPaperMetadata(
        doi=doi,
        source_url=_source_url(message, doi),
        title=title,
        authors=_authors(message.get("author")),
        abstract=abstract,
        published_at=_date_parts(message, "published-print")
        or _date_parts(message, "published-online")
        or _date_parts(message, "published")
        or _crossref_timestamp(message, "created"),
        updated_at=_crossref_timestamp(message, "deposited")
        or _crossref_timestamp(message, "indexed")
        or _crossref_timestamp(message, "created"),
        declared_license=_declared_license(message.get("license")),
        metadata_sha256=_metadata_hash(message),
    )


def _required_string(message: dict[str, Any], key: str) -> str:
    value = message.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DoiSourceError(AccessStatus.ERROR, "Invalid Crossref API response")
    return value.strip()


def _first_string_or_none(message: dict[str, Any], key: str) -> str | None:
    value = message.get(key)
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = _normalize_space(item)
        if normalized:
            return normalized
    return None


def _source_url(message: dict[str, Any], doi: str) -> str:
    value = message.get("URL")
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return f"https://doi.org/{doi}"


def _authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    authors: list[str] = []
    for author in value:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        if isinstance(name, str) and name.strip():
            authors.append(_normalize_space(name))
            continue
        parts = [
            part.strip()
            for part in (author.get("given"), author.get("family"))
            if isinstance(part, str) and part.strip()
        ]
        if parts:
            authors.append(_normalize_space(" ".join(parts)))
    return tuple(authors)


def _normalize_abstract(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _normalize_space(html.unescape(HTML_TAG_PATTERN.sub(" ", value)))


def _date_parts(message: dict[str, Any], key: str) -> datetime | None:
    value = message.get(key)
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    try:
        year = int(parts[0][0])
        month = int(parts[0][1]) if len(parts[0]) > 1 else 1
        day = int(parts[0][2]) if len(parts[0]) > 2 else 1
        return datetime(year, month, day, tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        return None


def _crossref_timestamp(message: dict[str, Any], key: str) -> datetime:
    value = message.get(key)
    if not isinstance(value, dict):
        raise DoiSourceError(AccessStatus.ERROR, "Invalid Crossref API response")
    timestamp = value.get("date-time")
    if not isinstance(timestamp, str):
        raise DoiSourceError(AccessStatus.ERROR, "Invalid Crossref API response")
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise DoiSourceError(AccessStatus.ERROR, "Invalid Crossref API timestamp") from error


def _declared_license(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for license_record in value:
        if not isinstance(license_record, dict):
            continue
        url = license_record.get("URL")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _metadata_hash(message: dict[str, Any]) -> str:
    serialized = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(serialized.encode()).hexdigest()


def _normalize_space(value: str) -> str:
    return " ".join(value.split())
