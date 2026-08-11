"""
Tests to validate functionality of cli_config.py
"""

__license__ = "GNU GPLv3"

import allure

from src import logger_adapter
from src.cli_config import load_cli_config

logger_adapter.LoggerAdapter.is_test_run = True


@allure.title(
    "load_cli_config gibt ein leeres Dict zurück, wenn keine Config-Datei existiert"
)
@allure.description(
    "Überprüft, dass load_cli_config ein leeres Dict zurückgibt, wenn weder "
    "TOPOLOGYBUILDER_CONFIG gesetzt ist noch topologybuilder.yml/.yaml im "
    "aktuellen Arbeitsverzeichnis existieren"
)
@allure.tag("negativ-test", "cli_config")
@allure.feature("cli_config")
@allure.severity(allure.severity_level.CRITICAL)
def cli_config_000(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOLOGYBUILDER_CONFIG", raising=False)

    assert load_cli_config() == {}


@allure.title("load_cli_config lädt topologybuilder.yml aus dem Arbeitsverzeichnis")
@allure.description(
    "Überprüft, dass load_cli_config die Werte aus ./topologybuilder.yml "
    "einliest, wenn keine TOPOLOGYBUILDER_CONFIG-Umgebungsvariable gesetzt ist"
)
@allure.tag("positiv-test", "cli_config")
@allure.feature("cli_config")
@allure.severity(allure.severity_level.CRITICAL)
def cli_config_001(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOLOGYBUILDER_CONFIG", raising=False)
    (tmp_path / "topologybuilder.yml").write_text("esxi_host: 10.20.20.202\n")

    assert load_cli_config() == {"esxi_host": "10.20.20.202"}


@allure.title(
    "load_cli_config bevorzugt topologybuilder.yaml, wenn kein .yml existiert"
)
@allure.description(
    "Überprüft, dass load_cli_config auf ./topologybuilder.yaml zurückfällt, "
    "wenn ./topologybuilder.yml nicht existiert"
)
@allure.tag("positiv-test", "cli_config")
@allure.feature("cli_config")
@allure.severity(allure.severity_level.NORMAL)
def cli_config_002(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOLOGYBUILDER_CONFIG", raising=False)
    (tmp_path / "topologybuilder.yaml").write_text("gns3_project: Lab\n")

    assert load_cli_config() == {"gns3_project": "Lab"}


@allure.title(
    "load_cli_config nutzt den Pfad aus TOPOLOGYBUILDER_CONFIG, falls gesetzt"
)
@allure.description(
    "Überprüft, dass load_cli_config bei gesetzter TOPOLOGYBUILDER_CONFIG-"
    "Umgebungsvariable ausschließlich diesen Pfad verwendet, statt die "
    "Standardpfade im Arbeitsverzeichnis zu suchen"
)
@allure.tag("positiv-test", "cli_config")
@allure.feature("cli_config")
@allure.severity(allure.severity_level.CRITICAL)
def cli_config_003(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    custom_path = tmp_path / "custom-config.yml"
    custom_path.write_text("esxi_username: root\n")
    (tmp_path / "topologybuilder.yml").write_text("esxi_username: should-not-be-used\n")
    monkeypatch.setenv("TOPOLOGYBUILDER_CONFIG", str(custom_path))

    assert load_cli_config() == {"esxi_username": "root"}


@allure.title("load_cli_config gibt ein leeres Dict für eine leere Config-Datei zurück")
@allure.description(
    "Überprüft, dass load_cli_config ein leeres Dict statt None zurückgibt, "
    "wenn topologybuilder.yml existiert, aber leer ist (yaml.safe_load "
    "liefert dann None)"
)
@allure.tag("negativ-test", "cli_config")
@allure.feature("cli_config")
@allure.severity(allure.severity_level.NORMAL)
def cli_config_004(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOLOGYBUILDER_CONFIG", raising=False)
    (tmp_path / "topologybuilder.yml").write_text("")

    assert load_cli_config() == {}
