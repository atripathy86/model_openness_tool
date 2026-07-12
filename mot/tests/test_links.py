from model_openness_tool.evidence import LinkedSourceType, TextArtifact
from model_openness_tool.links import (
    extract_linked_sources,
    normalize_github_repository,
    normalize_linked_source,
)


def test_extracts_and_deduplicates_supported_linked_sources() -> None:
    card = TextArtifact(
        path="README.md",
        content_sha256="hash",
        content="""
Code: https://github.com/ExampleOrg/example-model/tree/main and
https://github.com/ExampleOrg/example-model.git.
Data: https://huggingface.co/datasets/example-org/example-data/viewer/default/train
Paper: https://arxiv.org/pdf/2401.12345.pdf and https://doi.org/10.1000/example.
Docs: https://example.com/model/docs.
""",
    )

    sources = extract_linked_sources(card)

    identities = {(source.source_type, source.identifier) for source in sources}
    assert (LinkedSourceType.GITHUB_REPOSITORY, "ExampleOrg/example-model") in identities
    assert (LinkedSourceType.HUGGINGFACE_DATASET, "example-org/example-data") in identities
    assert (LinkedSourceType.PAPER, "arxiv:2401.12345") in identities
    assert (LinkedSourceType.PAPER, "doi:10.1000/example") in identities
    assert (LinkedSourceType.DOCUMENTATION, "https://example.com/model/docs") in identities
    assert (
        len(
            [
                source
                for source in sources
                if source.source_type == LinkedSourceType.GITHUB_REPOSITORY
            ]
        )
        == 1
    )


def test_rejects_github_navigation_pages_as_repositories() -> None:
    assert normalize_github_repository("https://github.com/topics/machine-learning") is None
    assert normalize_github_repository("https://github.com/example") is None


def test_normalizes_direct_github_repository_input() -> None:
    source = normalize_github_repository("git+https://github.com/example/repo.git")
    assert source is None

    source = normalize_github_repository("https://github.com/example/repo/issues/1")
    assert source is not None
    assert source.identifier == "example/repo"
    assert source.canonical_url == "https://github.com/example/repo"


def test_unsupported_non_http_links_are_ignored() -> None:
    assert normalize_linked_source("file:///tmp/model", discovered_in="README.md") is None
    assert (
        normalize_linked_source(
            "https://example.com/button.png",
            discovered_in="README.md",
        )
        is None
    )


def test_generic_pdf_is_recorded_as_paper() -> None:
    source = normalize_linked_source(
        "https://example.com/reports/model.pdf",
        discovered_in="README.md",
    )

    assert source is not None
    assert source.source_type == LinkedSourceType.PAPER
