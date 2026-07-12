from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from model_openness_tool.connectors.huggingface import (
    HubClient,
    HubFileMetadata,
    HubModelMetadata,
    HubSourceError,
    HuggingFaceConnector,
)
from model_openness_tool.evidence import (
    AccessStatus,
    AvailabilityStatus,
    CollectionResult,
    ComponentFinding,
    EvidenceClaim,
)


class FakeHubClient(HubClient):
    def __init__(
        self,
        *,
        model: HubModelMetadata,
        files: tuple[HubFileMetadata, ...],
        model_card_path: Path,
    ) -> None:
        self.model = model
        self.files = files
        self.model_card_path = model_card_path
        self.model_requests: list[tuple[str, str | None]] = []
        self.file_requests: list[tuple[str, str]] = []
        self.download_requests: list[tuple[str, str, str, Path]] = []

    def get_model(self, model_id: str, revision: str | None) -> HubModelMetadata:
        self.model_requests.append((model_id, revision))
        return self.model

    def list_files(self, model_id: str, revision: str) -> Iterable[HubFileMetadata]:
        self.file_requests.append((model_id, revision))
        return self.files

    def download_file(self, model_id: str, revision: str, path: str, cache_dir: Path) -> Path:
        self.download_requests.append((model_id, revision, path, cache_dir))
        return self.model_card_path


class ErrorHubClient(HubClient):
    def get_model(self, model_id: str, revision: str | None) -> HubModelMetadata:
        raise HubSourceError(AccessStatus.GATED, "Model repository is gated")

    def list_files(self, model_id: str, revision: str) -> Iterable[HubFileMetadata]:
        raise AssertionError("list_files must not be called after an access error")

    def download_file(self, model_id: str, revision: str, path: str, cache_dir: Path) -> Path:
        raise AssertionError("download_file must not be called after an access error")


def _finding(result: CollectionResult, component_id: int) -> ComponentFinding:
    report = result.report
    assert report is not None
    return next(item for item in report.findings if item.component_id == component_id)


def test_collect_pins_revision_and_emits_conservative_evidence(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text(
        """---
license: apache-2.0
datasets:
- example/data
---
# Example model

See https://arxiv.org/abs/1234.5678 and our benchmark results.
""",
        encoding="utf-8",
    )
    client = FakeHubClient(
        model=HubModelMetadata(
            model_id="example/model",
            revision="a" * 40,
            private=False,
            gated=False,
            pipeline_tag="text-generation",
            tags=("transformers",),
            declared_license="apache-2.0",
        ),
        files=(
            HubFileMetadata("model.safetensors", 1000, "weight", "b" * 64, 1000),
            HubFileMetadata("README.md", card.stat().st_size, "readme"),
            HubFileMetadata("config.json", 100, "config"),
            HubFileMetadata("modeling_example.py", 200, "architecture"),
            HubFileMetadata("inference.py", 150, "inference"),
        ),
        model_card_path=card,
    )
    connector = HuggingFaceConnector(
        client,
        cache_dir=tmp_path / "cache",
        clock=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )

    result = connector.collect("example/model", revision="main")

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.report is not None
    assert result.report.snapshot.requested_revision == "main"
    assert result.report.snapshot.resolved_revision == "a" * 40
    assert client.model_requests == [("example/model", "main")]
    assert client.file_requests == [("example/model", "a" * 40)]
    assert client.download_requests == [
        ("example/model", "a" * 40, "README.md", tmp_path / "cache")
    ]

    for component_id in (8, 9, 10, 13, 17):
        assert _finding(result, component_id).availability == AvailabilityStatus.PRESENT
    for component_id in (12, 15, 21):
        assert _finding(result, component_id).availability == AvailabilityStatus.MENTIONED_ONLY

    license_evidence = [
        item for item in result.report.evidence if item.claim == EvidenceClaim.LICENSE_DECLARED
    ]
    assert len(license_evidence) == 1
    assert license_evidence[0].value == "apache-2.0"


def test_collect_does_not_download_oversized_model_card(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text("unused", encoding="utf-8")
    client = FakeHubClient(
        model=HubModelMetadata(
            model_id="example/model",
            revision="a" * 40,
            private=False,
            gated=False,
            pipeline_tag=None,
            tags=(),
            declared_license=None,
        ),
        files=(HubFileMetadata("README.md", 101, "readme"),),
        model_card_path=card,
    )

    result = HuggingFaceConnector(
        client,
        cache_dir=tmp_path / "cache",
        max_model_card_bytes=100,
    ).collect("example/model")

    assert result.report is not None
    assert result.report.snapshot.model_card is None
    assert "exceeds the 100-byte limit" in result.report.snapshot.warnings[0]
    assert not client.download_requests
    assert _finding(result, 13).availability == AvailabilityStatus.PRESENT


def test_collect_rechecks_model_card_size_after_download(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text("x" * 101, encoding="utf-8")
    client = FakeHubClient(
        model=HubModelMetadata(
            model_id="example/model",
            revision="a" * 40,
            private=False,
            gated=False,
            pipeline_tag=None,
            tags=(),
            declared_license=None,
        ),
        files=(HubFileMetadata("README.md", 10, "readme"),),
        model_card_path=card,
    )

    result = HuggingFaceConnector(
        client,
        cache_dir=tmp_path / "cache",
        max_model_card_bytes=100,
    ).collect("example/model")

    assert result.report is not None
    assert result.report.snapshot.model_card is None
    assert "exceeds the 100-byte limit" in result.report.snapshot.warnings[0]


def test_collect_enforces_repository_file_limit(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text("unused", encoding="utf-8")
    client = FakeHubClient(
        model=HubModelMetadata(
            model_id="example/model",
            revision="a" * 40,
            private=False,
            gated=False,
            pipeline_tag=None,
            tags=(),
            declared_license=None,
        ),
        files=(
            HubFileMetadata("one.txt", 1, "one"),
            HubFileMetadata("two.txt", 1, "two"),
        ),
        model_card_path=card,
    )

    result = HuggingFaceConnector(
        client,
        cache_dir=tmp_path / "cache",
        max_files=1,
    ).collect("example/model")

    assert result.access_status == AccessStatus.ERROR
    assert result.error == "Repository exceeds the 1-file collection limit"
    assert result.report is None


def test_collect_returns_structured_access_error(tmp_path: Path) -> None:
    result = HuggingFaceConnector(ErrorHubClient(), cache_dir=tmp_path).collect(
        "gated/model",
        revision="main",
    )

    assert result.access_status == AccessStatus.GATED
    assert result.error == "Model repository is gated"
    assert result.report is None
