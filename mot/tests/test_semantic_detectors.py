from model_openness_tool.evidence import EvidenceClaim
from model_openness_tool.semantic_detectors import extract_semantic_mentions


def test_extracts_bounded_cited_artifact_mentions() -> None:
    evidence = extract_semantic_mentions(
        (
            "## Training\n"
            "The training code and preprocessing pipeline are described below.\n"
            "Evaluation results report accuracy on the benchmark dataset."
        ),
        snapshot_id="snapshot",
        source_url="https://docs.example.com/model",
        revision="sha256:document",
        path="https://docs.example.com/model",
        extraction_method="test-semantic-v1",
    )

    assert {item.component_id for item in evidence} == {7, 12, 16, 19}
    assert all(item.claim == EvidenceClaim.ARTIFACT_MENTIONED for item in evidence)
    assert all(item.excerpt for item in evidence)
    assert {item.path for item in evidence} == {
        "https://docs.example.com/model#line-2",
        "https://docs.example.com/model#line-3",
    }


def test_does_not_treat_generic_activity_words_as_artifact_mentions() -> None:
    evidence = extract_semantic_mentions(
        "We trained and evaluated the model before deployment.",
        snapshot_id="snapshot",
        source_url="https://docs.example.com/model",
        revision="sha256:document",
        path="https://docs.example.com/model",
        extraction_method="test-semantic-v1",
    )

    assert evidence == ()
