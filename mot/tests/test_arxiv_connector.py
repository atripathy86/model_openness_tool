from datetime import UTC, datetime

import httpx

from model_openness_tool.connectors.arxiv import (
    ArxivApiClient,
    ArxivConnector,
    ArxivPaperMetadata,
)
from model_openness_tool.evidence import AccessStatus, AvailabilityStatus, EvidenceClaim


class FakeArxivClient:
    def get_paper(self, paper_id: str) -> ArxivPaperMetadata:
        assert paper_id == "1912.01703"
        return ArxivPaperMetadata(
            paper_id="1912.01703v2",
            title="Language Models are Unsupervised Multitask Learners",
            authors=("A. Author", "B. Author"),
            abstract="A bounded abstract.",
            published_at=datetime(2019, 12, 4, tzinfo=UTC),
            updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            declared_license="http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        )


def test_collects_version_pinned_paper_evidence() -> None:
    result = ArxivConnector(
        FakeArxivClient(),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).collect("1912.01703")

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.snapshot.resolved_revision == "v2"
    assert result.snapshot.source_url.endswith("1912.01703v2")
    assert result.evidence_report is not None
    research_paper = next(
        finding for finding in result.evidence_report.findings if finding.component_id == 21
    )
    assert research_paper.availability == AvailabilityStatus.PRESENT
    licenses = [
        item
        for item in result.evidence_report.evidence
        if item.claim == EvidenceClaim.LICENSE_DECLARED
    ]
    assert len(licenses) == 1
    assert licenses[0].component_id == 21


def test_rejects_unsupported_paper_urls() -> None:
    result = ArxivConnector(FakeArxivClient()).collect("https://example.com/paper.pdf")

    assert result.access_status == AccessStatus.ERROR
    assert result.snapshot is None


def test_api_client_parses_bounded_atom_metadata() -> None:
    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1912.01703v2</id>
    <updated>2020-01-01T00:00:00Z</updated>
    <published>2019-12-04T00:00:00Z</published>
    <title>  Example\n title </title>
    <summary> Example abstract. </summary>
    <author><name>A. Author</name></author>
    <arxiv:license href="http://arxiv.org/licenses/nonexclusive-distrib/1.0/" />
  </entry>
</feed>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id_list"] == "1912.01703"
        return httpx.Response(200, content=atom)

    client = httpx.Client(
        base_url="https://export.arxiv.org",
        transport=httpx.MockTransport(handler),
    )
    metadata = ArxivApiClient(client=client).get_paper("1912.01703")

    assert metadata.paper_id == "1912.01703v2"
    assert metadata.title == "Example title"
    assert metadata.authors == ("A. Author",)
    assert metadata.declared_license is not None
