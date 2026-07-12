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

    return app


def app_factory() -> FastAPI:
    return create_app()


def _optional_environment(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


app = app_factory()
