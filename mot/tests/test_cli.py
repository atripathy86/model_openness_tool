import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from model_openness_tool import cli
from model_openness_tool.connectors.arxiv import ArxivPaperMetadata
from model_openness_tool.connectors.github import (
    GitHubRepositoryMetadata,
    GitHubTree,
    GitHubTreeEntry,
)
from model_openness_tool.connectors.huggingface import HubFileMetadata, HubModelMetadata
from model_openness_tool.connectors.huggingface_dataset import (
    DatasetFileMetadata,
    DatasetMetadata,
)

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(cli.app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_catalog_command() -> None:
    result = runner.invoke(cli.app, ["catalog"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["framework"]["version"] == "1.0"
    assert len(payload["components"]) == 17


def test_evaluate_yaml_command(repository_root: Path) -> None:
    fixture = (
        repository_root / "Test_Data/Class3TTestFile_C1_33%-C2_60%-C3_100%_6C_1G_6L_6V_0I_6T.yml"
    )
    result = runner.invoke(
        cli.app,
        ["evaluate-yaml", str(fixture), "--repository-root", str(repository_root)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["classification"] == 3
    assert payload["progress"]["3"] == 100.0


def test_collect_command_reads_token_from_environment_and_writes_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
) -> None:
    card = tmp_path / "README.md"
    card.write_text(
        (
            "# Example\n\nSource: https://github.com/example/model\n\n"
            "Data: https://huggingface.co/datasets/example/data\n\n"
            "Paper: https://arxiv.org/abs/1912.01703"
        ),
        encoding="utf-8",
    )
    captured_token: list[str | None] = []

    class FakeSdkClient:
        def __init__(self, token: str | None = None) -> None:
            captured_token.append(token)

        def get_model(self, model_id: str, revision: str | None) -> HubModelMetadata:
            return HubModelMetadata(
                model_id=model_id,
                revision="a" * 40,
                private=False,
                gated=False,
                pipeline_tag=None,
                tags=(),
                declared_license=None,
            )

        def list_files(self, model_id: str, revision: str) -> Iterable[HubFileMetadata]:
            return (HubFileMetadata("README.md", card.stat().st_size, "readme"),)

        def download_file(
            self,
            model_id: str,
            revision: str,
            path: str,
            cache_dir: Path,
        ) -> Path:
            return card

    class FakeGitHubClient:
        def __init__(self, token: str | None = None) -> None:
            assert token == "github-secret"

        def get_repository(self, owner: str, repository: str) -> GitHubRepositoryMetadata:
            return GitHubRepositoryMetadata(
                identifier=f"{owner}/{repository}",
                default_branch="main",
                private=False,
                archived=False,
            )

        def resolve_commit(self, owner: str, repository: str, revision: str) -> str:
            return "b" * 40

        def get_tree(self, owner: str, repository: str, revision: str) -> GitHubTree:
            return GitHubTree(
                entries=(GitHubTreeEntry("train.py", 10, "train"),),
                truncated=False,
            )

    class FakeDatasetClient:
        def __init__(self, token: str | None = None) -> None:
            assert token == "secret-token"

        def get_dataset(self, dataset_id: str, revision: str | None) -> DatasetMetadata:
            return DatasetMetadata(
                dataset_id=dataset_id,
                revision="d" * 40,
                private=False,
                gated=False,
                tags=(),
                declared_licenses=("cc-by-4.0",),
            )

        def list_files(self, dataset_id: str, revision: str) -> Iterable[DatasetFileMetadata]:
            return (DatasetFileMetadata("data/train.parquet", 100, "data"),)

        def download_file(
            self,
            dataset_id: str,
            revision: str,
            path: str,
            cache_dir: Path,
        ) -> Path:
            return card

    class FakeArxivClient:
        def get_paper(self, paper_id: str) -> ArxivPaperMetadata:
            assert paper_id == "1912.01703"
            return ArxivPaperMetadata(
                paper_id="1912.01703v2",
                title="Example paper",
                authors=("A. Author",),
                abstract="Example abstract.",
                published_at=datetime(2019, 12, 4, tzinfo=UTC),
                updated_at=datetime(2020, 1, 1, tzinfo=UTC),
                declared_license=None,
            )

    monkeypatch.setattr(cli, "HuggingFaceSdkClient", FakeSdkClient)
    monkeypatch.setattr(cli, "GitHubRestClient", FakeGitHubClient)
    monkeypatch.setattr(cli, "HuggingFaceDatasetSdkClient", FakeDatasetClient)
    monkeypatch.setattr(cli, "ArxivApiClient", FakeArxivClient)
    output = tmp_path / "result.json"
    result = runner.invoke(
        cli.app,
        [
            "collect",
            "example/model",
            "--token-env",
            "TEST_HF_TOKEN",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--output",
            str(output),
        ],
        env={"TEST_HF_TOKEN": "secret-token"},
    )

    assert result.exit_code == 0
    assert captured_token == ["secret-token"]
    serialized = output.read_text(encoding="utf-8")
    assert "secret-token" not in serialized
    payload = json.loads(serialized)
    assert payload["access_status"] == "available"
    assert payload["report"]["snapshot"]["resolved_revision"] == "a" * 40

    assessment_output = tmp_path / "assessment.json"
    assess_result = runner.invoke(
        cli.app,
        [
            "assess",
            str(output),
            "--repository-root",
            str(repository_root),
            "--output",
            str(assessment_output),
        ],
    )
    assert assess_result.exit_code == 0
    assessment = json.loads(assessment_output.read_text(encoding="utf-8"))
    assert assessment["kind"] == "provisional"
    assert assessment["confirmed"]["classification"] == 0

    evaluation_output = tmp_path / "evaluation.json"
    evaluate_result = runner.invoke(
        cli.app,
        [
            "evaluate",
            "example/model",
            "--repository-root",
            str(repository_root),
            "--token-env",
            "TEST_HF_TOKEN",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--output",
            str(evaluation_output),
            "--follow-github",
            "--github-token-env",
            "TEST_GITHUB_TOKEN",
            "--follow-datasets",
            "--follow-papers",
        ],
        env={
            "TEST_HF_TOKEN": "secret-token",
            "TEST_GITHUB_TOKEN": "github-secret",
        },
    )
    assert evaluate_result.exit_code == 0
    assert captured_token == ["secret-token", "secret-token"]
    evaluation = json.loads(evaluation_output.read_text(encoding="utf-8"))
    assert evaluation["collection"]["access_status"] == "available"
    assert len(evaluation["linked_github"]) == 1
    assert len(evaluation["linked_datasets"]) == 1
    assert len(evaluation["linked_papers"]) == 1
    assert evaluation["linked_github"][0]["snapshot"]["resolved_revision"] == "b" * 40
    assert evaluation["linked_datasets"][0]["snapshot"]["resolved_revision"] == "d" * 40
    assert evaluation["linked_papers"][0]["snapshot"]["resolved_revision"] == "v2"
    assert evaluation["assessment"]["kind"] == "provisional"
