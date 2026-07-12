"""Typed domain models shared by the catalog, parser, and scoring engine."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContentType(StrEnum):
    CODE = "code"
    DATA = "data"
    DOCUMENT = "document"


class FrameworkMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    date: date


class ComponentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: int
    name: str
    description: str
    content_type: ContentType
    mof_class: int = Field(alias="class", ge=1, le=3)
    weight: int
    required: bool


class FrameworkCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog_version: str
    catalog_sha256: str
    source: str
    source_revision: str
    framework: FrameworkMetadata
    components: tuple[ComponentDefinition, ...]

    @model_validator(mode="after")
    def validate_unique_components(self) -> FrameworkCatalog:
        ids = [component.id for component in self.components]
        names = [component.name for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Component IDs must be unique")
        if len(names) != len(set(names)):
            raise ValueError("Component names must be unique")
        return self

    def component(self, component_id: int) -> ComponentDefinition:
        for component in self.components:
            if component.id == component_id:
                return component
        raise KeyError(f"Unknown component ID: {component_id}")

    def component_named(self, name: str) -> ComponentDefinition:
        for component in self.components:
            if component.name == name:
                return component
        raise KeyError(f"Unknown component name: {name}")

    def required_for_class(self, mof_class: int) -> tuple[int, ...]:
        return tuple(
            component.id
            for component in self.components
            if component.mof_class == mof_class and component.required
        )

    def optional_for_class(self, mof_class: int) -> tuple[int, ...]:
        return tuple(
            component.id
            for component in self.components
            if component.mof_class == mof_class and not component.required
        )


class ModelInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    included_component_ids: frozenset[int]
    global_licenses: dict[str, str | None] = Field(default_factory=dict)
    component_licenses: dict[int, str | None] = Field(default_factory=dict)


class ComponentBuckets(BaseModel):
    missing: list[int] = Field(default_factory=list)
    included: list[int] = Field(default_factory=list)
    invalid: list[int] = Field(default_factory=list)
    unlicensed: list[int] = Field(default_factory=list)
    optional: list[int] = Field(default_factory=list)


class ClassEvaluation(BaseModel):
    components: ComponentBuckets
    licenses: dict[int, str] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    classes: dict[int, ClassEvaluation]
    not_type_appropriate: list[int] = Field(default_factory=list)


class ScoreReport(BaseModel):
    model_name: str
    framework_version: str
    catalog_version: str
    catalog_sha256: str
    license_catalog_sha256: str
    classification: int
    classification_label: str
    progress: dict[int, float]
    total_progress: float
    evaluation: EvaluationResult
