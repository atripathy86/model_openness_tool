from pathlib import Path

import yaml

from model_openness_tool.domain import FrameworkCatalog


def test_catalog_captures_current_seventeen_component_baseline(
    catalog: FrameworkCatalog,
) -> None:
    assert catalog.framework.version == "1.0"
    assert len(catalog.components) == 17
    assert set(catalog.required_for_class(3)) == {9, 10, 11, 12, 13, 14}
    assert set(catalog.required_for_class(2)) == {7, 8, 18, 19}
    assert set(catalog.required_for_class(1)) == {15, 16, 21, 24}
    assert set(catalog.optional_for_class(3)) == {20}
    assert set(catalog.optional_for_class(2)) == {22}
    assert set(catalog.optional_for_class(1)) == {17}


def test_catalog_has_stable_content_hash(catalog: FrameworkCatalog) -> None:
    assert len(catalog.catalog_sha256) == 64
    assert catalog.catalog_sha256.isalnum()


def test_packaged_catalog_matches_drupal_source(
    repository_root: Path,
    catalog: FrameworkCatalog,
) -> None:
    source_path = repository_root / "web/modules/mof/config/install/mof.settings.yml"
    source = yaml.safe_load(source_path.read_bytes())
    source_components = {
        item["id"]: {
            "id": item["id"],
            "name": item["name"],
            "description": item["description"],
            "content_type": item["content_type"],
            "class": item["class"],
            "weight": item["weight"],
            "required": item["required"],
        }
        for item in source["components"]
    }
    packaged_components = {
        component.id: component.model_dump(by_alias=True, mode="json")
        for component in catalog.components
    }

    assert packaged_components == source_components
