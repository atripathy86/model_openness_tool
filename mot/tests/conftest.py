from pathlib import Path

import pytest

from model_openness_tool.catalog import load_catalog
from model_openness_tool.domain import FrameworkCatalog
from model_openness_tool.licenses import LicenseRegistry


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def catalog() -> FrameworkCatalog:
    return load_catalog()


@pytest.fixture(scope="session")
def license_registry(repository_root: Path) -> LicenseRegistry:
    return LicenseRegistry.from_mot_files(
        repository_root / "web/modules/mof/licenses.json",
        repository_root / "web/modules/mof/mof-licenses.json",
    )
