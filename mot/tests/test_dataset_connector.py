from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from model_openness_tool.connectors.huggingface_dataset import (
    DatasetClient,
    DatasetFileMetadata,
    DatasetMetadata,
    DatasetSourceError,
    HuggingFaceDatasetConnector,
)
from model_openness_tool.dataset_detectors import MAX_DATA_FILE_EVIDENCE
from model_openness_tool.evidence import AccessStatus, AvailabilityStatus, EvidenceClaim


class FakeDatasetClient(DatasetClient):
    def __init__(self, card: Path) -> None:
        self.card = card
        self.downloads: list[str] = []

    def get_dataset(self, dataset_id: str, revision: str | None) -> DatasetMetadata:
        return DatasetMetadata(
            dataset_id=dataset_id,
            revision="d" * 40,
            private=False,
            gated=False,
            tags=("language:en",),
            declared_licenses=("cc-by-4.0",),
        )

    def list_files(self, dataset_id: str, revision: str) -> Iterable[DatasetFileMetadata]:
        return (
            DatasetFileMetadata("README.md", self.card.stat().st_size, "readme"),
            DatasetFileMetadata("data/train.parquet", 10_000, "data", "a" * 64, 10_000),
            DatasetFileMetadata("LICENSE", 100, "license"),
        )

    def download_file(
        self,
        dataset_id: str,
        revision: str,
        path: str,
        cache_dir: Path,
    ) -> Path:
        self.downloads.append(path)
        return self.card


class GatedDatasetClient(DatasetClient):
    def get_dataset(self, dataset_id: str, revision: str | None) -> DatasetMetadata:
        raise DatasetSourceError(AccessStatus.GATED, "Dataset repository is gated")

    def list_files(self, dataset_id: str, revision: str) -> Iterable[DatasetFileMetadata]:
        raise AssertionError("not reached")

    def download_file(
        self,
        dataset_id: str,
        revision: str,
        path: str,
        cache_dir: Path,
    ) -> Path:
        raise AssertionError("not reached")


class LargeDatasetClient(FakeDatasetClient):
    def list_files(self, dataset_id: str, revision: str) -> Iterable[DatasetFileMetadata]:
        return tuple(
            DatasetFileMetadata(f"data/part-{index:05}.parquet", 10_000, "data")
            for index in range(MAX_DATA_FILE_EVIDENCE + 5)
        )


def test_dataset_collection_proves_release_without_downloading_data(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text("# Dataset card", encoding="utf-8")
    client = FakeDatasetClient(card)
    connector = HuggingFaceDatasetConnector(
        client,
        cache_dir=tmp_path / "cache",
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    result = connector.collect("https://huggingface.co/datasets/example/data", "main")

    assert result.access_status == AccessStatus.AVAILABLE
    assert result.snapshot is not None
    assert result.evidence_report is not None
    assert result.snapshot.resolved_revision == "d" * 40
    assert client.downloads == ["LICENSE", "README.md"]
    assert "data/train.parquet" not in client.downloads
    findings = {item.component_id: item for item in result.evidence_report.findings}
    assert findings[15].availability == AvailabilityStatus.PRESENT
    assert findings[14].availability == AvailabilityStatus.PRESENT
    licenses = [
        item
        for item in result.evidence_report.evidence
        if item.claim == EvidenceClaim.LICENSE_DECLARED
    ]
    assert len(licenses) == 1
    assert licenses[0].component_id == 15
    assert licenses[0].value == "cc-by-4.0"


def test_dataset_collection_returns_structured_gated_result(tmp_path: Path) -> None:
    result = HuggingFaceDatasetConnector(
        GatedDatasetClient(),
        cache_dir=tmp_path,
    ).collect("https://huggingface.co/datasets/example/gated")

    assert result.access_status == AccessStatus.GATED
    assert result.snapshot is None
    assert result.error == "Dataset repository is gated"


def test_dataset_evidence_caps_cited_data_paths(tmp_path: Path) -> None:
    card = tmp_path / "README.md"
    card.write_text("# Dataset card", encoding="utf-8")
    result = HuggingFaceDatasetConnector(
        LargeDatasetClient(card),
        cache_dir=tmp_path / "cache",
    ).collect("https://huggingface.co/datasets/example/large")

    assert result.evidence_report is not None
    dataset_finding = next(
        finding for finding in result.evidence_report.findings if finding.component_id == 15
    )
    assert len(dataset_finding.evidence_ids) == MAX_DATA_FILE_EVIDENCE
    assert "25 released data file(s); 20 representative path(s)" in dataset_finding.rationale


def test_dataset_collection_rejects_model_url(tmp_path: Path) -> None:
    result = HuggingFaceDatasetConnector(
        GatedDatasetClient(),
        cache_dir=tmp_path,
    ).collect("https://huggingface.co/example/model")

    assert result.access_status == AccessStatus.ERROR
    assert result.error == "Input is not a valid Hugging Face dataset URL"
