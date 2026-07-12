import re
from pathlib import Path

import pytest

from model_openness_tool.domain import FrameworkCatalog, ModelInput
from model_openness_tool.licenses import LicenseRegistry
from model_openness_tool.model_yaml import load_model_yaml
from model_openness_tool.scoring import ModelEvaluator

PROGRESS_PATTERN = re.compile(r"_C1_(\d+)%-C2_(\d+)%-C3_(\d+)%")


@pytest.mark.parametrize(
    ("fixture_name", "expected_class", "expected_progress"),
    [
        (
            "Class3TTestFile_C1_33%-C2_60%-C3_100%_6C_1G_6L_6V_0I_6T.yml",
            3,
            {1: 0.0, 2: 60.0, 3: 100.0},
        ),
        (
            "Class2TTestFile_C1_71%-C2_100%-C3_100%_11C_1G_11L_11V_0I_11T.yml",
            2,
            {1: 71.42857142857143, 2: 100.0, 3: 100.0},
        ),
        (
            "Class1TestFile_C1_100%-C2_100%-C3_100%_15C_2G_15L_15V_0I_15T.yml",
            1,
            {1: 100.0, 2: 100.0, 3: 100.0},
        ),
    ],
)
def test_scoring_parity_for_class_fixtures(
    repository_root: Path,
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
    fixture_name: str,
    expected_class: int,
    expected_progress: dict[int, float],
) -> None:
    model = load_model_yaml(repository_root / "Test_Data" / fixture_name, catalog)
    report = ModelEvaluator(catalog, license_registry).score(model)

    assert report.classification == expected_class
    assert report.progress == pytest.approx(expected_progress)


def test_explicit_unlicensed_component_overrides_open_global_license(
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
) -> None:
    model = ModelInput(
        name="Explicitly unlicensed architecture",
        included_component_ids=frozenset({9}),
        global_licenses={"distribution": "Apache-2.0"},
        component_licenses={9: None},
    )

    evaluation = ModelEvaluator(catalog, license_registry).evaluate(model)

    assert 9 in evaluation.classes[3].components.unlicensed
    assert evaluation.classes[3].licenses[9] == "unlicensed"


def test_open_but_wrong_type_is_included_with_warning(
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
) -> None:
    model = ModelInput(
        name="Wrong type",
        included_component_ids=frozenset({9}),
        component_licenses={9: "CC-BY-4.0"},
    )

    evaluation = ModelEvaluator(catalog, license_registry).evaluate(model)

    assert 9 in evaluation.classes[3].components.included
    assert 9 in evaluation.not_type_appropriate


def test_progress_parity_for_all_named_drupal_fixtures(
    repository_root: Path,
    catalog: FrameworkCatalog,
    license_registry: LicenseRegistry,
) -> None:
    evaluator = ModelEvaluator(catalog, license_registry)
    failures: list[str] = []

    for fixture in sorted((repository_root / "Test_Data").glob("*.yml")):
        match = PROGRESS_PATTERN.search(fixture.name)
        if match is None:
            continue
        expected = {
            1: int(match.group(1)),
            2: int(match.group(2)),
            3: int(match.group(3)),
        }
        report = evaluator.score(load_model_yaml(fixture, catalog))
        actual = {mof_class: round(value) for mof_class, value in report.progress.items()}

        # Match the lower-class gating adjustment in scripts/test-model-files.php.
        if actual[3] < 100:
            expected[2] = 0
            expected[1] = 0
        elif actual[2] < 100:
            expected[1] = 0

        if actual != expected:
            failures.append(f"{fixture.name}: expected {expected}, got {actual}")

    assert not failures, "\n".join(failures)
