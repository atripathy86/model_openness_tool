from datetime import UTC, datetime

from model_openness_tool.connectors.documentation import (
    DocumentationConnector,
    DocumentResponse,
)
from model_openness_tool.evidence import AccessStatus, AvailabilityStatus


class FakeDocumentationClient:
    def __init__(self, responses: dict[str, DocumentResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, int]] = []

    def fetch(self, url: str, max_bytes: int) -> DocumentResponse:
        self.requests.append((url, max_bytes))
        return self.responses[url]


def test_collects_content_addressed_html_without_promoting_components() -> None:
    url = "https://docs.example.com/model"
    client = FakeDocumentationClient(
        {
            url: DocumentResponse(
                status_code=200,
                content_type="text/html; charset=utf-8",
                content=(
                    b"<html><head><title>Model docs</title><style>hidden</style></head>"
                    b"<body><h1>Model</h1><script>ignored</script><p>Public docs.</p></body></html>"
                ),
            )
        }
    )
    result = DocumentationConnector(
        client,
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).collect(url)

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.snapshot.title == "Model docs"
    assert result.snapshot.resolved_revision.startswith("sha256:")
    assert "ignored" not in result.snapshot.text.content
    assert result.evidence_report is not None
    assert all(
        finding.availability == AvailabilityStatus.UNKNOWN
        for finding in result.evidence_report.findings
    )


def test_validates_every_redirect_and_blocks_local_network_targets() -> None:
    source = "https://docs.example.com/model"
    client = FakeDocumentationClient(
        {
            source: DocumentResponse(
                status_code=302,
                content_type="text/plain",
                content=b"",
                location="http://127.0.0.1/private",
            )
        }
    )

    result = DocumentationConnector(client).collect(source)

    assert result.access_status == AccessStatus.ERROR
    assert result.error == "Non-public documentation URLs are blocked"
    assert len(client.requests) == 1


def test_rejects_binary_documentation_content() -> None:
    url = "https://docs.example.com/archive"
    result = DocumentationConnector(
        FakeDocumentationClient(
            {
                url: DocumentResponse(
                    status_code=200,
                    content_type="application/zip",
                    content=b"binary",
                )
            }
        )
    ).collect(url)

    assert result.access_status == AccessStatus.ERROR
    assert result.error == "Unsupported documentation content type: application/zip"


def test_rejects_invalid_or_nonstandard_url_authorities() -> None:
    client = FakeDocumentationClient({})

    invalid_port = DocumentationConnector(client).collect("https://example.com:invalid/docs")
    embedded_credentials = DocumentationConnector(client).collect(
        "https://user:password@example.com/docs"
    )

    assert invalid_port.error == "Unsafe documentation URL authority"
    assert embedded_credentials.error == "Unsafe documentation URL authority"
    assert client.requests == []
