"""Labeled evaluation harness for schema-validated LLM evidence extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.evidence import TextArtifact
from model_openness_tool.llm_extraction import (
    ExtractionStatus,
    LlmEvidenceExtractor,
    StructuredLlmClient,
)

PRECISION_TARGET = 0.95
CITATION_VALIDITY_TARGET = 1.0


class LabeledExtractionCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    expected_component_ids: frozenset[int]


class LabeledEvaluationSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_version: str
    cases: tuple[LabeledExtractionCase, ...] = Field(min_length=1)


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    status: ExtractionStatus
    error: str | None
    expected_component_ids: tuple[int, ...]
    accepted_component_ids: tuple[int, ...]
    rejected_proposal_count: int = Field(ge=0)
    true_positive_component_ids: tuple[int, ...]
    false_positive_component_ids: tuple[int, ...]
    false_negative_component_ids: tuple[int, ...]


class LlmEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation_version: str
    evaluated_at: datetime
    model: str | None
    case_count: int = Field(ge=0)
    successful_case_count: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    accepted_proposals: int = Field(ge=0)
    rejected_proposals: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    raw_citation_validity: float = Field(ge=0, le=1)
    precision_target: float = PRECISION_TARGET
    citation_validity_target: float = CITATION_VALIDITY_TARGET
    zero_llm_promotions: bool = True
    passed: bool
    cases: tuple[EvaluationCaseResult, ...]


def load_evaluation_set(path: Path) -> LabeledEvaluationSet:
    return LabeledEvaluationSet.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_extractor(
    evaluation_set: LabeledEvaluationSet,
    *,
    client: StructuredLlmClient,
    catalog: FrameworkCatalog,
) -> LlmEvaluationReport:
    case_results = []
    model: str | None = None
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    accepted_proposals = 0
    rejected_proposals = 0
    successful_cases = 0

    for case in evaluation_set.cases:
        content_hash = sha256(case.text.encode()).hexdigest()
        result = LlmEvidenceExtractor(client, catalog).extract(
            TextArtifact(
                path=f"evaluation:{case.case_id}",
                content_sha256=content_hash,
                content=case.text,
            ),
            source_url=f"evaluation:{case.case_id}",
            source_revision=f"sha256:{content_hash}",
        )
        accepted_ids: set[int] = set()
        rejected_count = 0
        error = result.error
        if result.report is not None:
            successful_cases += 1
            model = model or result.report.model
            accepted_ids = {
                item.component_id
                for item in result.report.evidence
                if item.component_id is not None
            }
            rejected_count = len(result.report.rejected)
        expected_ids = set(case.expected_component_ids)
        true_ids = accepted_ids & expected_ids
        false_ids = accepted_ids - expected_ids
        missing_ids = expected_ids - accepted_ids
        true_positives += len(true_ids)
        false_positives += len(false_ids) + rejected_count
        false_negatives += len(missing_ids)
        accepted_proposals += len(accepted_ids)
        rejected_proposals += rejected_count
        case_results.append(
            EvaluationCaseResult(
                case_id=case.case_id,
                status=result.status,
                error=error,
                expected_component_ids=tuple(sorted(expected_ids)),
                accepted_component_ids=tuple(sorted(accepted_ids)),
                rejected_proposal_count=rejected_count,
                true_positive_component_ids=tuple(sorted(true_ids)),
                false_positive_component_ids=tuple(sorted(false_ids)),
                false_negative_component_ids=tuple(sorted(missing_ids)),
            )
        )

    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)
    citation_validity = _ratio(
        accepted_proposals,
        accepted_proposals + rejected_proposals,
    )
    passed = (
        successful_cases == len(evaluation_set.cases)
        and true_positives > 0
        and precision >= PRECISION_TARGET
        and citation_validity >= CITATION_VALIDITY_TARGET
    )
    return LlmEvaluationReport(
        evaluation_version=evaluation_set.evaluation_version,
        evaluated_at=datetime.now(UTC),
        model=model,
        case_count=len(evaluation_set.cases),
        successful_case_count=successful_cases,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        accepted_proposals=accepted_proposals,
        rejected_proposals=rejected_proposals,
        precision=precision,
        recall=recall,
        raw_citation_validity=citation_validity,
        passed=passed,
        cases=tuple(case_results),
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator
