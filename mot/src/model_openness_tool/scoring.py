"""Pure deterministic port of the current Drupal ModelEvaluator behavior."""

from __future__ import annotations

from dataclasses import dataclass, field

from model_openness_tool.domain import (
    ClassEvaluation,
    ComponentBuckets,
    EvaluationResult,
    FrameworkCatalog,
    ModelInput,
    ScoreReport,
)
from model_openness_tool.licenses import LicenseRegistry

TECHNICAL_REPORT_ID = 11
RESEARCH_PAPER_ID = 21

CLASS_LABELS = {
    0: "Unclassified",
    1: "Class I - Open Science Model",
    2: "Class II - Open Tooling Model",
    3: "Class III - Open Model",
}


@dataclass
class _WorkingClass:
    missing: list[int] = field(default_factory=list)
    included: list[int] = field(default_factory=list)
    invalid: list[int] = field(default_factory=list)
    unlicensed: list[int] = field(default_factory=list)
    optional: list[int] = field(default_factory=list)
    licenses: dict[int, str] = field(default_factory=dict)

    def status(self, component_id: int) -> str | None:
        for status in ("included", "invalid", "unlicensed"):
            if component_id in getattr(self, status):
                return status
        return None


class ModelEvaluator:
    def __init__(self, catalog: FrameworkCatalog, licenses: LicenseRegistry) -> None:
        self.catalog = catalog
        self.licenses = licenses

    def score(self, model: ModelInput) -> ScoreReport:
        evaluation = self.evaluate(model)
        progress = {mof_class: self._progress(mof_class, evaluation) for mof_class in (1, 2, 3)}
        classification = 0
        for mof_class in (3, 2, 1):
            if progress[mof_class] == 100.0:
                classification = mof_class

        return ScoreReport(
            model_name=model.name,
            framework_version=self.catalog.framework.version,
            catalog_version=self.catalog.catalog_version,
            catalog_sha256=self.catalog.catalog_sha256,
            license_catalog_sha256=self.licenses.catalog_sha256,
            classification=classification,
            classification_label=CLASS_LABELS[classification],
            progress=progress,
            total_progress=sum(progress.values()) / 3,
            evaluation=evaluation,
        )

    def evaluate(self, model: ModelInput) -> EvaluationResult:
        classes: dict[int, _WorkingClass] = {}
        required: list[int] = []
        optional: list[int] = []
        not_type_appropriate: list[int] = []

        for mof_class in (3, 2, 1):
            current = _WorkingClass()
            classes[mof_class] = current
            required.extend(self.catalog.required_for_class(mof_class))
            optional.extend(self.catalog.optional_for_class(mof_class))
            self._evaluate_components(
                model,
                current,
                required,
                "included",
                not_type_appropriate,
            )
            self._evaluate_components(
                model,
                current,
                optional,
                "optional",
                not_type_appropriate,
            )

        self._handle_technical_report_omission(classes)
        return EvaluationResult(
            classes={
                mof_class: ClassEvaluation(
                    components=ComponentBuckets(
                        missing=current.missing,
                        included=current.included,
                        invalid=current.invalid,
                        unlicensed=current.unlicensed,
                        optional=current.optional,
                    ),
                    licenses=current.licenses,
                )
                for mof_class, current in classes.items()
            },
            not_type_appropriate=not_type_appropriate,
        )

    def _evaluate_components(
        self,
        model: ModelInput,
        current: _WorkingClass,
        component_ids: list[int],
        successful_status: str,
        not_type_appropriate: list[int],
    ) -> None:
        for component_id in component_ids:
            if component_id not in model.included_component_ids:
                if successful_status == "included":
                    current.missing.append(component_id)
                continue

            component = self.catalog.component(component_id)
            license_id = self._resolve_license(model, component_id) or "unlicensed"
            is_open = self.licenses.is_open(license_id)
            type_appropriate = self.licenses.is_type_appropriate(
                license_id,
                component.content_type,
            )

            if is_open:
                getattr(current, successful_status).append(component_id)
                if not type_appropriate and component_id not in not_type_appropriate:
                    not_type_appropriate.append(component_id)
            elif license_id == "unlicensed":
                current.unlicensed.append(component_id)
            else:
                current.invalid.append(component_id)
            current.licenses[component_id] = license_id

    def _resolve_license(self, model: ModelInput, component_id: int) -> str | None:
        if component_id in model.component_licenses:
            return model.component_licenses[component_id]

        content_type = self.catalog.component(component_id).content_type.value
        type_license = model.global_licenses.get(content_type)
        if type_license:
            return type_license
        return model.global_licenses.get("distribution")

    def _handle_technical_report_omission(
        self,
        classes: dict[int, _WorkingClass],
    ) -> None:
        if classes[3].status(TECHNICAL_REPORT_ID) == "included":
            return

        research_status = classes[1].status(RESEARCH_PAPER_ID)
        if research_status is None:
            return

        for mof_class in (1, 2, 3):
            current = classes[mof_class]
            if TECHNICAL_REPORT_ID in current.missing:
                current.missing.remove(TECHNICAL_REPORT_ID)

        license_id = classes[1].licenses.get(RESEARCH_PAPER_ID, "")
        for mof_class in (2, 3):
            current = classes[mof_class]
            getattr(current, research_status).append(RESEARCH_PAPER_ID)
            current.licenses[RESEARCH_PAPER_ID] = license_id

    def _progress(self, mof_class: int, evaluation: EvaluationResult) -> float:
        total = 0
        included = 0
        for current_class in range(3, mof_class - 1, -1):
            total += len(self.catalog.required_for_class(current_class))
            included = len(evaluation.classes[current_class].components.included)
            if included < total:
                if current_class > mof_class:
                    return 0.0
                break

        class_one = evaluation.classes[1].components
        if (
            mof_class == 1
            and TECHNICAL_REPORT_ID not in class_one.included
            and RESEARCH_PAPER_ID in class_one.included
        ):
            total -= 1

        return min((included / total) * 100, 100.0)
