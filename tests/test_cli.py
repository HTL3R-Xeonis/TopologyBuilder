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
    assert (
        orchestrator_cls.return_value.deploy_graph.call_args.kwargs["incremental"]
        is False
    )


@allure.title("deploy-Befehl mit --incremental leitet incremental=True weiter")
@allure.description(
    "Überprüft, dass der deploy-Befehl mit --incremental die "
    "deploy_graph-Methode mit incremental=True aufruft"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_010() -> None:
    with (
        patch("src.cli.TopologyFileValidation"),
        patch("src.cli.Graph"),
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
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
                "--incremental",
            ],
        )

    assert result.exit_code == 0, result.output
    assert (
        orchestrator_cls.return_value.deploy_graph.call_args.kwargs["incremental"]
        is True
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


@allure.title(
    "status-Befehl meldet Erreichbarkeit und listet Projekte mit Node-Zählern"
)
@allure.description(
    "Überprüft, dass der status-Befehl die ESXi- und GNS3-Erreichbarkeit "
    "meldet und für jedes GNS3-Projekt die Node- und Started-Zähler ausgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_004() -> None:
    with (
        patch("src.cli.ESXiConnection") as esxi_cls,
        patch("src.cli.GNS3Connection") as gns3_cls,
    ):
        esxi_cls.return_value.get_vm_ip_address.return_value = "10.20.20.231"
        gns3_cls.get_version.return_value = {"version": "2.2.61"}
        gns3_cls.list_all_projects.return_value = [
            {"project_id": "p1", "name": "lab", "status": "opened"}
        ]
        gns3_cls.list_project_nodes.return_value = [
            {"node_id": "n1", "status": "started"},
            {"node_id": "n2", "status": "stopped"},
        ]

        result = runner.invoke(
            app,
            [
                "status",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "ESXi host 10.20.20.202: reachable" in result.output
    assert "GNS3 2.2.61" in result.output
    assert "lab" in result.output
    assert "2 node(s), 1 started" in result.output


@allure.title("status-Befehl meldet Fehler, wenn keine GNS3-VM gefunden wird")
@allure.description(
    "Überprüft, dass der status-Befehl mit Exit-Code 1 abbricht, wenn "
    "get_vm_ip_address keine IP für die GNS3-VM zurückgibt"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_005() -> None:
    with patch("src.cli.ESXiConnection") as esxi_cls:
        esxi_cls.return_value.get_vm_ip_address.return_value = None

        result = runner.invoke(
            app,
            [
                "status",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 1


@allure.title("templates-Befehl listet ESXi- und GNS3-Template-Namen")
@allure.description(
    "Überprüft, dass der templates-Befehl beide Template-Listen sortiert ausgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_006() -> None:
    with patch("src.cli.APIHandler") as api_handler_cls:
        api_handler_cls.get_esxi_template_names.return_value = {"Ubuntu-Server"}
        api_handler_cls.get_gns3_template_names.return_value = {"VPCS", "Cloud"}

        result = runner.invoke(app, ["templates"])

    assert result.exit_code == 0, result.output
    assert "ESXi templates (1):" in result.output
    assert "Ubuntu-Server" in result.output
    assert "GNS3 templates (2):" in result.output
    assert "Cloud" in result.output
    assert "VPCS" in result.output


@allure.title("portgroups-Befehl listet die Port-Groups des ESXi-Hosts")
@allure.description(
    "Überprüft, dass der portgroups-Befehl jede Port-Group mit Name, "
    "VLAN-ID und vSwitch ausgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_007() -> None:
    with patch("src.cli.ESXiConnection") as esxi_cls:
        esxi_cls.return_value.list_port_groups.return_value = [
            {"name": "PG-MGMT", "vlan_id": 0, "vswitch": "internal_network"}
        ]

        result = runner.invoke(
            app,
            [
                "portgroups",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "PG-MGMT (VLAN 0) on internal_network" in result.output


@allure.title("logs-Befehl zeigt die letzten N Zeilen der Log-Datei")
@allure.description(
    "Überprüft, dass der logs-Befehl nur die letzten --lines Zeilen der "
    "Log-Datei ausgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_008(tmp_path) -> None:
    from src.settings import Settings

    log_file = tmp_path / "app.log"
    log_file.write_text("line1\nline2\nline3\n")

    original_path = Settings.LOG_FILE_PATH
    Settings.LOG_FILE_PATH = str(log_file)
    try:
        result = runner.invoke(app, ["logs", "--lines", "2"])
    finally:
        Settings.LOG_FILE_PATH = original_path

    assert result.exit_code == 0, result.output
    assert "line1" not in result.output
    assert "line2" in result.output
    assert "line3" in result.output


@allure.title("logs-Befehl meldet Fehler, wenn keine Log-Datei existiert")
@allure.description(
    "Überprüft, dass der logs-Befehl mit Exit-Code 1 abbricht, wenn die "
    "konfigurierte Log-Datei nicht existiert"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_009(tmp_path) -> None:
    from src.settings import Settings

    original_path = Settings.LOG_FILE_PATH
    Settings.LOG_FILE_PATH = str(tmp_path / "does-not-exist.log")
    try:
        result = runner.invoke(app, ["logs"])
    finally:
        Settings.LOG_FILE_PATH = original_path

    assert result.exit_code == 1


@allure.title("verify-Befehl meldet Erfolg, wenn alle Checks bestehen")
@allure.description(
    "Überprüft, dass der verify-Befehl bei durchweg bestandenen Checks "
    "Exit-Code 0 und eine 'N/N checks passed'-Zusammenfassung liefert"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_011() -> None:
    with (
        patch("src.cli.TopologyFileValidation"),
        patch("src.cli.Graph"),
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        orchestrator_cls.return_value.verify_graph.return_value = [
            (True, "R1: started"),
            (True, "VM1: powered on"),
        ]

        result = runner.invoke(
            app,
            [
                "verify",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "[OK]" in result.output
    assert "2/2 checks passed" in result.output


@allure.title("verify-Befehl bricht mit Exit-Code 1 ab, wenn ein Check fehlschlägt")
@allure.description(
    "Überprüft, dass der verify-Befehl mit Exit-Code 1 abbricht und "
    "fehlgeschlagene Checks als [FAIL] markiert, sobald mindestens ein "
    "Check nicht bestanden wurde"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_012() -> None:
    with (
        patch("src.cli.TopologyFileValidation"),
        patch("src.cli.Graph"),
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        orchestrator_cls.return_value.verify_graph.return_value = [
            (True, "R1: started"),
            (False, "VM1: not found"),
        ]

        result = runner.invoke(
            app,
            [
                "verify",
                "--address",
                "10.20.20.202",
                "--esxi_username",
                "root",
                "--esxi_password",
                "pw",
            ],
        )

    assert result.exit_code == 1
    assert "[FAIL]" in result.output
    assert "1/2 checks passed" in result.output
