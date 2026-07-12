"""Bounded PDF collection with injectable MinerU document extraction."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin

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
MINERU_TIMEOUT_SECONDS = 600
PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


class MinerUBackend(StrEnum):
    VLM_HTTP_CLIENT = "vlm-http-client"
    HYBRID_HTTP_CLIENT = "hybrid-http-client"


@dataclass(frozen=True)
class MinerUExtraction:
    markdown: str
    page_count: int
    extracted_page_count: int
    version: str
    backend: str
    warnings: tuple[str, ...] = ()


class PdfExtractor(Protocol):
    def extract(
        self,
        content: bytes,
        *,
        backend: MinerUBackend,
        server_url: str,
        max_pages: int,
        max_chars: int,
    ) -> MinerUExtraction: ...


class MinerUCliExtractor:
    """Run the uv-installed MinerU client without invoking a shell."""

    def __init__(
        self, *, executable: str = "mineru", timeout: int = MINERU_TIMEOUT_SECONDS
    ) -> None:
        self._executable = executable
        self._timeout = timeout

    def extract(
        self,
        content: bytes,
        *,
        backend: MinerUBackend,
        server_url: str,
        max_pages: int,
        max_chars: int,
    ) -> MinerUExtraction:
        if shutil.which(self._executable) is None:
            raise DocumentationSourceError(
                AccessStatus.ERROR, "MinerU CLI is not installed in the active uv environment"
            )
        with tempfile.TemporaryDirectory(prefix="mot-mineru-") as temporary:
            root = Path(temporary)
            input_path = root / "document.pdf"
            output_path = root / "output"
            input_path.write_bytes(content)
            command = [
                self._executable,
                "-p",
                str(input_path),
                "-o",
                str(output_path),
                "-b",
                backend.value,
                "-u",
                server_url,
                "--start",
                "0",
                "--end",
                str(max_pages - 1),
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired as error:
                raise DocumentationSourceError(
                    AccessStatus.ERROR,
                    f"MinerU extraction exceeded the {self._timeout}-second limit",
                ) from error
            if completed.returncode != 0:
                raise DocumentationSourceError(AccessStatus.ERROR, "MinerU extraction failed")
            extraction = _read_mineru_output(output_path, max_pages=max_pages, max_chars=max_chars)
            try:
                mineru_version = version("mineru")
            except PackageNotFoundError:
                mineru_version = "unknown"
            return MinerUExtraction(
                markdown=extraction.markdown,
                page_count=extraction.page_count,
                extracted_page_count=extraction.extracted_page_count,
                version=mineru_version,
                backend=backend.value,
                warnings=extraction.warnings,
            )


class PypdfExtractor:
    """Bounded lower-fidelity fallback when MinerU is unavailable."""

    def extract(
        self,
        content: bytes,
        *,
        backend: MinerUBackend,
        server_url: str,
        max_pages: int,
        max_chars: int,
    ) -> MinerUExtraction:
        del backend, server_url
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            page_count = len(reader.pages)
            if page_count == 0:
                raise DocumentationSourceError(AccessStatus.ERROR, "PDF does not contain pages")
            extracted_pages = min(page_count, max_pages)
            parts = [(reader.pages[index].extract_text() or "") for index in range(extracted_pages)]
        except (PdfReadError, ValueError, TypeError) as error:
            raise DocumentationSourceError(
                AccessStatus.ERROR, "Invalid or unreadable PDF"
            ) from error
        text = "\n".join(
            line.strip() for part in parts for line in part.splitlines() if line.strip()
        )
        if not text:
            raise DocumentationSourceError(
                AccessStatus.ERROR, "PDF does not contain fallback-extractable text"
            )
        warnings = []
        if page_count > max_pages:
            warnings.append(f"Fallback text extraction limited to the first {max_pages} pages")
        if len(text) > max_chars:
            text = text[:max_chars]
            warnings.append(f"Fallback text truncated to {max_chars} characters")
        try:
            pypdf_version = version("pypdf")
        except PackageNotFoundError:
            pypdf_version = "unknown"
        return MinerUExtraction(
            markdown=text,
            page_count=page_count,
            extracted_page_count=extracted_pages,
            version=pypdf_version,
            backend="pypdf-fallback",
            warnings=tuple(warnings),
        )


class FallbackPdfExtractor:
    def __init__(self, primary: PdfExtractor, fallback: PdfExtractor) -> None:
        self._primary = primary
        self._fallback = fallback

    def extract(
        self,
        content: bytes,
        *,
        backend: MinerUBackend,
        server_url: str,
        max_pages: int,
        max_chars: int,
    ) -> MinerUExtraction:
        try:
            return self._primary.extract(
                content,
                backend=backend,
                server_url=server_url,
                max_pages=max_pages,
                max_chars=max_chars,
            )
        except DocumentationSourceError as error:
            fallback = self._fallback.extract(
                content,
                backend=backend,
                server_url=server_url,
                max_pages=max_pages,
                max_chars=max_chars,
            )
            return MinerUExtraction(
                markdown=fallback.markdown,
                page_count=fallback.page_count,
                extracted_page_count=fallback.extracted_page_count,
                version=fallback.version,
                backend=fallback.backend,
                warnings=(
                    f"MinerU extraction unavailable ({error}); used bounded pypdf fallback",
                    *fallback.warnings,
                ),
            )


class PdfConnector:
    def __init__(
        self,
        client: DocumentationClient,
        extractor: PdfExtractor | None = None,
        *,
        backend: MinerUBackend = MinerUBackend.VLM_HTTP_CLIENT,
        server_url: str = "http://127.0.0.1:30000",
        allow_fallback: bool = True,
        max_bytes: int = MAX_PDF_BYTES,
        max_pages: int = MAX_PDF_PAGES,
        max_extracted_chars: int = MAX_EXTRACTED_CHARS,
        max_redirects: int = MAX_REDIRECTS,
        catalog: FrameworkCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._extractor = extractor or (
            FallbackPdfExtractor(MinerUCliExtractor(), PypdfExtractor())
            if allow_fallback
            else MinerUCliExtractor()
        )
        self._backend = backend
        self._server_url = _safe_mineru_server_url(server_url)
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
            extraction = self._extractor.extract(
                response.content,
                backend=self._backend,
                server_url=self._server_url,
                max_pages=self._max_pages,
                max_chars=self._max_extracted_chars,
            )
            normalized = extraction.markdown.strip()
            if not normalized:
                raise DocumentationSourceError(
                    AccessStatus.ERROR, "MinerU did not produce extractable Markdown"
                )
            text_sha256 = sha256(normalized.encode()).hexdigest()
            snapshot = PdfSnapshot(
                snapshot_id=sha256(f"pdf:{current_url}:{raw_sha256}".encode()).hexdigest(),
                source_url=pdf_url,
                final_url=current_url,
                resolved_revision=f"sha256:{raw_sha256}",
                retrieved_at=self._clock(),
                content_type=content_type,
                page_count=extraction.page_count,
                extracted_page_count=extraction.extracted_page_count,
                extraction_backend=extraction.backend,
                extractor_version=extraction.version,
                text=TextArtifact(
                    path=current_url,
                    content_sha256=text_sha256,
                    content=normalized,
                ),
                warnings=extraction.warnings,
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

    def _fetch_redirects(self, initial_url: str) -> tuple[str, DocumentResponse]:
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


def _read_mineru_output(output_path: Path, *, max_pages: int, max_chars: int) -> MinerUExtraction:
    markdown_files = sorted(output_path.rglob("*.md"))
    content_files = sorted(output_path.rglob("*_content_list_v2.json"))
    if len(markdown_files) != 1 or len(content_files) != 1:
        raise DocumentationSourceError(
            AccessStatus.ERROR, "MinerU output did not contain one Markdown and content-list result"
        )
    try:
        markdown = markdown_files[0].read_text(encoding="utf-8")
        content_list: object = json.loads(content_files[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise DocumentationSourceError(AccessStatus.ERROR, "Invalid MinerU output") from error
    if not isinstance(content_list, list) or not content_list:
        raise DocumentationSourceError(AccessStatus.ERROR, "Invalid MinerU page content list")
    page_count = len(content_list)
    extracted_page_count = min(page_count, max_pages)
    warnings = []
    if page_count >= max_pages:
        warnings.append(f"MinerU extraction was limited to at most {max_pages} pages")
    if len(markdown) > max_chars:
        markdown = markdown[:max_chars]
        warnings.append(f"MinerU Markdown truncated to {max_chars} characters")
    return MinerUExtraction(
        markdown=markdown,
        page_count=page_count,
        extracted_page_count=extracted_page_count,
        version="unknown",
        backend="mineru-output",
        warnings=tuple(warnings),
    )


def _safe_mineru_server_url(value: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise DocumentationSourceError(AccessStatus.ERROR, "Invalid MinerU server URL")
    if parsed.username is not None or parsed.password is not None:
        raise DocumentationSourceError(AccessStatus.ERROR, "Unsafe MinerU server URL")
    return value.rstrip("/")
