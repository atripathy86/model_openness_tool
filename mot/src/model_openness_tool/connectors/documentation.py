"""Bounded, content-addressed collection of linked documentation pages."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from model_openness_tool.catalog import load_catalog
from model_openness_tool.documentation_detectors import detect_documentation_evidence
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AccessStatus,
    DocumentationCollectionResult,
    DocumentationSnapshot,
    TextArtifact,
)

ALLOWED_CONTENT_TYPES = frozenset(
    {"application/xhtml+xml", "text/html", "text/markdown", "text/plain", "text/x-markdown"}
)
MAX_DOCUMENT_BYTES = 1_000_000
MAX_REDIRECTS = 3


@dataclass(frozen=True)
class DocumentResponse:
    status_code: int
    content_type: str
    content: bytes
    location: str | None = None


class DocumentationClient(Protocol):
    def fetch(self, url: str, max_bytes: int) -> DocumentResponse: ...


class DocumentationSourceError(RuntimeError):
    def __init__(self, status: AccessStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class DocumentationHttpClient:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": "model-openness-tool/0.1 (documentation collection)"},
            timeout=20.0,
            follow_redirects=False,
        )

    def fetch(self, url: str, max_bytes: int) -> DocumentResponse:
        try:
            with self._client.stream("GET", url) as response:
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise DocumentationSourceError(
                            AccessStatus.ERROR,
                            f"Documentation exceeds the {max_bytes}-byte collection limit",
                        )
                return DocumentResponse(
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type", ""),
                    content=bytes(content),
                    location=response.headers.get("location"),
                )
        except DocumentationSourceError:
            raise
        except httpx.HTTPError as error:
            raise DocumentationSourceError(
                AccessStatus.ERROR, "Documentation request failed"
            ) from error


class DocumentationConnector:
    def __init__(
        self,
        client: DocumentationClient,
        *,
        max_bytes: int = MAX_DOCUMENT_BYTES,
        max_redirects: int = MAX_REDIRECTS,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, documentation_url: str) -> DocumentationCollectionResult:
        try:
            current_url = _safe_documentation_url(documentation_url)
            current_url, response = self._fetch_redirects(current_url)
            content_type = response.content_type.split(";", maxsplit=1)[0].strip().casefold()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise DocumentationSourceError(
                    AccessStatus.ERROR,
                    f"Unsupported documentation content type: {content_type or 'missing'}",
                )
            raw_sha256 = sha256(response.content).hexdigest()
            decoded = response.content.decode("utf-8", errors="replace")
            title: str | None = None
            if content_type in {"text/html", "application/xhtml+xml"}:
                parser = _DocumentParser()
                parser.feed(decoded)
                text = parser.text
                title = parser.title
            else:
                text = decoded
            normalized_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            if not normalized_text:
                raise DocumentationSourceError(
                    AccessStatus.ERROR, "Documentation does not contain extractable text"
                )
            text_sha256 = sha256(normalized_text.encode()).hexdigest()
            snapshot = DocumentationSnapshot(
                snapshot_id=sha256(f"document:{current_url}:{raw_sha256}".encode()).hexdigest(),
                source_url=documentation_url,
                final_url=current_url,
                resolved_revision=f"sha256:{raw_sha256}",
                retrieved_at=self._clock(),
                content_type=content_type,
                title=title,
                text=TextArtifact(
                    path=current_url,
                    content_sha256=text_sha256,
                    content=normalized_text,
                ),
            )
            return DocumentationCollectionResult(
                documentation_url=documentation_url,
                access_status=AccessStatus.AVAILABLE,
                snapshot=snapshot,
                evidence_report=detect_documentation_evidence(snapshot, self._catalog),
            )
        except DocumentationSourceError as error:
            return DocumentationCollectionResult(
                documentation_url=documentation_url,
                access_status=error.status,
                error=str(error),
            )

    def _fetch_redirects(self, initial_url: str) -> tuple[str, DocumentResponse]:
        current_url = initial_url
        for redirect_count in range(self._max_redirects + 1):
            response = self._client.fetch(current_url, self._max_bytes)
            if response.status_code == 404:
                raise DocumentationSourceError(AccessStatus.MISSING, "Documentation was not found")
            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_count == self._max_redirects or response.location is None:
                    raise DocumentationSourceError(
                        AccessStatus.ERROR, "Documentation redirect limit exceeded"
                    )
                current_url = _safe_documentation_url(urljoin(current_url, response.location))
                continue
            if response.status_code in {401, 403}:
                raise DocumentationSourceError(
                    AccessStatus.ERROR, "Documentation is not publicly accessible"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise DocumentationSourceError(
                    AccessStatus.ERROR,
                    f"Documentation request returned HTTP {response.status_code}",
                )
            return current_url, response
        raise DocumentationSourceError(AccessStatus.ERROR, "Documentation redirect limit exceeded")


def _safe_documentation_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise DocumentationSourceError(AccessStatus.ERROR, "Invalid documentation URL")
    try:
        port = parsed.port
    except ValueError as error:
        raise DocumentationSourceError(
            AccessStatus.ERROR, "Unsafe documentation URL authority"
        ) from error
    if parsed.username is not None or parsed.password is not None or port not in {None, 80, 443}:
        raise DocumentationSourceError(AccessStatus.ERROR, "Unsafe documentation URL authority")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise DocumentationSourceError(AccessStatus.ERROR, "Local documentation URLs are blocked")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return value
    if not address.is_global:
        raise DocumentationSourceError(
            AccessStatus.ERROR, "Non-public documentation URLs are blocked"
        )
    return value


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    @property
    def title(self) -> str | None:
        title = " ".join(" ".join(self._title_parts).split())
        return title or None

    @property
    def text(self) -> str:
        return "\n".join(self._text_parts)
