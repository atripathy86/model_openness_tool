"""FastAPI service boundary with optional bearer authentication."""

from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict

from model_openness_tool import __version__
from model_openness_tool.catalog import load_catalog
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.jobs import (
    EvaluationJob,
    EvaluationJobRequest,
    EvaluationJobSummary,
    JobQueue,
    JobStatus,
    summarize_job,
)
from model_openness_tool.persistence import Database


@dataclass(frozen=True)
class ApiSettings:
    database_url: str | None = None
    bearer_token: str | None = None

    @classmethod
    def from_environment(cls) -> ApiSettings:
        return cls(
            database_url=_optional_environment("DATABASE_URL"),
            bearer_token=_optional_environment("MOT_API_BEARER_TOKEN"),
        )


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    version: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    database_configured: bool


class JobListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[EvaluationJobSummary, ...]


def create_app(
    settings: ApiSettings | None = None,
    *,
    database: Database | None = None,
    catalog: FrameworkCatalog | None = None,
) -> FastAPI:
    resolved_settings = settings or ApiSettings.from_environment()
    resolved_database = database or (
        Database(resolved_settings.database_url) if resolved_settings.database_url else None
    )
    resolved_catalog = catalog or load_catalog()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if resolved_database is not None:
                resolved_database.dispose()

    app = FastAPI(
        title="Model Openness Tool API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = resolved_database

    def authorize(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = resolved_settings.bearer_token
        if expected is None:
            return
        scheme, separator, credential = (authorization or "").partition(" ")
        if (
            separator != " "
            or scheme.casefold() != "bearer"
            or not hmac.compare_digest(credential, expected)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def jobs() -> JobQueue:
        if resolved_database is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is not configured",
            )
        return JobQueue(resolved_database)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/ready", response_model=ReadinessResponse)
    def ready() -> ReadinessResponse:
        return ReadinessResponse(
            ready=resolved_database.ready() if resolved_database is not None else False,
            database_configured=resolved_database is not None,
        )

    @app.get(
        "/v1/catalog",
        response_model=FrameworkCatalog,
        dependencies=[Depends(authorize)],
    )
    def catalog_endpoint() -> FrameworkCatalog:
        return resolved_catalog

    @app.post(
        "/v1/jobs",
        response_model=EvaluationJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(authorize)],
    )
    def submit_job(request: EvaluationJobRequest) -> EvaluationJob:
        return jobs().submit(request)

    @app.get(
        "/v1/jobs",
        response_model=JobListResponse,
        dependencies=[Depends(authorize)],
    )
    def list_jobs(
        job_status: JobStatus | None = None,
        limit: int = 100,
    ) -> JobListResponse:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        return JobListResponse(
            items=tuple(summarize_job(job) for job in jobs().list(job_status, limit=limit))
        )

    @app.get(
        "/v1/jobs/{job_id}",
        response_model=EvaluationJob,
        dependencies=[Depends(authorize)],
    )
    def get_job(job_id: str) -> EvaluationJob:
        job = jobs().get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Evaluation job was not found")
        return job

    return app


def app_factory() -> FastAPI:
    return create_app()


def _optional_environment(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


app = app_factory()
