"""Load the versioned Model Openness Framework component catalog."""

from __future__ import annotations

from hashlib import sha256
from importlib.resources import files
from typing import Any

import yaml

from model_openness_tool.domain import FrameworkCatalog


def load_catalog(version: str = "1.0") -> FrameworkCatalog:
    resource = files("model_openness_tool.catalogs").joinpath(f"mof-{version}.yaml")
    raw = resource.read_bytes()
    payload: Any = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"Catalog mof-{version}.yaml must contain a mapping")
    payload["catalog_sha256"] = sha256(raw).hexdigest()
    return FrameworkCatalog.model_validate(payload)
