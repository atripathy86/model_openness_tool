from datetime import UTC, datetime

import httpx

from model_openness_tool.connectors.doi import CrossrefClient, DoiConnector, DoiPaperMetadata
from model_openness_tool.evidence import AccessStatus, AvailabilityStatus, EvidenceClaim


class FakeDoiClient:
    def get_work(self, doi: str) -> DoiPaperMetadata:
        assert doi == "10.18653/v1/n19-1423"
        return DoiPaperMetadata(
            doi="10.18653/v1/n19-1423",
            source_url="https://doi.org/10.18653/v1/n19-1423",
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            authors=("A. Author", "B. Author"),
            abstract="A bounded abstract.",
            published_at=datetime(2019, 6, 1, tzinfo=UTC),
            updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            declared_license="https://creativecommons.org/licenses/by/4.0/",
            metadata_sha256="c" * 64,
        )


def test_collects_content_addressed_doi_paper_evidence() -> None:
    result = DoiConnector(
        FakeDoiClient(),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).collect("https://doi.org/10.18653/v1/n19-1423")

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.snapshot.paper_id == "10.18653/v1/n19-1423"
    assert result.snapshot.resolved_revision == f"sha256:{'c' * 64}"
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


def test_rejects_unsupported_doi_inputs() -> None:
    result = DoiConnector(FakeDoiClient()).collect("https://example.com/paper.pdf")

    assert result.access_status == AccessStatus.ERROR
    assert result.snapshot is None


def test_crossref_client_parses_bounded_work_metadata() -> None:
    payload = {
        "message": {
            "DOI": "10.18653/v1/n19-1423",
            "URL": "https://doi.org/10.18653/v1/n19-1423",
            "title": ["  BERT:\n Pre-training "],
            "author": [
                {"given": "Jacob", "family": "Devlin"},
                {"name": "Example Consortium"},
            ],
            "abstract": "<jats:p>Example &amp; bounded abstract.</jats:p>",
            "published-print": {"date-parts": [[2019, 6]]},
            "created": {"date-time": "2019-06-01T00:00:00Z"},
            "deposited": {"date-time": "2020-01-01T00:00:00Z"},
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/10.18653/v1/n19-1423"
        return httpx.Response(200, json=payload)

    client = httpx.Client(
        base_url="https://api.crossref.org",
        transport=httpx.MockTransport(handler),
    )
    metadata = CrossrefClient(client=client).get_work("10.18653/v1/n19-1423")

    assert metadata.doi == "10.18653/v1/n19-1423"
    assert metadata.title == "BERT: Pre-training"
    assert metadata.authors == ("Jacob Devlin", "Example Consortium")
    assert metadata.abstract == "Example & bounded abstract."
    assert metadata.declared_license == "https://creativecommons.org/licenses/by/4.0/"
    assert len(metadata.metadata_sha256) == 64


def test_crossref_client_falls_back_to_doi_when_title_is_empty() -> None:
    payload = {
        "message": {
            "DOI": "10.18653/v1/n19-1423",
            "URL": "https://doi.org/10.18653/v1/n19-1423",
            "title": [""],
            "published": {"date-parts": [[2019]]},
            "created": {"date-time": "2019-07-21T17:26:41Z"},
            "deposited": {"date-time": "2019-07-21T17:29:29Z"},
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(
        base_url="https://api.crossref.org",
        transport=httpx.MockTransport(handler),
    )
    metadata = CrossrefClient(client=client).get_work("10.18653/v1/n19-1423")

    assert metadata.title == "10.18653/v1/n19-1423"
