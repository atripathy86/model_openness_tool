"""Provider-neutral, schema-validated LLM evidence proposals."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import EvidenceClaim, EvidenceItem, TextArtifact

PROMPT_VERSION = "artifact-proposals-v1"
EXTRACTOR_VERSION = "openai-compatible-v1"
MAX_LLM_INPUT_CHARS = 60_000
MAX_PROPOSALS = 50


class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class LlmClaimProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component_id: int
    source_quote: str = Field(min_length=1, max_length=500)
    source_line_start: int = Field(ge=1)
    source_line_end: int = Field(ge=1)
    rationale: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)


class LlmProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: tuple[LlmClaimProposal, ...] = Field(max_length=MAX_PROPOSALS)


class LlmUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    content: str
    provider: str = "openai-compatible"
    endpoint: str = "unknown"
    usage: LlmUsage = LlmUsage()


class RejectedProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal: LlmClaimProposal
    reason: str


class LlmExtractionReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    extraction_id: str
    source_url: str
    source_revision: str
    source_content_sha256: str
    source_truncated: bool
    provider: str
    endpoint: str
    model: str
    prompt_version: str
    extractor_version: str
    created_at: datetime
    duration_ms: int = Field(ge=0)
    usage: LlmUsage
    evidence: tuple[EvidenceItem, ...]
    rejected: tuple[RejectedProposal, ...]
    review_required: bool = True


class LlmExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ExtractionStatus
    error: str | None = None
    report: LlmExtractionReport | None = None


class StructuredLlmClient(Protocol):
    def extract(self, *, system_prompt: str, user_prompt: str) -> ProviderResponse: ...


class OpenAiCompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(headers=headers, timeout=120.0)

    def extract(self, *, system_prompt: str, user_prompt: str) -> ProviderResponse:
        model = self._model or self._first_model()
        schema = LlmProposalResponse.model_json_schema()
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "mot_artifact_proposals",
                            "strict": True,
                            "schema": schema,
                        },
                    },
                },
            )
            response.raise_for_status()
            payload: object = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError("OpenAI-compatible extraction request failed") from error
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid OpenAI-compatible extraction response")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("Invalid OpenAI-compatible extraction response")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise RuntimeError("Invalid OpenAI-compatible extraction response")
        usage = _usage(payload.get("usage"))
        resolved_model = payload.get("model")
        return ProviderResponse(
            model=resolved_model if isinstance(resolved_model, str) else model,
            content=message["content"],
            endpoint=self._base_url,
            usage=usage,
        )

    def _first_model(self) -> str:
        try:
            response = self._client.get(f"{self._base_url}/models")
            response.raise_for_status()
            payload: object = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError("Could not discover an OpenAI-compatible model") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("Invalid OpenAI-compatible models response")
        for item in payload["data"]:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str):
                    return model_id
        raise RuntimeError("OpenAI-compatible endpoint did not report a model")


class LlmEvidenceExtractor:
    def __init__(
        self,
        client: StructuredLlmClient,
        catalog: FrameworkCatalog,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._catalog = catalog
        self._clock = clock or (lambda: datetime.now(UTC))

    def extract(
        self,
        text: TextArtifact,
        *,
        source_url: str,
        source_revision: str,
    ) -> LlmExtractionResult:
        source = text.content[:MAX_LLM_INPUT_CHARS]
        lines = source.splitlines()
        system_prompt, user_prompt = _prompts(self._catalog, lines)
        started = time.monotonic()
        try:
            provider_response = self._client.extract(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            proposals = LlmProposalResponse.model_validate_json(provider_response.content)
        except (RuntimeError, ValidationError) as error:
            return LlmExtractionResult(status=ExtractionStatus.ERROR, error=str(error))
        duration_ms = round((time.monotonic() - started) * 1000)
        evidence, rejected = _validate_citations(
            proposals,
            lines=lines,
            catalog=self._catalog,
            source_url=source_url,
            source_revision=source_revision,
            source_path=text.path,
        )
        identity = json.dumps(
            {
                "source": text.content_sha256,
                "model": provider_response.model,
                "prompt": PROMPT_VERSION,
                "evidence": [item.evidence_id for item in evidence],
                "rejected": [item.reason for item in rejected],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        report = LlmExtractionReport(
            extraction_id=sha256(identity.encode()).hexdigest(),
            source_url=source_url,
            source_revision=source_revision,
            source_content_sha256=text.content_sha256,
            source_truncated=len(text.content) > MAX_LLM_INPUT_CHARS,
            provider=provider_response.provider,
            endpoint=provider_response.endpoint,
            model=provider_response.model,
            prompt_version=PROMPT_VERSION,
            extractor_version=EXTRACTOR_VERSION,
            created_at=self._clock(),
            duration_ms=duration_ms,
            usage=provider_response.usage,
            evidence=evidence,
            rejected=rejected,
        )
        return LlmExtractionResult(status=ExtractionStatus.SUCCESS, report=report)


def _prompts(catalog: FrameworkCatalog, lines: list[str]) -> tuple[str, str]:
    components = "\n".join(
        f"{component.id}: {component.name} - {component.description}"
        for component in catalog.components
    )
    numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=1))
    system = (
        "You extract review proposals for the Model Openness Framework. Return only the "
        "requested JSON schema. A document statement is not proof that an artifact is "
        "released. Quote the supplied source exactly and never invent citations."
    )
    user = (
        f"Prompt version: {PROMPT_VERSION}\n\nMOF components:\n{components}\n\n"
        "Extract explicit artifact claims. Each source_quote must occur verbatim within the "
        "inclusive numbered line range. Omit uncertain claims.\n\nSource:\n"
        f"{numbered}"
    )
    return system, user


def _validate_citations(
    proposals: LlmProposalResponse,
    *,
    lines: list[str],
    catalog: FrameworkCatalog,
    source_url: str,
    source_revision: str,
    source_path: str,
) -> tuple[tuple[EvidenceItem, ...], tuple[RejectedProposal, ...]]:
    component_ids = {component.id for component in catalog.components}
    evidence = []
    rejected = []
    for proposal in proposals.claims:
        reason = _citation_error(proposal, lines, component_ids)
        if reason is not None:
            rejected.append(RejectedProposal(proposal=proposal, reason=reason))
            continue
        locator = (
            f"{source_path}#line-{proposal.source_line_start}"
            if proposal.source_line_start == proposal.source_line_end
            else (f"{source_path}#lines-{proposal.source_line_start}-{proposal.source_line_end}")
        )
        identity = json.dumps(
            {
                "component": proposal.component_id,
                "quote": proposal.source_quote,
                "locator": locator,
                "revision": source_revision,
                "method": EXTRACTOR_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence.append(
            EvidenceItem(
                evidence_id=sha256(identity.encode()).hexdigest(),
                component_id=proposal.component_id,
                claim=EvidenceClaim.ARTIFACT_MENTIONED,
                value=proposal.source_quote,
                source_url=source_url,
                revision=source_revision,
                path=locator,
                extraction_method=EXTRACTOR_VERSION,
                confidence=proposal.confidence,
                excerpt=proposal.source_quote,
            )
        )
    return tuple(evidence), tuple(rejected)


def _citation_error(
    proposal: LlmClaimProposal, lines: list[str], component_ids: set[int]
) -> str | None:
    if proposal.component_id not in component_ids:
        return "Unknown MOF component ID"
    if proposal.source_line_end < proposal.source_line_start:
        return "Citation line range is reversed"
    if proposal.source_line_end > len(lines):
        return "Citation line range is outside the supplied source"
    cited = "\n".join(lines[proposal.source_line_start - 1 : proposal.source_line_end])
    if proposal.source_quote not in cited:
        return "Source quote does not occur verbatim in the cited line range"
    return None


def _usage(value: object) -> LlmUsage:
    if not isinstance(value, dict):
        return LlmUsage()
    return LlmUsage(
        prompt_tokens=_nonnegative_int(value.get("prompt_tokens")),
        completion_tokens=_nonnegative_int(value.get("completion_tokens")),
        total_tokens=_nonnegative_int(value.get("total_tokens")),
    )


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
