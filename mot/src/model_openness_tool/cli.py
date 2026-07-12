"""Command-line interface for the MOT evaluator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, TypeAdapter, ValidationError

from model_openness_tool import __version__
from model_openness_tool.assessment import EvaluationRun, ProvisionalEvaluator
from model_openness_tool.catalog import load_catalog
from model_openness_tool.connectors.arxiv import ArxivApiClient, ArxivConnector
from model_openness_tool.connectors.documentation import (
    DocumentationConnector,
    DocumentationHttpClient,
)
from model_openness_tool.connectors.doi import CrossrefClient, DoiConnector
from model_openness_tool.connectors.github import GitHubConnector, GitHubRestClient
from model_openness_tool.connectors.huggingface import HuggingFaceConnector, HuggingFaceSdkClient
from model_openness_tool.connectors.huggingface_dataset import (
    HuggingFaceDatasetConnector,
    HuggingFaceDatasetSdkClient,
)
from model_openness_tool.connectors.pdf import MinerUBackend, PdfConnector
from model_openness_tool.evidence import (
    AccessStatus,
    CollectionResult,
    DatasetCollectionResult,
    DatasetEvidenceReport,
    DocumentationCollectionResult,
    DocumentationEvidenceReport,
    GitHubCollectionResult,
    GitHubEvidenceReport,
    LinkedSourceType,
    PaperCollectionResult,
    PaperEvidenceReport,
    PdfCollectionResult,
    PdfEvidenceReport,
)
from model_openness_tool.licenses import LicenseRegistry
from model_openness_tool.llm_extraction import (
    ExtractionStatus,
    LlmEvidenceExtractor,
    OpenAiCompatibleClient,
)
from model_openness_tool.model_yaml import load_model_yaml
from model_openness_tool.scoring import ModelEvaluator
from model_openness_tool.source_detectors import merge_evidence_reports

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


@app.command("collect-dataset")
def collect_dataset(
    dataset_url: Annotated[
        str,
        typer.Argument(
            help="Hugging Face dataset URL, such as https://huggingface.co/datasets/org/data."
        ),
    ],
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
        typer.Option("--cache-dir", file_okay=False, help="Local Hugging Face cache."),
    ] = Path(".hf-cache"),
    token_env: Annotated[
        str,
        typer.Option("--token-env", help="Environment variable containing a Hugging Face token."),
    ] = "HF_TOKEN",
) -> None:
    """Collect a revision-pinned dataset manifest and bounded data card."""
    connector = HuggingFaceDatasetConnector(
        HuggingFaceDatasetSdkClient(token=os.environ.get(token_env)),
        cache_dir=cache_dir,
    )
    result = connector.collect(dataset_url, revision)
    _emit_json(result, output)
    if result.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("collect-paper")
def collect_paper(
    paper: Annotated[
        str,
        typer.Argument(
            help=(
                "arXiv or DOI paper identifier/URL, such as "
                "https://arxiv.org/abs/1912.01703 or https://doi.org/10.18653/v1/n19-1423."
            ),
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
) -> None:
    """Collect bounded paper metadata or a content-addressed generic PDF."""
    result = _collect_paper(paper)
    _emit_json(result, output)
    if result.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("collect-pdf")
def collect_pdf(
    pdf_url: Annotated[
        str,
        typer.Argument(help="Public HTTP(S) PDF URL."),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
    mineru_url: Annotated[
        str | None,
        typer.Option(
            "--mineru-url",
            help="OpenAI-compatible MinerU VLM server; defaults to MINERU_SERVER_URL.",
        ),
    ] = None,
    backend: Annotated[
        MinerUBackend,
        typer.Option("--backend", help="MinerU remote extraction backend."),
    ] = MinerUBackend.VLM_HTTP_CLIENT,
    pdf_fallback: Annotated[
        bool,
        typer.Option(
            "--pdf-fallback/--no-pdf-fallback",
            help="Use bounded pypdf text extraction when MinerU is unavailable.",
        ),
    ] = True,
) -> None:
    """Collect bounded, content-addressed MinerU Markdown from a public PDF."""
    result = PdfConnector(
        DocumentationHttpClient(),
        backend=backend,
        server_url=mineru_url or os.environ.get("MINERU_SERVER_URL", "http://127.0.0.1:30000"),
        allow_fallback=pdf_fallback,
    ).collect(pdf_url)
    _emit_json(result, output)
    if result.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("collect-doc")
def collect_documentation(
    documentation_url: Annotated[
        str,
        typer.Argument(help="Public HTTP(S) documentation page URL."),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
) -> None:
    """Collect a bounded, content-addressed documentation snapshot."""
    result = DocumentationConnector(DocumentationHttpClient()).collect(documentation_url)
    _emit_json(result, output)
    if result.access_status != AccessStatus.AVAILABLE:
        raise typer.Exit(code=2)


@app.command("extract-llm")
def extract_llm(
    evidence_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write JSON to this file."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="OpenAI-compatible API base URL; defaults to OPENAI_BASE_URL.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model ID; discover the first endpoint model if omitted."),
    ] = None,
) -> None:
    """Extract schema-validated, citation-checked LLM review proposals."""
    resolved_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    if resolved_base_url is None:
        raise typer.BadParameter("Set OPENAI_BASE_URL or pass --base-url")
    api_key = os.environ.get("OPENAI_API_KEY")
    try:
        collection: DocumentationCollectionResult | PdfCollectionResult = TypeAdapter(
            DocumentationCollectionResult | PdfCollectionResult
        ).validate_json(evidence_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise typer.BadParameter(f"Invalid document evidence report: {error}") from error
    if collection.snapshot is None:
        raise typer.BadParameter("Evidence report does not contain a collected document snapshot")
    result = LlmEvidenceExtractor(
        OpenAiCompatibleClient(base_url=resolved_base_url, api_key=api_key, model=model),
        load_catalog(),
    ).extract(
        collection.snapshot.text,
        source_url=collection.snapshot.final_url,
        source_revision=collection.snapshot.resolved_revision,
    )
    _emit_json(result, output)
    if result.status == ExtractionStatus.ERROR:
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
    follow_github: Annotated[
        bool,
        typer.Option(
            "--follow-github/--no-follow-github",
            help="Collect and merge pinned GitHub repositories linked by the model card.",
        ),
    ] = False,
    github_token_env: Annotated[
        str,
        typer.Option(
            "--github-token-env",
            help="Environment variable containing a GitHub token.",
        ),
    ] = "GITHUB_TOKEN",
    max_linked_github: Annotated[
        int,
        typer.Option(
            "--max-linked-github",
            min=0,
            max=10,
            help="Maximum linked GitHub repositories to collect.",
        ),
    ] = 3,
    follow_datasets: Annotated[
        bool,
        typer.Option(
            "--follow-datasets/--no-follow-datasets",
            help="Collect and merge pinned Hugging Face datasets linked by the model card.",
        ),
    ] = False,
    max_linked_datasets: Annotated[
        int,
        typer.Option(
            "--max-linked-datasets",
            min=0,
            max=10,
            help="Maximum linked Hugging Face datasets to collect.",
        ),
    ] = 3,
    follow_papers: Annotated[
        bool,
        typer.Option(
            "--follow-papers/--no-follow-papers",
            help="Collect and merge arXiv and DOI papers linked by the model card.",
        ),
    ] = False,
    max_linked_papers: Annotated[
        int,
        typer.Option(
            "--max-linked-papers",
            min=0,
            max=10,
            help="Maximum linked arXiv or DOI papers to collect.",
        ),
    ] = 3,
    follow_documentation: Annotated[
        bool,
        typer.Option(
            "--follow-documentation/--no-follow-documentation",
            help="Collect bounded documentation pages linked by the model card.",
        ),
    ] = False,
    max_linked_documentation: Annotated[
        int,
        typer.Option(
            "--max-linked-documentation",
            min=0,
            max=10,
            help="Maximum linked documentation pages to collect.",
        ),
    ] = 3,
) -> None:
    """Collect evidence and emit a conservative provisional MOF assessment."""
    collection = _connector(cache_dir, os.environ.get(token_env)).collect(model_id, revision)
    linked_github: tuple[GitHubCollectionResult, ...] = ()
    linked_datasets: tuple[DatasetCollectionResult, ...] = ()
    linked_papers: tuple[PaperCollectionResult | PdfCollectionResult, ...] = ()
    linked_documentation: tuple[DocumentationCollectionResult, ...] = ()
    assessment = None
    if collection.report is not None:
        assessment_report = collection.report
        if follow_github:
            github_connector = GitHubConnector(
                GitHubRestClient(token=os.environ.get(github_token_env))
            )
            github_sources = [
                source
                for source in collection.report.linked_sources
                if source.source_type == LinkedSourceType.GITHUB_REPOSITORY
            ][:max_linked_github]
            linked_github = tuple(
                github_connector.collect(source.canonical_url) for source in github_sources
            )
            linked_reports: list[
                GitHubEvidenceReport
                | DatasetEvidenceReport
                | PaperEvidenceReport
                | PdfEvidenceReport
                | DocumentationEvidenceReport
            ] = []
            for linked_result in linked_github:
                if linked_result.evidence_report is not None:
                    linked_reports.append(linked_result.evidence_report)
        else:
            linked_reports = []
        if follow_datasets:
            dataset_connector = HuggingFaceDatasetConnector(
                HuggingFaceDatasetSdkClient(token=os.environ.get(token_env)),
                cache_dir=cache_dir,
            )
            dataset_sources = [
                source
                for source in collection.report.linked_sources
                if source.source_type == LinkedSourceType.HUGGINGFACE_DATASET
            ][:max_linked_datasets]
            linked_datasets = tuple(
                dataset_connector.collect(source.canonical_url) for source in dataset_sources
            )
            for dataset_result in linked_datasets:
                if dataset_result.evidence_report is not None:
                    linked_reports.append(dataset_result.evidence_report)
        if follow_papers:
            paper_sources = [
                source
                for source in collection.report.linked_sources
                if source.source_type == LinkedSourceType.PAPER
                and (
                    source.identifier.startswith("arxiv:")
                    or source.identifier.startswith("doi:")
                    or source.canonical_url.casefold().split("?", 1)[0].endswith(".pdf")
                )
            ][:max_linked_papers]
            linked_papers = tuple(_collect_paper(source.canonical_url) for source in paper_sources)
            for paper_result in linked_papers:
                if paper_result.evidence_report is not None:
                    linked_reports.append(paper_result.evidence_report)
        if follow_documentation:
            documentation_connector = DocumentationConnector(DocumentationHttpClient())
            documentation_sources = [
                source
                for source in collection.report.linked_sources
                if source.source_type == LinkedSourceType.DOCUMENTATION
            ][:max_linked_documentation]
            linked_documentation = tuple(
                documentation_connector.collect(source.canonical_url)
                for source in documentation_sources
            )
            for documentation_result in linked_documentation:
                if documentation_result.evidence_report is not None:
                    linked_reports.append(documentation_result.evidence_report)
        assessment_report = merge_evidence_reports(
            assessment_report,
            tuple(linked_reports),
        )
        root = repository_root or find_repository_root()
        assessment = ProvisionalEvaluator(load_catalog(), _license_registry(root)).assess(
            assessment_report
        )
    run = EvaluationRun(
        collection=collection,
        linked_github=linked_github,
        linked_datasets=linked_datasets,
        linked_papers=linked_papers,
        linked_documentation=linked_documentation,
        assessment=assessment,
    )
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


def _collect_paper(paper: str) -> PaperCollectionResult | PdfCollectionResult:
    normalized = paper.strip().casefold()
    if normalized.startswith(("doi:", "10.")) or "doi.org/" in normalized:
        return DoiConnector(CrossrefClient()).collect(paper)
    if normalized.startswith(("http://", "https://")) and normalized.split("?", 1)[0].endswith(
        ".pdf"
    ):
        return PdfConnector(
            DocumentationHttpClient(),
            server_url=os.environ.get("MINERU_SERVER_URL", "http://127.0.0.1:30000"),
        ).collect(paper)
    return ArxivConnector(ArxivApiClient()).collect(paper)


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
