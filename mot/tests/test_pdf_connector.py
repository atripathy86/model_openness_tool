import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from model_openness_tool.connectors.documentation import (
    DocumentationSourceError,
    DocumentResponse,
)
from model_openness_tool.connectors.pdf import (
    FallbackPdfExtractor,
    MinerUBackend,
    MinerUCliExtractor,
    MinerUExtraction,
    PdfConnector,
    PypdfExtractor,
)
from model_openness_tool.evidence import AccessStatus, AvailabilityStatus


class FakePdfClient:
    def __init__(self, responses: dict[str, DocumentResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, int]] = []

    def fetch(self, url: str, max_bytes: int) -> DocumentResponse:
        self.requests.append((url, max_bytes))
        return self.responses[url]


class FakeMinerUExtractor:
    def __init__(self, extraction: MinerUExtraction) -> None:
        self.extraction = extraction
        self.calls: list[tuple[bytes, MinerUBackend, str, int, int]] = []

    def extract(
        self,
        content: bytes,
        *,
        backend: MinerUBackend,
        server_url: str,
        max_pages: int,
        max_chars: int,
    ) -> MinerUExtraction:
        self.calls.append((content, backend, server_url, max_pages, max_chars))
        return self.extraction


def test_collects_content_addressed_mineru_markdown_without_promoting_components() -> None:
    url = "https://example.com/report.pdf"
    extractor = FakeMinerUExtractor(
        MinerUExtraction(
            markdown="# Model report\n\n| Metric | Value |\n|---|---|\n| score | 1 |",
            page_count=2,
            extracted_page_count=2,
            version="3.3.0",
            backend="vlm-http-client",
        )
    )
    result = PdfConnector(
        FakePdfClient(
            {
                url: DocumentResponse(
                    status_code=200,
                    content_type="application/pdf",
                    content=b"%PDF mocked",
                )
            }
        ),
        extractor,
        server_url="http://mineru.example.com:30000",
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).collect(url)

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.snapshot.page_count == 2
    assert result.snapshot.extraction_backend == "vlm-http-client"
    assert result.snapshot.extractor_version == "3.3.0"
    assert "| Metric | Value |" in result.snapshot.text.content
    assert extractor.calls == [
        (
            b"%PDF mocked",
            MinerUBackend.VLM_HTTP_CLIENT,
            "http://mineru.example.com:30000",
            100,
            500_000,
        )
    ]
    assert result.evidence_report is not None
    assert all(
        finding.availability == AvailabilityStatus.UNKNOWN
        for finding in result.evidence_report.findings
    )


def test_preserves_mineru_extraction_warnings() -> None:
    url = "https://example.com/report.pdf"
    result = PdfConnector(
        FakePdfClient(
            {
                url: DocumentResponse(
                    status_code=200,
                    content_type="application/pdf",
                    content=b"%PDF mocked",
                )
            }
        ),
        FakeMinerUExtractor(
            MinerUExtraction(
                markdown="bounded",
                page_count=100,
                extracted_page_count=100,
                version="3.3.0",
                backend="vlm-http-client",
                warnings=("MinerU extraction was limited to at most 100 pages",),
            )
        ),
    ).collect(url)

    assert result.snapshot is not None
    assert result.snapshot.warnings == ("MinerU extraction was limited to at most 100 pages",)


def test_rejects_non_pdf_content_and_unsafe_redirects_before_extraction() -> None:
    source = "https://example.com/report.pdf"
    extractor = FakeMinerUExtractor(MinerUExtraction("unused", 1, 1, "3.3.0", "vlm-http-client"))
    wrong_type = PdfConnector(
        FakePdfClient(
            {
                source: DocumentResponse(
                    status_code=200,
                    content_type="text/html",
                    content=b"not a pdf",
                )
            }
        ),
        extractor,
    ).collect(source)
    unsafe_redirect = PdfConnector(
        FakePdfClient(
            {
                source: DocumentResponse(
                    status_code=302,
                    content_type="text/plain",
                    content=b"",
                    location="http://127.0.0.1/private.pdf",
                )
            }
        ),
        extractor,
    ).collect(source)

    assert wrong_type.error == "Unsupported PDF content type: text/html"
    assert unsafe_redirect.error == "Non-public documentation URLs are blocked"
    assert extractor.calls == []


def test_mineru_cli_extractor_invokes_remote_backend_and_reads_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        assert options["timeout"] == 600
        output = Path(command[command.index("-o") + 1]) / "document" / "vlm"
        output.mkdir(parents=True)
        (output / "document.md").write_text("# Parsed\n\n| A | B |", encoding="utf-8")
        (output / "document_content_list_v2.json").write_text("[[], []]", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("model_openness_tool.connectors.pdf.shutil.which", lambda value: value)
    monkeypatch.setattr("model_openness_tool.connectors.pdf.subprocess.run", fake_run)

    result = MinerUCliExtractor().extract(
        b"%PDF mocked",
        backend=MinerUBackend.VLM_HTTP_CLIENT,
        server_url="http://127.0.0.1:30000",
        max_pages=100,
        max_chars=500_000,
    )

    assert result.markdown.startswith("# Parsed")
    assert result.page_count == 2
    assert result.version == "3.4.4"
    assert captured[0][captured[0].index("-b") + 1] == "vlm-http-client"
    assert captured[0][captured[0].index("-u") + 1] == "http://127.0.0.1:30000"
    assert captured[0][captured[0].index("--end") + 1] == "99"


def test_falls_back_to_bounded_pypdf_and_records_reduced_fidelity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableMinerU:
        def extract(self, content: bytes, **options: object) -> MinerUExtraction:
            raise DocumentationSourceError(AccessStatus.ERROR, "VLM server unavailable")

    class FakePage:
        def extract_text(self) -> str:
            return "Fallback PDF text"

    class FakeReader:
        def __init__(self, source: object, strict: bool) -> None:
            assert strict is False
            self.pages = [FakePage()]

    monkeypatch.setattr("model_openness_tool.connectors.pdf.PdfReader", FakeReader)
    extractor = FallbackPdfExtractor(UnavailableMinerU(), PypdfExtractor())

    result = extractor.extract(
        b"%PDF mocked",
        backend=MinerUBackend.VLM_HTTP_CLIENT,
        server_url="http://127.0.0.1:30000",
        max_pages=100,
        max_chars=500_000,
    )

    assert result.backend == "pypdf-fallback"
    assert result.markdown == "Fallback PDF text"
    assert "VLM server unavailable" in result.warnings[0]


def test_pdf_semantic_claims_remain_mentioned_only() -> None:
    url = "https://example.com/report.pdf"
    result = PdfConnector(
        FakePdfClient(
            {
                url: DocumentResponse(
                    status_code=200,
                    content_type="application/pdf",
                    content=b"%PDF mocked",
                )
            }
        ),
        FakeMinerUExtractor(
            MinerUExtraction(
                "# Evaluation results\n\nThe training dataset is described in the paper.",
                1,
                1,
                "3.4.4",
                "vlm-http-client",
            )
        ),
    ).collect(url)

    assert result.evidence_report is not None
    mentioned = {
        finding.component_id
        for finding in result.evidence_report.findings
        if finding.availability == AvailabilityStatus.MENTIONED_ONLY
    }
    assert mentioned == {12, 15, 21}
