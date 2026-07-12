"""Command-line interface for the MOT evaluator."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from model_openness_tool import __version__
from model_openness_tool.catalog import load_catalog
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
    registry = LicenseRegistry.from_mot_files(
        root / "web/modules/mof/licenses.json",
        root / "web/modules/mof/mof-licenses.json",
    )
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
