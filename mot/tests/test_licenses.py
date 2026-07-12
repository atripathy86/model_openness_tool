from model_openness_tool.domain import ContentType
from model_openness_tool.licenses import LicenseRegistry


def test_license_registry_matches_mot_openness_rules(
    license_registry: LicenseRegistry,
) -> None:
    assert license_registry.is_open("Apache-2.0")
    assert license_registry.is_open("CC-BY-4.0")
    assert not license_registry.is_open("LicenseRef-not-real")


def test_license_registry_matches_mot_type_rules(
    license_registry: LicenseRegistry,
) -> None:
    assert license_registry.is_type_appropriate("Apache-2.0", ContentType.CODE)
    assert license_registry.is_type_appropriate("Apache-2.0", ContentType.DOCUMENT)
    assert not license_registry.is_type_appropriate("Apache-2.0", ContentType.DATA)
    # Current MOT data imports CC-BY-4.0 as document-only even though
    # LicenseHandler separately considers it an open-data license.
    assert license_registry.is_type_appropriate("CC-BY-4.0", ContentType.DOCUMENT)
    assert not license_registry.is_type_appropriate("CC-BY-4.0", ContentType.DATA)


def test_license_catalog_hash_covers_both_source_files(
    license_registry: LicenseRegistry,
) -> None:
    assert len(license_registry.catalog_sha256) == 64
