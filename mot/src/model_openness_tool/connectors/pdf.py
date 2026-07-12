"""Bounded, content-addressed collection of public PDF documents."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from model_openness_tool.catalog import load_catalog
from model_openness_tool.connectors.documentation import (
    DocumentationClient,
    DocumentationSourceError,
    DocumentResponse,
    _safe_documentation_url,
)
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import (
    AccessStatus,
    PdfCollectionResult,
    PdfSnapshot,
    TextArtifact,
)
from model_openness_tool.pdf_detectors import detect_pdf_evidence

MAX_PDF_BYTES = 10_000_000
MAX_PDF_PAGES = 100
MAX_EXTRACTED_CHARS = 500_000
MAX_REDIRECTS = 3
PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


class PdfConnector:
    def __init__(
        self,
        client: DocumentationClient,
        *,
        max_bytes: int = MAX_PDF_BYTES,
        max_pages: int = MAX_PDF_PAGES,
        max_extracted_chars: int = MAX_EXTRACTED_CHARS,
        max_redirects: int = MAX_REDIRECTS,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._max_extracted_chars = max_extracted_chars
        self._max_redirects = max_redirects
        self._catalog = catalog or load_catalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(self, pdf_url: str) -> PdfCollectionResult:
        try:
            current_url = _safe_documentation_url(pdf_url)
            current_url, response = self._fetch_redirects(current_url)
            content_type = response.content_type.split(";", maxsplit=1)[0].strip().casefold()
            if content_type not in PDF_CONTENT_TYPES:
                raise DocumentationSourceError(
                    AccessStatus.ERROR,
                    f"Unsupported PDF content type: {content_type or 'missing'}",
                )
            raw_sha256 = sha256(response.content).hexdigest()
            text, page_count, extracted_page_count, warnings = self._extract_text(response.content)
            text_sha256 = sha256(text.encode()).hexdigest()
            snapshot = PdfSnapshot(
                snapshot_id=sha256(f"pdf:{current_url}:{raw_sha256}".encode()).hexdigest(),
                source_url=pdf_url,
                final_url=current_url,
                resolved_revision=f"sha256:{raw_sha256}",
                retrieved_at=self._clock(),
                content_type=content_type,
                page_count=page_count,
                extracted_page_count=extracted_page_count,
                text=TextArtifact(
                    path=current_url,
                    content_sha256=text_sha256,
                    content=text,
                ),
                warnings=warnings,
            )
            return PdfCollectionResult(
                pdf_url=pdf_url,
                access_status=AccessStatus.AVAILABLE,
                snapshot=snapshot,
                evidence_report=detect_pdf_evidence(snapshot, self._catalog),
            )
        except DocumentationSourceError as error:
            return PdfCollectionResult(
                pdf_url=pdf_url,
                access_status=error.status,
                error=str(error),
            )

    def _extract_text(self, content: bytes) -> tuple[str, int, int, tuple[str, ...]]:
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            page_count = len(reader.pages)
            if page_count == 0:
                raise DocumentationSourceError(AccessStatus.ERROR, "PDF does not contain pages")
            extracted_pages = min(page_count, self._max_pages)
            parts = [(reader.pages[index].extract_text() or "") for index in range(extracted_pages)]
        except (PdfReadError, ValueError, TypeError) as error:
            raise DocumentationSourceError(
                AccessStatus.ERROR, "Invalid or unreadable PDF"
            ) from error
        normalized = "\n".join(
            line.strip() for part in parts for line in part.splitlines() if line.strip()
        )
        if not normalized:
            raise DocumentationSourceError(
                AccessStatus.ERROR, "PDF does not contain extractable text"
            )
        warnings = []
        if page_count > self._max_pages:
            warnings.append(f"Text extraction limited to the first {self._max_pages} pages")
        if len(normalized) > self._max_extracted_chars:
            normalized = normalized[: self._max_extracted_chars]
            warnings.append(f"Extracted text truncated to {self._max_extracted_chars} characters")
        return normalized, page_count, extracted_pages, tuple(warnings)

    def _fetch_redirects(self, initial_url: str) -> tuple[str, DocumentResponse]:
        from urllib.parse import urljoin

        current_url = initial_url
        for redirect_count in range(self._max_redirects + 1):
            response = self._client.fetch(current_url, self._max_bytes)
            if response.status_code == 404:
                raise DocumentationSourceError(AccessStatus.MISSING, "PDF was not found")
            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_count == self._max_redirects or response.location is None:
                    raise DocumentationSourceError(
                        AccessStatus.ERROR, "PDF redirect limit exceeded"
                    )
                current_url = _safe_documentation_url(urljoin(current_url, response.location))
                continue
            if response.status_code in {401, 403}:
                raise DocumentationSourceError(AccessStatus.ERROR, "PDF is not publicly accessible")
            if response.status_code < 200 or response.status_code >= 300:
                raise DocumentationSourceError(
                    AccessStatus.ERROR, f"PDF request returned HTTP {response.status_code}"
                )
            return current_url, response
        raise DocumentationSourceError(AccessStatus.ERROR, "PDF redirect limit exceeded")
