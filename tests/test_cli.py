"""
Tests to validate functionality of src/cli.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import patch

import allure
from typer.testing import CliRunner

from src.cli import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"})


@allure.title("validate-Befehl bestätigt eine gültige Topologie-Datei")
@allure.description(
    "Überprüft, dass der validate-Befehl validate_file() aufruft und den Erfolg meldet"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_000() -> None:
    with patch("src.cli.TopologyFileValidation") as validator_cls:
        result = runner.invoke(app, ["validate"])

    validator_cls.return_value.validate_file.assert_called_once()
    assert result.exit_code == 0, result.output
    assert "Valid." in result.output


@allure.title("deploy-Befehl validiert, baut den Graphen und deployt ihn")
@allure.description(
    "Überprüft, dass der deploy-Befehl validate_file() aufruft, einen Graph "
    "baut und VMOrchestrator.deploy_graph mit diesem Graph aufruft"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_001() -> None:
    with (
        patch("src.cli.TopologyFileValidation") as validator_cls,
        patch("src.cli.Graph") as graph_cls,
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        validator_cls.return_value.nodes = []
        validator_cls.return_value.edges = []

        result = runner.invoke(
            app,
            [
                "deploy",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 0, result.output
    validator_cls.return_value.validate_file.assert_called_once()
    orchestrator_cls.return_value.deploy_graph.assert_called_once()
    assert (
        orchestrator_cls.return_value.deploy_graph.call_args.kwargs["graph"]
        is graph_cls.return_value
    )


@allure.title(
    "deploy-Befehl wirft einen Fehler bei gleichzeitigem --only_on_gns3 und --only_on_esxi"
)
@allure.description(
    "Überprüft, dass der deploy-Befehl einen Fehler wirft, wenn sowohl "
    "--only_on_gns3 als auch --only_on_esxi angegeben werden, da beide "
    "Umgebungen gleichzeitig ausschließlich zu deployen widersprüchlich ist"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_002() -> None:
    with (
        patch("src.cli.TopologyFileValidation"),
        patch("src.cli.Graph"),
        patch("src.cli.VMOrchestrator"),
    ):
        result = runner.invoke(
            app,
            [
                "deploy",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
                "--only_on_gns3",
                "--only_on_esxi",
            ],
        )

    assert result.exit_code != 0


@allure.title("destroy-Befehl validiert, baut den Graphen und zerstört ihn")
@allure.description(
    "Überprüft, dass der destroy-Befehl validate_file() aufruft, einen "
    "Graph baut und VMOrchestrator.destroy_graph mit diesem Graph aufruft"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_003() -> None:
    with (
        patch("src.cli.TopologyFileValidation") as validator_cls,
        patch("src.cli.Graph") as graph_cls,
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        result = runner.invoke(
            app,
            [
                "destroy",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 0, result.output
    validator_cls.return_value.validate_file.assert_called_once()
    orchestrator_cls.return_value.destroy_graph.assert_called_once()
    assert orchestrator_cls.return_value.destroy_graph.call_args.args[0] is (
        graph_cls.return_value
    )
    assert "Destroy complete." in result.output
