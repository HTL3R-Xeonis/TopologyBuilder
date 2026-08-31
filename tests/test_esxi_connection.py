"""
Tests to validate functionality of src/connections/esxi_connection.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock

import allure
import pytest

from src.connections.esxi_connection import ESXiConnection
from src.settings import Settings


def _make_esxi_connection() -> ESXiConnection:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn.view_manager = MagicMock()
    return conn


def _reset_settings() -> None:
    Settings.ONLY_ON_GNS3 = False
    Settings.ONLY_ON_ESXI = False
    Settings.IS_DRY_RUN = False


@allure.title(
    "ensure_bridging_security_policy aktiviert promiscuous mode und forged transmits"
)
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy UpdatePortGroup mit "
    "einer Security-Policy aufruft, die promiscuous mode, MAC changes und "
    "forged transmits aktiviert, wenn die Port-Group das noch nicht tut"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_000() -> None:
    _reset_settings()
    conn = _make_esxi_connection()

    port_group = MagicMock()
    port_group.spec.name = "PG_GNS3_TRUNK"
    port_group.spec.policy = None

    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = [port_group]
    conn._get_object_by_name = MagicMock(return_value=host_system)

    conn.ensure_bridging_security_policy("PG_GNS3_TRUNK")

    network_system = host_system.configManager.networkSystem
    network_system.UpdatePortGroup.assert_called_once()
    _, kwargs = network_system.UpdatePortGroup.call_args
    assert kwargs["pgName"] == "PG_GNS3_TRUNK"
    spec = kwargs["portgrp"]
    assert spec.policy.security.allowPromiscuous is True
    assert spec.policy.security.macChanges is True
    assert spec.policy.security.forgedTransmits is True


@allure.title(
    "ensure_bridging_security_policy ist ein No-Op, wenn bereits korrekt gesetzt"
)
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy UpdatePortGroup nicht "
    "erneut aufruft, wenn die Port-Group bereits promiscuous mode, MAC "
    "changes und forged transmits akzeptiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_001() -> None:
    from pyVmomi import vim

    _reset_settings()
    conn = _make_esxi_connection()

    security = vim.host.NetworkPolicy.SecurityPolicy()
    security.allowPromiscuous = True
    security.macChanges = True
    security.forgedTransmits = True
    policy = vim.host.NetworkPolicy()
    policy.security = security

    port_group = MagicMock()
    port_group.spec.name = "PG_GNS3_TRUNK"
    port_group.spec.policy = policy

    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = [port_group]
    conn._get_object_by_name = MagicMock(return_value=host_system)

    conn.ensure_bridging_security_policy("PG_GNS3_TRUNK")

    host_system.configManager.networkSystem.UpdatePortGroup.assert_not_called()


@allure.title("ensure_bridging_security_policy überspringt alles im Dry-Run-Modus")
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy im Dry-Run-Modus keine "
    "ESXi-API aufruft"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_002() -> None:
    _reset_settings()
    Settings.IS_DRY_RUN = True
    conn = _make_esxi_connection()
    conn._get_object_by_name = MagicMock()

    try:
        conn.ensure_bridging_security_policy("PG_GNS3_TRUNK")
    finally:
        _reset_settings()

    conn._get_object_by_name.assert_not_called()


@allure.title(
    "ensure_bridging_security_policy wirft einen Fehler, wenn die Port-Group nicht existiert"
)
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy einen RuntimeError "
    "wirft, wenn keine Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_003() -> None:
    _reset_settings()
    conn = _make_esxi_connection()

    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = []
    conn._get_object_by_name = MagicMock(return_value=host_system)

    with pytest.raises(RuntimeError, match=r"Port group PG_GNS3_TRUNK not found"):
        conn.ensure_bridging_security_policy("PG_GNS3_TRUNK")
