"""Parse existing MOT model YAML into the scorer input contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from model_openness_tool.domain import FrameworkCatalog, ModelInput


def load_model_yaml(path: Path, catalog: FrameworkCatalog) -> ModelInput:
    payload: Any = yaml.safe_load(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"Model YAML must contain a mapping: {path}")

    release = payload.get("release", payload)
    if not isinstance(release, dict):
        raise ValueError(f"Model YAML release must contain a mapping: {path}")

    name = release.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Model YAML release.name must be a non-empty string: {path}")

    global_licenses: dict[str, str | None] = {}
    license_section = release.get("license", {}) or {}
    if not isinstance(license_section, dict):
        raise ValueError(f"Model YAML release.license must contain a mapping: {path}")
    for scope, assignment in license_section.items():
        if not isinstance(assignment, dict):
            continue
        global_licenses[str(scope)] = _normalize_license(assignment.get("name"))

    included: set[int] = set()
    component_licenses: dict[int, str | None] = {}
    components = release.get("components", []) or []
    if not isinstance(components, list):
        raise ValueError(f"Model YAML release.components must contain a list: {path}")

    for component_data in components:
        if not isinstance(component_data, dict):
            raise ValueError(f"Model YAML contains a non-mapping component: {path}")
        component_name = component_data.get("name")
        if not isinstance(component_name, str):
            raise ValueError(f"Model YAML component name must be a string: {path}")
        try:
            component = catalog.component_named(component_name)
        except KeyError as error:
            raise ValueError(str(error)) from error
        included.add(component.id)
        if "license" in component_data:
            component_licenses[component.id] = _normalize_license(component_data.get("license"))

    return ModelInput(
        name=name,
        included_component_ids=frozenset(included),
        global_licenses=global_licenses,
        component_licenses=component_licenses,
    )


def _normalize_license(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or value == "unlicensed":
        return None
    return value.strip()
