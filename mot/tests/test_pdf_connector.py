from datetime import UTC, datetime

import pytest

from model_openness_tool.connectors.documentation import DocumentResponse
from model_openness_tool.connectors.pdf import PdfConnector
from model_openness_tool.evidence import AccessStatus, AvailabilityStatus


class FakePdfClient:
    def __init__(self, responses: dict[str, DocumentResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, int]] = []

    def fetch(self, url: str, max_bytes: int) -> DocumentResponse:
        self.requests.append((url, max_bytes))
        return self.responses[url]


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, _source: object, strict: bool) -> None:
        assert strict is False
        self.pages = [FakePage("Model report\nTraining details"), FakePage("Evaluation results")]


def test_collects_bounded_content_addressed_pdf_without_promoting_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://example.com/report.pdf"
    monkeypatch.setattr("model_openness_tool.connectors.pdf.PdfReader", FakeReader)
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
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).collect(url)

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.snapshot.page_count == 2
    assert result.snapshot.extracted_page_count == 2
    assert result.snapshot.resolved_revision.startswith("sha256:")
    assert "Training details" in result.snapshot.text.content
    assert result.evidence_report is not None
    assert all(
        finding.availability == AvailabilityStatus.UNKNOWN
        for finding in result.evidence_report.findings
    )


def test_limits_extracted_pages_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.com/report.pdf"
    monkeypatch.setattr("model_openness_tool.connectors.pdf.PdfReader", FakeReader)
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
        max_pages=1,
        max_extracted_chars=12,
    ).collect(url)

    assert result.snapshot is not None
    assert result.snapshot.extracted_page_count == 1
    assert len(result.snapshot.text.content) == 12
    assert len(result.snapshot.warnings) == 2


def test_rejects_non_pdf_content_and_unsafe_redirects() -> None:
    source = "https://example.com/report.pdf"
    wrong_type = PdfConnector(
        FakePdfClient(
            {
                source: DocumentResponse(
                    status_code=200,
                    content_type="text/html",
                    content=b"not a pdf",
                )
            }
        )
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
        )
    ).collect(source)

    assert wrong_type.error == "Unsupported PDF content type: text/html"
    assert unsafe_redirect.error == "Non-public documentation URLs are blocked"
