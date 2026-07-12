"""Bounded, metadata-only arXiv paper collection."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

import httpx

from model_openness_tool.catalog import load_catalog
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import AccessStatus, PaperCollectionResult, PaperSnapshot
from model_openness_tool.links import normalize_arxiv_paper
from model_openness_tool.paper_detectors import detect_paper_evidence

ARXIV_ID_PATTERN = re.compile(
    r"^(?P<base>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7}))(?P<version>v\d+)?$",
    re.IGNORECASE,
)
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
ARXIV_NAMESPACE = "http://arxiv.org/schemas/atom"
MAX_ABSTRACT_CHARS = 20_000


@dataclass(frozen=True)
class ArxivPaperMetadata:
    paper_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    published_at: datetime
    updated_at: datetime
    declared_license: str | None


class ArxivClient(Protocol):
    def get_paper(self, paper_id: str) -> ArxivPaperMetadata: ...


class ArxivSourceError(RuntimeError):
    def __init__(self, status: AccessStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class ArxivApiClient:
    """Typed boundary around the public arXiv Atom API."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url="https://export.arxiv.org",
            headers={"User-Agent": "model-openness-tool/0.1 (metadata collection)"},
            timeout=20.0,
            follow_redirects=False,
        )

    def get_paper(self, paper_id: str) -> ArxivPaperMetadata:
        try:
            response = self._client.get("/api/query", params={"id_list": paper_id})
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ArxivSourceError(AccessStatus.ERROR, "arXiv API request failed") from error
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            raise ArxivSourceError(AccessStatus.ERROR, "Invalid arXiv API response") from error
        entry = root.find(f"{{{ATOM_NAMESPACE}}}entry")
        if entry is None:
            raise ArxivSourceError(AccessStatus.MISSING, "arXiv paper was not found")
        entry_id = _required_text(entry, "id").rsplit("/", maxsplit=1)[-1]
        match = ARXIV_ID_PATTERN.fullmatch(entry_id)
        if match is None:
            raise ArxivSourceError(AccessStatus.ERROR, "Invalid arXiv paper identifier")
        authors = tuple(
            _required_text(author, "name")
            for author in entry.findall(f"{{{ATOM_NAMESPACE}}}author")
        )
        license_element = entry.find(f"{{{ARXIV_NAMESPACE}}}license")
        declared_license = license_element.get("href") if license_element is not None else None
        abstract = _normalize_space(_required_text(entry, "summary"))
        if len(abstract) > MAX_ABSTRACT_CHARS:
            raise ArxivSourceError(
                AccessStatus.ERROR,
                f"arXiv abstract exceeds the {MAX_ABSTRACT_CHARS}-character limit",
            )
        return ArxivPaperMetadata(
            paper_id=entry_id,
            title=_normalize_space(_required_text(entry, "title")),
            authors=authors,
            abstract=abstract,
            published_at=_parse_datetime(_required_text(entry, "published")),
            updated_at=_parse_datetime(_required_text(entry, "updated")),
            declared_license=declared_license,
        )


class ArxivConnector:
    def __init__(
        self,
        client: ArxivClient,
        *,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, paper_url: str) -> PaperCollectionResult:
        source = normalize_arxiv_paper(paper_url)
        if source is None:
            return PaperCollectionResult(
                paper_url=paper_url,
                access_status=AccessStatus.ERROR,
                error="Input is not a supported arXiv paper ID or URL",
            )
        requested_id = source.identifier.removeprefix("arxiv:")
        requested_match = ARXIV_ID_PATTERN.fullmatch(requested_id)
        if requested_match is None:
            return PaperCollectionResult(
                paper_url=source.canonical_url,
                access_status=AccessStatus.ERROR,
                error="Input is not a valid arXiv paper identifier",
            )
        try:
            metadata = self._client.get_paper(requested_id)
            resolved_match = ARXIV_ID_PATTERN.fullmatch(metadata.paper_id)
            if resolved_match is None or resolved_match.group("version") is None:
                raise ArxivSourceError(
                    AccessStatus.ERROR,
                    "arXiv did not return a version-pinned paper identifier",
                )
            if resolved_match.group("base").casefold() != requested_match.group("base").casefold():
                raise ArxivSourceError(AccessStatus.ERROR, "arXiv returned a different paper")
            resolved_id = metadata.paper_id
            snapshot = PaperSnapshot(
                snapshot_id=sha256(f"arxiv:{resolved_id}".encode()).hexdigest(),
                paper_id=resolved_match.group("base"),
                source_url=f"https://arxiv.org/abs/{resolved_id}",
                requested_revision=requested_match.group("version"),
                resolved_revision=resolved_match.group("version"),
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
        except ArxivSourceError as error:
            return PaperCollectionResult(
                paper_url=source.canonical_url,
                access_status=error.status,
                error=str(error),
            )


def _required_text(element: ET.Element, name: str) -> str:
    child = element.find(f"{{{ATOM_NAMESPACE}}}{name}")
    if child is None or child.text is None or not child.text.strip():
        raise ArxivSourceError(AccessStatus.ERROR, "Invalid arXiv API response")
    return child.text.strip()


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ArxivSourceError(AccessStatus.ERROR, "Invalid arXiv API timestamp") from error


def _normalize_space(value: str) -> str:
    return " ".join(value.split())
