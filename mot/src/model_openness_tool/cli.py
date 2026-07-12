"""Command-line interface for the MOT evaluator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ValidationError

from model_openness_tool import __version__
from model_openness_tool.assessment import EvaluationRun, ProvisionalEvaluator
from model_openness_tool.catalog import load_catalog
from model_openness_tool.connectors.github import GitHubConnector, GitHubRestClient
from model_openness_tool.connectors.huggingface import HuggingFaceConnector, HuggingFaceSdkClient
from model_openness_tool.evidence import AccessStatus, CollectionResult
from model_openness_tool.licenses import LicenseRegistry
from model_openness_tool.model_yaml import load_model_yaml
from model_openness_tool.scoring import ModelEvaluator

app = typer.Typer(
    name="mot",
    help="Evidence-backed Model Openness Framework evaluation.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the MOT Python package version."""
    typer.echo(__version__)


@app.command("catalog")
def show_catalog() -> None:
    """Print the active component catalog as JSON."""
    catalog = load_catalog()
    typer.echo(catalog.model_dump_json(indent=2, by_alias=True))


@app.command("collect")
def collect_model(
    model_id: Annotated[str, typer.Argument(help="Hugging Face model ID, such as org/model.")],
    revision: Annotated[
        str | None,
        typer.Option("--revision", help="Branch, tag, or commit to resolve and pin."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            file_okay=False,
            help="Local Hugging Face cache; model weights are not downloaded.",
        ),
    ] = Path(".hf-cache"),
    token_env: Annotated[
        str,
        typer.Option(
            "--token-env",
            help="Environment variable containing a Hugging Face token.",
        ),
    ] = "HF_TOKEN",
) -> None:
    """Collect a revision-pinned Hugging Face evidence snapshot."""
    token = os.environ.get(token_env)
    connector = _connector(cache_dir, token)
    result = connector.collect(model_id, revision)
    _emit_json(result, output)
    if result.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("collect-github")
def collect_github(
    repository_url: Annotated[
        str,
        typer.Argument(help="GitHub repository URL, such as https://github.com/org/repo."),
    ],
    revision: Annotated[
        str | None,
        typer.Option("--revision", help="Branch, tag, or commit to resolve and pin."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
    token_env: Annotated[
        str,
        typer.Option("--token-env", help="Environment variable containing a GitHub token."),
    ] = "GITHUB_TOKEN",
) -> None:
    """Collect a revision-pinned GitHub repository file manifest."""
    connector = GitHubConnector(GitHubRestClient(token=os.environ.get(token_env)))
    result = connector.collect(repository_url, revision)
    _emit_json(result, output)
    if result.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("assess")
def assess_evidence(
    evidence_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
    repository_root: Annotated[
        Path | None,
        typer.Option(
            "--repository-root",
            help="MOT repository root containing license catalogs.",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Create a provisional assessment from a saved collection report."""
    try:
        collection = CollectionResult.model_validate_json(evidence_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise typer.BadParameter(f"Invalid evidence report: {error}") from error
    if collection.report is None:
        raise typer.BadParameter("Evidence report does not contain a collected snapshot")
    root = repository_root or find_repository_root()
    assessment = ProvisionalEvaluator(load_catalog(), _license_registry(root)).assess(
        collection.report
    )
    _emit_json(assessment, output)


@app.command("evaluate")
def evaluate_model(
    model_id: Annotated[str, typer.Argument(help="Hugging Face model ID, such as org/model.")],
    revision: Annotated[
        str | None,
        typer.Option("--revision", help="Branch, tag, or commit to resolve and pin."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            file_okay=False,
            help="Local Hugging Face cache; model weights are not downloaded.",
        ),
    ] = Path(".hf-cache"),
    token_env: Annotated[
        str,
        typer.Option("--token-env", help="Environment variable containing a Hugging Face token."),
    ] = "HF_TOKEN",
    repository_root: Annotated[
        Path | None,
        typer.Option(
            "--repository-root",
            help="MOT repository root containing license catalogs.",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Collect evidence and emit a conservative provisional MOF assessment."""
    collection = _connector(cache_dir, os.environ.get(token_env)).collect(model_id, revision)
    assessment = None
    if collection.report is not None:
        root = repository_root or find_repository_root()
        assessment = ProvisionalEvaluator(load_catalog(), _license_registry(root)).assess(
            collection.report
        )
    run = EvaluationRun(collection=collection, assessment=assessment)
    _emit_json(run, output)
    if collection.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("evaluate-yaml")
def evaluate_yaml(
    model_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    repository_root: Annotated[
        Path | None,
        typer.Option(
            "--repository-root",
            help="MOT repository root containing web/modules/mof license catalogs.",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Evaluate an existing MOT model YAML with the parity scorer."""
    root = repository_root or find_repository_root()
    catalog = load_catalog()
    registry = _license_registry(root)
    model = load_model_yaml(model_file, catalog)
    report = ModelEvaluator(catalog, registry).score(model)
    typer.echo(report.model_dump_json(indent=2))


def find_repository_root(start: Path | None = None) -> Path:
    candidates: list[Path] = []
    for base in (start or Path.cwd(), Path(__file__).resolve()):
        candidates.extend((base, *base.parents))
    for candidate in candidates:
        if (candidate / "web/modules/mof/licenses.json").is_file():
            return candidate
    raise typer.BadParameter(
        "Could not locate the MOT repository root; pass --repository-root explicitly."
    )


def _connector(cache_dir: Path, token: str | None) -> HuggingFaceConnector:
    return HuggingFaceConnector(HuggingFaceSdkClient(token=token), cache_dir=cache_dir)


def _license_registry(root: Path) -> LicenseRegistry:
    return LicenseRegistry.from_mot_files(
        root / "web/modules/mof/licenses.json",
        root / "web/modules/mof/mof-licenses.json",
    )


def _emit_json(value: BaseModel, output: Path | None) -> None:
    serialized = value.model_dump_json(indent=2)
    if output is None:
        typer.echo(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{serialized}\n", encoding="utf-8")
