"""Command-line interface for the MOT evaluator."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import timedelta
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
from model_openness_tool.jobs import (
    EvaluationJobRequest,
    JobQueue,
    JobStatus,
    WorkerResult,
    summarize_job,
)
from model_openness_tool.licenses import LicenseRegistry
from model_openness_tool.llm_evaluation import evaluate_extractor, load_evaluation_set
from model_openness_tool.llm_extraction import (
    ExtractionStatus,
    LlmEvidenceExtractor,
    OpenAiCompatibleClient,
)
from model_openness_tool.logging_config import configure_json_logging
from model_openness_tool.model_yaml import load_model_yaml
from model_openness_tool.persistence import Database
from model_openness_tool.review_store import (
    ReviewDecision,
    ReviewListResult,
    ReviewStatus,
    ReviewStore,
    load_extraction_report,
)
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


@app.command("llm-eval")
def evaluate_llm(
    evaluation_file: Annotated[
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
    """Measure LLM proposal precision, recall, and citation validity."""
    resolved_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    if resolved_base_url is None:
        raise typer.BadParameter("Set OPENAI_BASE_URL or pass --base-url")
    try:
        evaluation_set = load_evaluation_set(evaluation_file)
    except (OSError, ValidationError) as error:
        raise typer.BadParameter(f"Invalid labeled evaluation set: {error}") from error
    report = evaluate_extractor(
        evaluation_set,
        client=OpenAiCompatibleClient(
            base_url=resolved_base_url,
            api_key=os.environ.get("OPENAI_API_KEY"),
            model=model,
        ),
        catalog=load_catalog(),
    )
    _emit_json(report, output)
    if not report.passed:
        raise typer.Exit(code=2)


@app.command("review-import")
def review_import(
    extraction_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    database: Annotated[
        Path,
        typer.Option("--database", dir_okay=False, help="Local SQLite review database."),
    ] = Path(".mot/review.db"),
) -> None:
    """Import accepted, citation-validated LLM proposals into the review queue."""
    try:
        report = load_extraction_report(extraction_file)
    except (OSError, ValueError, ValidationError) as error:
        raise typer.BadParameter(f"Invalid LLM extraction report: {error}") from error
    result = ReviewStore(database).import_report(report)
    typer.echo(result.model_dump_json(indent=2))


@app.command("review-list")
def review_list(
    database: Annotated[
        Path,
        typer.Option("--database", dir_okay=False, help="Local SQLite review database."),
    ] = Path(".mot/review.db"),
    status: Annotated[
        ReviewStatus | None,
        typer.Option("--status", help="Filter by current review status."),
    ] = None,
) -> None:
    """List queued LLM evidence proposals and their latest review status."""
    result = ReviewListResult(
        database=str(database),
        items=ReviewStore(database).list_items(status),
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command("review-decide")
def review_decide(
    evidence_id: Annotated[str, typer.Argument(help="Queued evidence identifier.")],
    decision: Annotated[
        ReviewDecision,
        typer.Option("--decision", help="Accept or reject the evidence proposal."),
    ],
    reviewer: Annotated[
        str,
        typer.Option("--reviewer", help="Reviewer identity recorded in the audit event."),
    ],
    reason: Annotated[
        str,
        typer.Option("--reason", help="Required review rationale."),
    ],
    database: Annotated[
        Path,
        typer.Option("--database", dir_okay=False, help="Local SQLite review database."),
    ] = Path(".mot/review.db"),
) -> None:
    """Append an immutable accept or reject event for queued evidence."""
    try:
        event = ReviewStore(database).append_decision(
            evidence_id,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(event.model_dump_json(indent=2))


@app.command("job-submit")
def job_submit(
    model_id: Annotated[str, typer.Argument(help="Hugging Face model ID.")],
    revision: Annotated[
        str | None,
        typer.Option("--revision", help="Optional branch, tag, or commit to pin."),
    ] = None,
    max_attempts: Annotated[
        int,
        typer.Option("--max-attempts", min=1, max=10, help="Maximum worker attempts."),
    ] = 3,
) -> None:
    """Submit a durable PostgreSQL evaluation job."""
    database = Database(_required_environment("DATABASE_URL"))
    try:
        job = JobQueue(database).submit(
            EvaluationJobRequest(
                model_id=model_id,
                revision=revision,
                max_attempts=max_attempts,
            )
        )
        typer.echo(job.model_dump_json(indent=2))
    finally:
        database.dispose()


@app.command("job-list")
def job_list(
    status: Annotated[
        JobStatus | None,
        typer.Option("--status", help="Filter by durable job status."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=500, help="Maximum jobs to return."),
    ] = 100,
) -> None:
    """List durable PostgreSQL evaluation jobs."""
    database = Database(_required_environment("DATABASE_URL"))
    try:
        jobs = JobQueue(database).list(status, limit=limit)
        typer.echo(
            json.dumps(
                [summarize_job(job).model_dump(mode="json") for job in jobs],
                indent=2,
            )
        )
    finally:
        database.dispose()


@app.command("job-retry")
def job_retry(
    job_id: Annotated[str, typer.Argument(help="Terminally failed evaluation job ID.")],
) -> None:
    """Requeue a failed job with one additional attempt."""
    database = Database(_required_environment("DATABASE_URL"))
    try:
        try:
            job = JobQueue(database).retry(job_id)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        typer.echo(job.model_dump_json(indent=2))
    finally:
        database.dispose()


@app.command("worker")
def run_worker(
    once: Annotated[
        bool,
        typer.Option("--once/--loop", help="Process at most one job or poll continuously."),
    ] = True,
    worker_id: Annotated[
        str | None,
        typer.Option("--worker-id", help="Worker identity stored on claimed jobs."),
    ] = None,
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=0.1, max=60.0, help="Idle loop delay."),
    ] = 2.0,
    heartbeat_seconds: Annotated[
        float,
        typer.Option(
            "--heartbeat-seconds",
            min=1.0,
            max=300.0,
            help="Interval for refreshing the running-job lease.",
        ),
    ] = 30.0,
    stale_seconds: Annotated[
        float,
        typer.Option(
            "--stale-seconds",
            min=2.0,
            help="Recover running jobs whose heartbeat is older than this duration.",
        ),
    ] = 3600.0,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", file_okay=False, help="Local Hugging Face cache."),
    ] = Path(".hf-cache"),
) -> None:
    """Claim and execute durable evaluation jobs without Prefect."""
    if heartbeat_seconds >= stale_seconds:
        raise typer.BadParameter("--heartbeat-seconds must be less than --stale-seconds")
    configure_json_logging(os.environ.get("MOT_LOG_LEVEL", "INFO"))
    logger = logging.getLogger("model_openness_tool.worker")
    database = Database(_required_environment("DATABASE_URL"))
    queue = JobQueue(database)
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    try:
        recovery = queue.recover_stale(timedelta(seconds=stale_seconds))
        logger.info(
            "worker started",
            extra={
                "event": "worker_started",
                "worker_id": identity,
                "requeued_jobs": recovery.requeued_count,
                "failed_jobs": recovery.failed_count,
            },
        )
        while True:
            job = queue.claim(identity)
            if job is None:
                if once:
                    typer.echo(WorkerResult(processed=False).model_dump_json(indent=2))
                    return
                time.sleep(poll_seconds)
                continue
            logger.info(
                "job claimed",
                extra={
                    "event": "job_claimed",
                    "job_id": job.job_id,
                    "worker_id": identity,
                    "attempt": job.attempts,
                },
            )
            stop_heartbeat = threading.Event()
            heartbeat = threading.Thread(
                target=_heartbeat_job,
                args=(queue, job.job_id, identity, heartbeat_seconds, stop_heartbeat),
                daemon=True,
                name=f"mot-heartbeat-{job.job_id}",
            )
            heartbeat.start()
            try:
                result = _execute_evaluation_job(job.request, cache_dir)
                completed = queue.succeed(job.job_id, result.model_dump(mode="json"))
                logger.info(
                    "job succeeded",
                    extra={"event": "job_succeeded", "job_id": job.job_id},
                )
            except Exception as error:
                completed = queue.fail(job.job_id, f"{type(error).__name__}: {error}")
                logger.exception(
                    "job execution failed",
                    extra={
                        "event": "job_failed",
                        "job_id": job.job_id,
                        "status": completed.status.value,
                    },
                )
            finally:
                stop_heartbeat.set()
                heartbeat.join()
            typer.echo(
                WorkerResult(
                    processed=True,
                    job_id=completed.job_id,
                    status=completed.status,
                    attempts=completed.attempts,
                    error=completed.error,
                ).model_dump_json(indent=2)
            )
            if once:
                return
    finally:
        database.dispose()


@app.command("job-recover")
def job_recover(
    stale_seconds: Annotated[
        float,
        typer.Option(
            "--stale-seconds",
            min=1.0,
            help="Recover running jobs whose heartbeat is older than this duration.",
        ),
    ] = 3600.0,
) -> None:
    """Recover abandoned running jobs using their heartbeat lease."""
    configure_json_logging(os.environ.get("MOT_LOG_LEVEL", "INFO"))
    database = Database(_required_environment("DATABASE_URL"))
    try:
        result = JobQueue(database).recover_stale(timedelta(seconds=stale_seconds))
        logging.getLogger("model_openness_tool.worker").info(
            "stale-job recovery completed",
            extra={
                "event": "stale_jobs_recovered",
                "requeued_jobs": result.requeued_count,
                "failed_jobs": result.failed_count,
            },
        )
        typer.echo(result.model_dump_json(indent=2))
    finally:
        database.dispose()


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


def _heartbeat_job(
    queue: JobQueue,
    job_id: str,
    worker_id: str,
    interval_seconds: float,
    stop: threading.Event,
) -> None:
    logger = logging.getLogger("model_openness_tool.worker")
    while not stop.wait(interval_seconds):
        try:
            if not queue.heartbeat(job_id, worker_id):
                logger.warning(
                    "job heartbeat lease was lost",
                    extra={"event": "heartbeat_lost", "job_id": job_id},
                )
                return
        except Exception:
            logger.exception(
                "job heartbeat failed",
                extra={"event": "heartbeat_failed", "job_id": job_id},
            )


def _execute_evaluation_job(request: EvaluationJobRequest, cache_dir: Path) -> EvaluationRun:
    collection = _connector(cache_dir, os.environ.get("HF_TOKEN")).collect(
        request.model_id,
        request.revision,
    )
    assessment = None
    if collection.report is not None:
        root = find_repository_root()
        assessment = ProvisionalEvaluator(load_catalog(), _license_registry(root)).assess(
            collection.report
        )
    return EvaluationRun(collection=collection, assessment=assessment)


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


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise typer.BadParameter(f"Environment variable {name} is required")
    return value.strip()
