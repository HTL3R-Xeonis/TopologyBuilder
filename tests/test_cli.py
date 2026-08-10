"""
Tests to validate functionality of cli.py
"""

__license__ = "GNU GPLv3"

import logging
from unittest.mock import MagicMock, patch

import allure
import pytest
import typer
from typer.testing import CliRunner

from src import logger_adapter
from src.cli import app, main, _resolve_config_path, _resolve_esxi_credentials
from src.factories import Environment

logger_adapter.LoggerAdapter.is_test_run = True

# Typer renders BadParameter errors through Rich in a bordered panel whose
# wrap width and color are auto-detected per environment - narrow enough
# locally to sometimes split a multi-word substring across the wrap, and
# CI has been observed to enable ANSI color where a local run didn't. Both
# make substring assertions against result.output flaky across machines.
# Pinning a wide COLUMNS and disabling color keeps every assertion on
# rendered CLI output exact and reproducible everywhere.
runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"})


# --- _resolve_esxi_credentials -----------------------------------------


@allure.title("Fehlender ESXi-Host wirft BadParameter")
@allure.description(
    "Überprüft, dass _resolve_esxi_credentials einen typer.BadParameter wirft, "
    "wenn kein ESXi-Host angegeben ist"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_000() -> None:
    with pytest.raises(typer.BadParameter, match=r"Missing ESXi host"):
        _resolve_esxi_credentials(None, "root", "pw")


@allure.title("Fehlender ESXi-Benutzername wirft BadParameter")
@allure.description(
    "Überprüft, dass _resolve_esxi_credentials einen typer.BadParameter wirft, "
    "wenn kein ESXi-Benutzername angegeben ist"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_001() -> None:
    with pytest.raises(typer.BadParameter, match=r"Missing ESXi username"):
        _resolve_esxi_credentials("10.20.20.202", None, "pw")


@allure.title("Fehlendes ESXi-Passwort wird interaktiv abgefragt")
@allure.description(
    "Überprüft, dass _resolve_esxi_credentials bei fehlendem Passwort per "
    "typer.prompt danach fragt und den eingegebenen Wert zurückgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_002() -> None:
    with patch("src.cli.typer.prompt", return_value="prompted-pw") as mock_prompt:
        result = _resolve_esxi_credentials("10.20.20.202", "root", None)

    mock_prompt.assert_called_once_with("ESXi password", hide_input=True)
    assert result == ("10.20.20.202", "root", "prompted-pw")


@allure.title("Vollständige ESXi-Zugangsdaten werden unverändert zurückgegeben")
@allure.description(
    "Überprüft, dass _resolve_esxi_credentials nicht nach dem Passwort fragt, "
    "wenn alle drei Werte bereits angegeben sind"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_003() -> None:
    with patch("src.cli.typer.prompt") as mock_prompt:
        result = _resolve_esxi_credentials("10.20.20.202", "root", "pw")

    mock_prompt.assert_not_called()
    assert result == ("10.20.20.202", "root", "pw")


# --- _resolve_config_path ------------------------------------------------


@allure.title("Fehlender Config-Pfad wirft BadParameter")
@allure.description(
    "Überprüft, dass _resolve_config_path einen typer.BadParameter wirft, "
    "wenn kein Config-Dateipfad angegeben ist"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_004() -> None:
    with pytest.raises(typer.BadParameter, match=r"Missing topology config file path"):
        _resolve_config_path(None)


@allure.title("Vorhandener Config-Pfad wird unverändert zurückgegeben")
@allure.description(
    "Überprüft, dass _resolve_config_path einen gegebenen Pfad unverändert zurückgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_005() -> None:
    assert _resolve_config_path("../config_ex") == "../config_ex"


# --- main() (console verbosity) ------------------------------------------


@allure.title("Verbosity-Zähler wird auf steigende Log-Level abgebildet")
@allure.description(
    "Überprüft, dass main() ohne --quiet den Verbosity-Zähler auf WARNING "
    "(0), INFO (1) und DEBUG (2) abbildet"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_006() -> None:
    with patch("src.cli.set_console_level") as mock_set_level:
        main(
            verbose=0,
            quiet=False,
            esxi_template_api_url=None,
            gns3_template_api_url=None,
        )
        main(
            verbose=1,
            quiet=False,
            esxi_template_api_url=None,
            gns3_template_api_url=None,
        )
        main(
            verbose=2,
            quiet=False,
            esxi_template_api_url=None,
            gns3_template_api_url=None,
        )

    assert mock_set_level.call_args_list == [
        ((logging.WARNING,),),
        ((logging.INFO,),),
        ((logging.DEBUG,),),
    ]


@allure.title("Verbosity-Zähler über der Höchststufe wird auf DEBUG begrenzt")
@allure.description(
    "Überprüft, dass main() einen Verbosity-Zähler, der über die Anzahl "
    "bekannter Level hinausgeht, auf die höchste Stufe (DEBUG) begrenzt, "
    "statt einen IndexError zu werfen"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_007() -> None:
    with patch("src.cli.set_console_level") as mock_set_level:
        main(
            verbose=10,
            quiet=False,
            esxi_template_api_url=None,
            gns3_template_api_url=None,
        )

    mock_set_level.assert_called_once_with(logging.DEBUG)


@allure.title("--quiet unterdrückt die Konsolenausgabe bis auf Fehler")
@allure.description(
    "Überprüft, dass main() mit quiet=True set_console_level mit ERROR "
    "aufruft, unabhängig vom Verbosity-Zähler"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_008() -> None:
    with patch("src.cli.set_console_level") as mock_set_level:
        main(
            verbose=2,
            quiet=True,
            esxi_template_api_url=None,
            gns3_template_api_url=None,
        )

    mock_set_level.assert_called_once_with(logging.ERROR)


# --- validate command ------------------------------------------------------


@allure.title("validate-Befehl bestätigt eine gültige Config-Datei")
@allure.description(
    "Überprüft, dass der validate-Befehl validate_file() aufruft und den Erfolg meldet"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_009() -> None:
    with patch("src.cli.ConfigFileHandler") as handler_cls:
        result = runner.invoke(app, ["validate", "config_ex.yml"])

    handler_cls.return_value.validate_file.assert_called_once()
    assert result.exit_code == 0
    assert "config_ex.yml is valid." in result.output


@allure.title("validate-Befehl ohne Config-Pfad schlägt fehl")
@allure.description(
    "Überprüft, dass der validate-Befehl ohne Config-Pfad (und ohne Default "
    "aus topologybuilder.yml) mit einem Fehler abbricht"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_010() -> None:
    result = runner.invoke(app, ["validate"])

    assert result.exit_code != 0
    assert "Missing topology config file path" in result.output


# --- build command -----------------------------------------------------


@allure.title("build-Befehl listet die gebauten Nodes auf")
@allure.description(
    "Überprüft, dass der build-Befehl die Anzahl und Namen der gebauten Nodes ausgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_011() -> None:
    nodes = {"PC1": MagicMock(), "SW-C1": MagicMock()}
    with (
        patch("src.cli.ConfigFileHandler"),
        patch("src.cli.GraphBuilder") as graph_builder_cls,
    ):
        graph_builder_cls.return_value.build.return_value = nodes
        result = runner.invoke(app, ["build", "config_ex.yml"])

    assert result.exit_code == 0
    assert "Built 2 node(s):" in result.output
    assert "- PC1" in result.output
    assert "- SW-C1" in result.output


@allure.title("build --graph zeigt eine Visualisierung an")
@allure.description(
    "Überprüft, dass der build-Befehl mit --graph render_graph aufruft und "
    "dessen Ausgabe anzeigt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_012() -> None:
    nodes = {"PC1": MagicMock()}
    with (
        patch("src.cli.ConfigFileHandler"),
        patch("src.cli.GraphBuilder") as graph_builder_cls,
        patch("src.cli.render_graph", return_value="<< graph art >>") as render,
    ):
        graph_builder_cls.return_value.build.return_value = nodes
        result = runner.invoke(app, ["build", "config_ex.yml", "--graph"])

    render.assert_called_once_with(nodes)
    assert "<< graph art >>" in result.output


@allure.title("build --list zeigt den Verbindungsbaum an")
@allure.description(
    "Überprüft, dass der build-Befehl mit --list print_connection_tree mit "
    "den gebauten Nodes aufruft"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_013() -> None:
    nodes = {"PC1": MagicMock()}
    with (
        patch("src.cli.ConfigFileHandler"),
        patch("src.cli.GraphBuilder") as graph_builder_cls,
        patch("src.cli.print_connection_tree") as print_tree,
    ):
        graph_builder_cls.return_value.build.return_value = nodes
        runner.invoke(app, ["build", "config_ex.yml", "--list"])

    print_tree.assert_called_once_with(nodes)


# --- generate command ----------------------------------------------------


@allure.title("generate-Befehl schreibt die generierte Config-Datei")
@allure.description(
    "Überprüft, dass der generate-Befehl bei einem gültigen Ergebnis die "
    "generierte YAML-Config in die Zieldatei schreibt und den Erfolg meldet"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_014(tmp_path) -> None:
    output_path = tmp_path / "generated.yml"
    with patch("src.cli.generate_topology") as generate:
        generate.return_value = {
            "valid": True,
            "yaml": "nodes: []\nedges: []\n",
            "warnings": [],
        }
        result = runner.invoke(
            app, ["generate", "a small lab", "--output", str(output_path)]
        )

    assert result.exit_code == 0
    assert output_path.read_text() == "nodes: []\nedges: []\n"
    assert f"Wrote generated config to {output_path}" in result.output


@allure.title("generate-Befehl zeigt Warnungen auf stderr an")
@allure.description(
    "Überprüft, dass der generate-Befehl jede Warnung aus dem Ergebnis auf "
    "stderr ausgibt, auch bei einem gültigen Ergebnis"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_015(tmp_path) -> None:
    output_path = tmp_path / "generated.yml"
    with patch("src.cli.generate_topology") as generate:
        generate.return_value = {
            "valid": True,
            "yaml": "nodes: []\nedges: []\n",
            "warnings": ["ambiguous device count"],
        }
        result = runner.invoke(
            app, ["generate", "a small lab", "--output", str(output_path)]
        )

    assert "Warning: ambiguous device count" in result.stderr


@allure.title("generate-Befehl schreibt bei ungültigem Ergebnis keine Datei")
@allure.description(
    "Überprüft, dass der generate-Befehl mit Exit-Code 1 abbricht und keine "
    "Datei schreibt, wenn das generierte Ergebnis als ungültig markiert ist"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_016(tmp_path) -> None:
    output_path = tmp_path / "generated.yml"
    with patch("src.cli.generate_topology") as generate:
        generate.return_value = {"valid": False, "warnings": []}
        result = runner.invoke(
            app, ["generate", "a small lab", "--output", str(output_path)]
        )

    assert result.exit_code == 1
    assert not output_path.exists()
    assert "Topology generation failed" in result.stderr


# --- deploy command --------------------------------------------------------


_DEPLOY_CREDS = [
    "--esxi-host",
    "10.20.20.202",
    "--esxi-username",
    "root",
    "--esxi-password",
    "pw",
]


@allure.title("deploy-Befehl verlangt --esxi-datastore bei ESXi-gehosteten Nodes")
@allure.description(
    "Überprüft, dass der deploy-Befehl mit einem BadParameter abbricht, "
    "wenn die Topologie eine ESXi-gehostete Node enthält, aber kein "
    "--esxi-datastore angegeben wurde"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_017() -> None:
    esxi_node = MagicMock()
    esxi_node.env = Environment.ON_ESXI
    with (
        patch("src.cli.ConfigFileHandler"),
        patch("src.cli.GraphBuilder") as graph_builder_cls,
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        graph_builder_cls.return_value.build.return_value = {"VM1": esxi_node}
        result = runner.invoke(app, ["deploy", "config_ex.yml", *_DEPLOY_CREDS])

    assert result.exit_code != 0
    assert "--esxi-datastore is required" in result.output
    orchestrator_cls.assert_not_called()


@allure.title("deploy --fresh-gns3-vm verlangt die zusätzlichen Flags")
@allure.description(
    "Überprüft, dass deploy --fresh-gns3-vm ohne die zusätzlich benötigten "
    "Flags (--gns3-ova-path, --gns3-datastore, --gns3-mgmt-network, "
    "--gns3-trunk-network) mit einem BadParameter abbricht, der alle "
    "fehlenden Flags nennt"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_018() -> None:
    result = runner.invoke(
        app, ["deploy", "config_ex.yml", "--fresh-gns3-vm", *_DEPLOY_CREDS]
    )

    assert result.exit_code != 0
    assert "--gns3-ova-path" in result.output
    assert "--gns3-datastore" in result.output
    assert "--gns3-mgmt-network" in result.output
    assert "--gns3-trunk-network" in result.output


@allure.title("deploy-Befehl durchläuft die volle Deploy-Pipeline")
@allure.description(
    "Überprüft, dass der deploy-Befehl ohne --fresh-gns3-vm die Pipeline in "
    "der richtigen Reihenfolge aufruft: delete_stale_esxi_resources, "
    "create_gns3_configuration_file, deploy_esxi_nodes, deploy_gns3_topology "
    "- und deploy_fresh_gns3_vm dabei NICHT aufruft"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_019() -> None:
    gns3_node = MagicMock()
    gns3_node.env = Environment.ON_GNS3
    nodes = {"R1": gns3_node}
    with (
        patch("src.cli.ConfigFileHandler"),
        patch("src.cli.GraphBuilder") as graph_builder_cls,
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        graph_builder_cls.return_value.build.return_value = nodes
        orchestrator = orchestrator_cls.return_value
        result = runner.invoke(app, ["deploy", "config_ex.yml", *_DEPLOY_CREDS])

    assert result.exit_code == 0, result.output
    orchestrator_cls.assert_called_once_with("10.20.20.202", "root", "pw")
    orchestrator.deploy_fresh_gns3_vm.assert_not_called()
    orchestrator.delete_stale_esxi_resources.assert_called_once_with(nodes)
    orchestrator.create_gns3_configuration_file.assert_called_once_with(
        nodes, vm_name=None, trunk_network_name=None, trunk_interface=None
    )
    orchestrator.deploy_esxi_nodes.assert_called_once_with(
        nodes, None, download_dir=None
    )
    orchestrator.deploy_gns3_topology.assert_called_once_with(
        nodes, "config_ex", vm_name=None
    )
    assert "Deployment complete." in result.output


@allure.title("deploy --fresh-gns3-vm ersetzt die GNS3-VM vor dem restlichen Deploy")
@allure.description(
    "Überprüft, dass der deploy-Befehl mit --fresh-gns3-vm und allen "
    "benötigten Flags deploy_fresh_gns3_vm mit den richtigen Argumenten "
    "aufruft, bevor die restliche Deploy-Pipeline läuft"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_020() -> None:
    gns3_node = MagicMock()
    gns3_node.env = Environment.ON_GNS3
    nodes = {"R1": gns3_node}
    with (
        patch("src.cli.ConfigFileHandler"),
        patch("src.cli.GraphBuilder") as graph_builder_cls,
        patch("src.cli.VMOrchestrator") as orchestrator_cls,
    ):
        graph_builder_cls.return_value.build.return_value = nodes
        orchestrator = orchestrator_cls.return_value
        result = runner.invoke(
            app,
            [
                "deploy",
                "config_ex.yml",
                *_DEPLOY_CREDS,
                "--fresh-gns3-vm",
                "--gns3-ova-path",
                "/mnt/GNS3-OVAs/gns3.ova",
                "--gns3-datastore",
                "datastore1",
                "--gns3-mgmt-network",
                "PG-MGMT",
                "--gns3-trunk-network",
                "PG-GNS3-TRUNK",
                "--gns3-vm-name",
                "GNS3-VM",
            ],
        )

    assert result.exit_code == 0, result.output
    orchestrator.deploy_fresh_gns3_vm.assert_called_once_with(
        "/mnt/GNS3-OVAs/gns3.ova",
        "datastore1",
        "PG-MGMT",
        "PG-GNS3-TRUNK",
        vm_name="GNS3-VM",
    )


# --- portgroups command -----------------------------------------------------


@allure.title("portgroups-Befehl listet die Port-Groups des ESXi-Hosts auf")
@allure.description(
    "Überprüft, dass der portgroups-Befehl jede Port-Group mit Name, VLAN-ID "
    "und vSwitch formatiert ausgibt"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_021() -> None:
    with patch("src.cli.ESXiConnection") as esxi_cls:
        esxi_cls.return_value.list_port_groups.return_value = [
            {"name": "PC4_gi0-0", "vlan_id": 2, "vswitch": "vSwitch0"},
        ]
        result = runner.invoke(app, ["portgroups", *_DEPLOY_CREDS])

    assert result.exit_code == 0
    assert "PC4_gi0-0 (VLAN 2) on vSwitch0" in result.output


# --- logs command -----------------------------------------------------------


@allure.title("logs-Befehl zeigt die letzten N Zeilen der Log-Datei")
@allure.description(
    "Überprüft, dass der logs-Befehl nur die letzten --lines Zeilen der "
    "Log-Datei ausgibt, nicht die gesamte Datei"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_022(tmp_path) -> None:
    log_file = tmp_path / "log.txt"
    log_file.write_text("".join(f"line {i}\n" for i in range(1, 11)))

    with patch("src.cli.get_log_file_path", return_value=log_file):
        result = runner.invoke(app, ["logs", "--lines", "3"])

    assert result.exit_code == 0
    assert result.output == "line 8\nline 9\nline 10\n"


@allure.title("logs-Befehl zeigt die ganze Datei, wenn sie kürzer als --lines ist")
@allure.description(
    "Überprüft, dass der logs-Befehl die komplette Datei ausgibt, ohne "
    "Fehler, wenn sie weniger Zeilen als angefordert enthält"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_023(tmp_path) -> None:
    log_file = tmp_path / "log.txt"
    log_file.write_text("line 1\nline 2\n")

    with patch("src.cli.get_log_file_path", return_value=log_file):
        result = runner.invoke(app, ["logs", "--lines", "50"])

    assert result.exit_code == 0
    assert result.output == "line 1\nline 2\n"


@allure.title("logs-Befehl meldet einen Fehler, wenn die Log-Datei fehlt")
@allure.description(
    "Überprüft, dass der logs-Befehl mit Exit-Code 1 und einer klaren "
    "Fehlermeldung abbricht, wenn die Log-Datei (noch) nicht existiert"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_024(tmp_path) -> None:
    missing_path = tmp_path / "does_not_exist.txt"

    with patch("src.cli.get_log_file_path", return_value=missing_path):
        result = runner.invoke(app, ["logs"])

    assert result.exit_code == 1
    assert f"No log file found at {missing_path}" in result.output


@allure.title("logs --lines lehnt einen nicht-positiven Wert ab")
@allure.description(
    "Überprüft, dass der logs-Befehl --lines 0 ablehnt, statt (wegen "
    "Pythons list[-0:]-Verhalten) versehentlich die gesamte Datei "
    "auszugeben"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_025() -> None:
    result = runner.invoke(app, ["logs", "--lines", "0"])

    assert result.exit_code != 0


# --- main() (template-API URL overrides) ----------------------------------


@allure.title("main() überschreibt die Template-API-URLs, wenn angegeben")
@allure.description(
    "Überprüft, dass main() set_esxi_template_api_url/set_gns3_template_api_url "
    "mit den gegebenen URLs aufruft, wenn --esxi-template-api-url/"
    "--gns3-template-api-url angegeben sind"
)
@allure.tag("positiv-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.CRITICAL)
def cli_026() -> None:
    with (
        patch("src.cli.set_console_level"),
        patch("src.cli.set_esxi_template_api_url") as set_esxi,
        patch("src.cli.set_gns3_template_api_url") as set_gns3,
    ):
        main(
            verbose=0,
            quiet=False,
            esxi_template_api_url="http://esxi-templates.example:8000",
            gns3_template_api_url="http://gns3-templates.example:8001",
        )

    set_esxi.assert_called_once_with("http://esxi-templates.example:8000")
    set_gns3.assert_called_once_with("http://gns3-templates.example:8001")


@allure.title("main() lässt die Template-API-URLs unverändert, wenn nicht angegeben")
@allure.description(
    "Überprüft, dass main() set_esxi_template_api_url/set_gns3_template_api_url "
    "nicht aufruft, wenn keine der beiden Optionen angegeben ist - die "
    "Standard-URLs in connections_handler.py bleiben dann unangetastet"
)
@allure.tag("negativ-test", "cli")
@allure.feature("cli")
@allure.severity(allure.severity_level.NORMAL)
def cli_027() -> None:
    with (
        patch("src.cli.set_console_level"),
        patch("src.cli.set_esxi_template_api_url") as set_esxi,
        patch("src.cli.set_gns3_template_api_url") as set_gns3,
    ):
        main(
            verbose=0,
            quiet=False,
            esxi_template_api_url=None,
            gns3_template_api_url=None,
        )

    set_esxi.assert_not_called()
    set_gns3.assert_not_called()
