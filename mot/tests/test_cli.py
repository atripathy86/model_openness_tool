import json
from pathlib import Path

from typer.testing import CliRunner

from model_openness_tool.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_catalog_command() -> None:
    result = runner.invoke(app, ["catalog"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["framework"]["version"] == "1.0"
    assert len(payload["components"]) == 17


def test_evaluate_yaml_command(repository_root: Path) -> None:
    fixture = (
        repository_root / "Test_Data/Class3TTestFile_C1_33%-C2_60%-C3_100%_6C_1G_6L_6V_0I_6T.yml"
    )
    result = runner.invoke(
        app,
        ["evaluate-yaml", str(fixture), "--repository-root", str(repository_root)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["classification"] == 3
    assert payload["progress"]["3"] == 100.0
