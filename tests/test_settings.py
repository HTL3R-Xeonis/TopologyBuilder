"""
Tests to validate functionality of src/settings/settings.py
"""

__license__ = "GNU GPLv3"

import allure
import pytest
import yaml

from src.settings import Settings


def _write_settings(tmp_path, data: dict) -> str:
    path = tmp_path / "settings.yml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def _reset_esxi_gns3_defaults() -> None:
    Settings.ESXI.IP = "10.20.20.200"
    Settings.ESXI.PORT = 443
    Settings.ESXI.USERNAME = "root"
    Settings.ESXI.VIRTUAL_SWITCH = "internal_network"
    Settings.ESXI.TRUNK_PORT_GROUP = "PG_GNS3_TRUNK"
    Settings.ESXI.IGNORE_PORT_GROUPS = {"PG_GNS3_TRUNK"}
    Settings.ESXI.DATASTORE = "datastore1 (2)"
    Settings.ESXI.GNS3_VM_NAME = "GNS3 (1)"
    Settings.GNS3.USERNAME = "gns3"
    Settings.GNS3.PROJECT_NAME = "tb_gns3_project"
    Settings.GNS3.PORT = 80
    Settings.GNS3.PARENT_INTERFACE = "eth1"
    Settings.TOPOLOGY_FILE = "./topology_example.yaml"


@allure.title("initialise_settings wendet jeden unterstützten Schlüssel an")
@allure.description(
    "Überprüft, dass initialise_settings jeden unterstützten Schlüssel aus "
    "der YAML-Datei auf die entsprechende Settings-Klasse (Settings, "
    "Settings.ESXI, Settings.GNS3, Settings.API) anwendet"
)
@allure.tag("positiv-test", "settings")
@allure.feature("settings")
@allure.severity(allure.severity_level.CRITICAL)
def settings_000(tmp_path) -> None:
    _reset_esxi_gns3_defaults()
    path = _write_settings(
        tmp_path,
        {
            "topology_file": "./my_topology.yaml",
            "esxi": {
                "ip": "10.20.20.202",
                "username": "admin",
                "virtual_switch": "vSwitch1",
                "trunk_port_group": "PG-GNS3-TRUNK",
                "ignore_port_groups": ["PG-GNS3-TRUNK", "PG-MGMT"],
                "datastore": "VNX-FC-Datastore-ESXi3",
                "gns3_vm_name": "GNS3-VM (1)",
            },
            "gns3": {
                "username": "gns3user",
                "project_name": "my_lab",
                "port": 8080,
                "parent_interface": "eth2",
            },
            "api": {
                "esxi_template_server_url": "http://example.com:8000",
                "gns3_template_server_url": "http://example.com:8001",
            },
        },
    )

    try:
        Settings.initialise_settings(path)

        assert Settings.TOPOLOGY_FILE == "./my_topology.yaml"
        assert Settings.ESXI.IP == "10.20.20.202"
        assert Settings.ESXI.USERNAME == "admin"
        assert Settings.ESXI.VIRTUAL_SWITCH == "vSwitch1"
        assert Settings.ESXI.TRUNK_PORT_GROUP == "PG-GNS3-TRUNK"
        assert Settings.ESXI.IGNORE_PORT_GROUPS == {"PG-GNS3-TRUNK", "PG-MGMT"}
        assert Settings.ESXI.DATASTORE == "VNX-FC-Datastore-ESXi3"
        assert Settings.ESXI.GNS3_VM_NAME == "GNS3-VM (1)"
        assert Settings.GNS3.USERNAME == "gns3user"
        assert Settings.GNS3.PROJECT_NAME == "my_lab"
        assert Settings.GNS3.PORT == 8080
        assert Settings.GNS3.PARENT_INTERFACE == "eth2"
        assert Settings.API.ESXI_TEMPLATE_SERVER_URL == "http://example.com:8000"
        assert Settings.API.GNS3_TEMPLATE_SERVER_URL == "http://example.com:8001"
    finally:
        _reset_esxi_gns3_defaults()


@allure.title("initialise_settings lässt fehlende Schlüssel unverändert")
@allure.description(
    "Überprüft, dass initialise_settings nur die im File tatsächlich "
    "angegebenen Schlüssel überschreibt, alle anderen bleiben beim "
    "aktuellen Wert"
)
@allure.tag("positiv-test", "settings")
@allure.feature("settings")
@allure.severity(allure.severity_level.NORMAL)
def settings_001(tmp_path) -> None:
    _reset_esxi_gns3_defaults()
    path = _write_settings(tmp_path, {"esxi": {"ip": "10.20.20.202"}})

    try:
        Settings.initialise_settings(path)

        assert Settings.ESXI.IP == "10.20.20.202"
        assert Settings.ESXI.USERNAME == "root"
        assert Settings.ESXI.DATASTORE == "datastore1 (2)"
    finally:
        _reset_esxi_gns3_defaults()


@allure.title("initialise_settings lehnt ein Passwort unter 'esxi' ab")
@allure.description(
    "Überprüft, dass initialise_settings einen ValueError wirft, wenn die "
    "Datei ein 'password' unter 'esxi' enthält - Passwörter gehören in "
    "Umgebungsvariablen/CLI-Optionen, nicht in eine Datei auf der Platte"
)
@allure.tag("negativ-test", "settings")
@allure.feature("settings")
@allure.severity(allure.severity_level.CRITICAL)
def settings_002(tmp_path) -> None:
    path = _write_settings(tmp_path, {"esxi": {"password": "hunter2"}})

    with pytest.raises(ValueError, match=r"Passwords are not supported"):
        Settings.initialise_settings(path)


@allure.title("initialise_settings lehnt ein Passwort unter 'gns3' ab")
@allure.description(
    "Überprüft, dass initialise_settings einen ValueError wirft, wenn die "
    "Datei ein 'password' unter 'gns3' enthält"
)
@allure.tag("negativ-test", "settings")
@allure.feature("settings")
@allure.severity(allure.severity_level.CRITICAL)
def settings_003(tmp_path) -> None:
    path = _write_settings(tmp_path, {"gns3": {"password": "hunter2"}})

    with pytest.raises(ValueError, match=r"Passwords are not supported"):
        Settings.initialise_settings(path)


@allure.title("initialise_settings mit einer leeren Datei ändert nichts")
@allure.description(
    "Überprüft, dass initialise_settings mit einer leeren YAML-Datei keine "
    "Settings verändert und keinen Fehler wirft"
)
@allure.tag("positiv-test", "settings")
@allure.feature("settings")
@allure.severity(allure.severity_level.NORMAL)
def settings_004(tmp_path) -> None:
    _reset_esxi_gns3_defaults()
    path = tmp_path / "empty.yml"
    path.write_text("")

    try:
        Settings.initialise_settings(str(path))
        assert Settings.ESXI.IP == "10.20.20.200"
    finally:
        _reset_esxi_gns3_defaults()


@allure.title("initialise_settings wirft einen Fehler, wenn die Datei nicht existiert")
@allure.description(
    "Überprüft, dass initialise_settings einen FileNotFoundError wirft, "
    "wenn keine Datei am gegebenen Pfad existiert"
)
@allure.tag("negativ-test", "settings")
@allure.feature("settings")
@allure.severity(allure.severity_level.NORMAL)
def settings_005() -> None:
    with pytest.raises(FileNotFoundError):
        Settings.initialise_settings("./does-not-exist.yml")
