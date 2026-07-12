import json
from pathlib import Path

from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.llm_evaluation import evaluate_extractor, load_evaluation_set
from model_openness_tool.llm_extraction import ProviderResponse


class LabeledFakeClient:
    def __init__(self, *, emit_claims: bool = True) -> None:
        self.emit_claims = emit_claims

    def extract(self, *, system_prompt: str, user_prompt: str) -> ProviderResponse:
        del system_prompt
        source_lines = [line for line in user_prompt.splitlines() if line.startswith("1: ")]
        source = source_lines[-1].removeprefix("1: ")
        claims = []
        if self.emit_claims:
            expected = {
                "training code is released": (7, 16),
                "training dataset is ExampleCorpus": (12, 15),
                "final model weights are published": (10, 17),
                "We trained and evaluated": (),
                "research paper and technical report": (11, 20, 21),
            }
            marker = next(marker for marker in expected if marker in user_prompt)
            claims = [
                {
                    "component_id": component_id,
                    "source_quote": source,
                    "source_line_start": 1,
                    "source_line_end": 1,
                    "rationale": "Labeled fixture claim.",
                    "confidence": 0.99,
                }
                for component_id in expected[marker]
            ]
        return ProviderResponse(model="fixture-model", content=json.dumps({"claims": claims}))


def test_five_case_fixture_meets_gates_with_exact_cited_predictions(
    catalog: FrameworkCatalog,
) -> None:
    fixture = Path(__file__).parent / "fixtures/llm-evaluation-v1.json"
    evaluation_set = load_evaluation_set(fixture)

    report = evaluate_extractor(
        evaluation_set,
        client=LabeledFakeClient(),
        catalog=catalog,
    )

    assert report.case_count == 5
    assert report.true_positives == 9
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.raw_citation_validity == 1.0
    assert report.zero_llm_promotions is True
    assert report.passed is True


def test_zero_claims_cannot_pass_vacuous_precision(
    catalog: FrameworkCatalog,
) -> None:
    fixture = Path(__file__).parent / "fixtures/llm-evaluation-v1.json"

    report = evaluate_extractor(
        load_evaluation_set(fixture),
        client=LabeledFakeClient(emit_claims=False),
        catalog=catalog,
    )

    assert report.precision == 1.0
    assert report.recall == 0.0
    assert report.true_positives == 0
    assert report.passed is False
