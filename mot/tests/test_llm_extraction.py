import json
from datetime import UTC, datetime

import httpx

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import EvidenceClaim, TextArtifact
from model_openness_tool.llm_extraction import (
    ExtractionStatus,
    LlmEvidenceExtractor,
    LlmUsage,
    OpenAiCompatibleClient,
    ProviderResponse,
)


class FakeStructuredClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.prompts: list[tuple[str, str]] = []

    def extract(self, *, system_prompt: str, user_prompt: str) -> ProviderResponse:
        self.prompts.append((system_prompt, user_prompt))
        return ProviderResponse(
            model="local-test-model",
            content=json.dumps(self.payload),
            usage=LlmUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        )


def test_accepts_only_schema_valid_proposals_with_verbatim_citations(
    catalog: FrameworkCatalog,
) -> None:
    client = FakeStructuredClient(
        {
            "claims": [
                {
                    "component_id": 7,
                    "source_quote": "The training code is published separately.",
                    "source_line_start": 2,
                    "source_line_end": 2,
                    "rationale": "Explicit training-code statement.",
                    "confidence": 0.93,
                },
                {
                    "component_id": 15,
                    "source_quote": "Invented dataset quote",
                    "source_line_start": 1,
                    "source_line_end": 1,
                    "rationale": "Unsupported.",
                    "confidence": 0.8,
                },
            ]
        }
    )
    result = LlmEvidenceExtractor(
        client,
        catalog,
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    ).extract(
        TextArtifact(
            path="https://docs.example.com/model",
            content_sha256="content-hash",
            content="# Training\nThe training code is published separately.",
        ),
        source_url="https://docs.example.com/model",
        source_revision="sha256:source",
    )

    assert result.status == ExtractionStatus.SUCCESS
    assert result.report is not None
    assert result.report.review_required is True
    assert result.report.model == "local-test-model"
    assert result.report.usage.total_tokens == 120
    assert len(result.report.evidence) == 1
    assert result.report.evidence[0].claim == EvidenceClaim.ARTIFACT_MENTIONED
    assert result.report.evidence[0].path.endswith("#line-2")
    assert result.report.rejected[0].reason == (
        "Source quote does not occur verbatim in the cited line range"
    )
    assert "Return only the requested JSON schema" in client.prompts[0][0]


def test_rejects_non_schema_provider_output(catalog: FrameworkCatalog) -> None:
    result = LlmEvidenceExtractor(
        FakeStructuredClient({"unexpected": []}),
        catalog,
    ).extract(
        TextArtifact(path="doc", content_sha256="hash", content="text"),
        source_url="https://docs.example.com/model",
        source_revision="sha256:source",
    )

    assert result.status == ExtractionStatus.ERROR
    assert result.report is None


def test_openai_compatible_client_supports_unauthenticated_model_discovery() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "local-model"}]})
        if request.url.path == "/v1/chat/completions":
            assert request.read()
            return httpx.Response(
                200,
                json={
                    "model": "local-model",
                    "choices": [{"message": {"content": '{"claims": []}'}}],
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    response = OpenAiCompatibleClient(
        base_url="http://127.0.0.1:1234/v1",
        client=http,
    ).extract(system_prompt="system", user_prompt="user")

    assert response.model == "local-model"
    assert all("authorization" not in request.headers for request in requests)
