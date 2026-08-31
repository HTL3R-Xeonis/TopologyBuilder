"""
Tests to validate functionality of src/connections/esxi_connection.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

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


@allure.title("find_datastore findet ein Datastore anhand des Namens")
@allure.description(
    "Überprüft, dass find_datastore das Datastore mit passendem Namen zurückgibt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_004() -> None:
    conn = _make_esxi_connection()
    datastore = MagicMock()
    conn._get_object_by_name = MagicMock(return_value=datastore)

    assert conn.find_datastore("datastore1") is datastore


@allure.title("find_datastore wirft einen Fehler, wenn kein Datastore passt")
@allure.description(
    "Überprüft, dass find_datastore einen ValueError wirft, wenn kein "
    "Datastore mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_005() -> None:
    conn = _make_esxi_connection()
    conn._get_object_by_name = MagicMock(return_value=None)

    with pytest.raises(ValueError, match=r"Datastore 'datastore1' not found"):
        conn.find_datastore("datastore1")


@allure.title("find_network findet ein Netzwerk anhand des Namens")
@allure.description(
    "Überprüft, dass find_network das Netzwerk/die Port-Group mit "
    "passendem Namen zurückgibt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_006() -> None:
    conn = _make_esxi_connection()
    network = MagicMock()
    conn._get_object_by_name = MagicMock(return_value=network)

    assert conn.find_network("PG-GNS3-TRUNK") is network


@allure.title("find_network wirft einen Fehler, wenn kein Netzwerk passt")
@allure.description(
    "Überprüft, dass find_network einen ValueError wirft, wenn kein "
    "Netzwerk/keine Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_007() -> None:
    conn = _make_esxi_connection()
    conn._get_object_by_name = MagicMock(return_value=None)

    with pytest.raises(
        ValueError, match=r"Network/port group 'PG-GNS3-TRUNK' not found"
    ):
        conn.find_network("PG-GNS3-TRUNK")


@allure.title("power_on_vm schaltet eine ausgeschaltete VM ein")
@allure.description(
    "Überprüft, dass power_on_vm PowerOnVM_Task aufruft, wenn die VM nicht "
    "bereits eingeschaltet ist"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_008() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOff
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.success
    vm.PowerOnVM_Task.return_value = task

    conn.power_on_vm(vm)

    vm.PowerOnVM_Task.assert_called_once()


@allure.title("power_on_vm lässt eine bereits eingeschaltete VM unangetastet")
@allure.description(
    "Überprüft, dass power_on_vm PowerOnVM_Task nicht aufruft, wenn die VM "
    "bereits eingeschaltet ist"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_009() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOn

    conn.power_on_vm(vm)

    vm.PowerOnVM_Task.assert_not_called()


@allure.title("_wait_for_task wirft einen Fehler, wenn der Task fehlschlägt")
@allure.description(
    "Überprüft, dass _wait_for_task einen RuntimeError wirft, wenn der "
    "vSphere-Task im Fehlerzustand endet"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_010() -> None:
    from pyVmomi import vim

    task = MagicMock()
    task.info.state = vim.TaskInfo.State.error
    task.info.error = "boom"

    with pytest.raises(RuntimeError, match=r"vSphere task failed: boom"):
        ESXiConnection._wait_for_task(task)


@allure.title("add_vm_network_adapters fügt einen Adapter pro Netzwerknamen hinzu")
@allure.description(
    "Überprüft, dass add_vm_network_adapters für jeden gegebenen Namen "
    "einen neuen Netzwerkadapter über ReconfigVM_Task hinzufügt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_011() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    conn.find_network = MagicMock(side_effect=lambda name: vim.Network(name))

    vm = MagicMock()
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.success
    vm.ReconfigVM_Task.return_value = task

    conn.add_vm_network_adapters(vm, ["PG-MGMT", "PG-GNS3-TRUNK"])

    vm.ReconfigVM_Task.assert_called_once()
    device_changes = vm.ReconfigVM_Task.call_args.kwargs["spec"].deviceChange
    assert len(device_changes) == 2


@allure.title(
    "deploy_virtual_machine lädt die OVA herunter, importiert sie und schaltet die VM ein"
)
@allure.description(
    "Überprüft, dass deploy_virtual_machine im Normalbetrieb die OVA über "
    "APIHandler.download_ova herunterlädt, über OVAImporter importiert und "
    "die neue VM danach einschaltet"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_012() -> None:
    from src.graph.blocks.generic_node import GenericNode
    from src.graph.blocks.vlan import VirtualLan

    _reset_settings()
    Settings.API.LITERAL_API_VALUES = True
    conn = _make_esxi_connection()

    node = GenericNode("Ubuntu-Server", "VM", "VM1")
    interface = node.add_interface("ens160")
    interface.vlan = VirtualLan("VM1", "ens160")

    fake_vm = MagicMock()
    with (
        patch(
            "src.connections.esxi_connection.APIHandler.download_ova"
        ) as mock_download,
        patch("src.connections.esxi_connection.OVAImporter") as mock_importer_cls,
        patch.object(conn, "power_on_vm") as mock_power_on,
    ):
        mock_importer_cls.return_value.import_ova.return_value = fake_vm
        conn.deploy_virtual_machine(node, "datastore1")

    mock_download.assert_called_once()
    assert mock_download.call_args.args[0] == "Ubuntu-Server"
    mock_importer_cls.return_value.import_ova.assert_called_once()
    import_args = mock_importer_cls.return_value.import_ova.call_args.args
    assert import_args[1] == "VM1"
    assert import_args[2] == "datastore1"
    assert import_args[3] == [interface.vlan.name]
    mock_power_on.assert_called_once_with(fake_vm)


@allure.title("deploy_virtual_machine überspringt alles im Dry-Run-Modus")
@allure.description(
    "Überprüft, dass deploy_virtual_machine im Dry-Run-Modus weder die OVA "
    "herunterlädt noch importiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_013() -> None:
    from src.graph.blocks.generic_node import GenericNode

    _reset_settings()
    Settings.API.LITERAL_API_VALUES = True
    Settings.IS_DRY_RUN = True
    conn = _make_esxi_connection()
    node = GenericNode("Ubuntu-Server", "VM", "VM1")
    node.add_interface("ens160")

    try:
        with patch(
            "src.connections.esxi_connection.APIHandler.download_ova"
        ) as mock_download:
            conn.deploy_virtual_machine(node, "datastore1")
    finally:
        _reset_settings()

    mock_download.assert_not_called()
