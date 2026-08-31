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


@allure.title(
    "find_vms_matching findet exakte Treffer und automatisch umbenannte Duplikate"
)
@allure.description(
    "Überprüft, dass find_vms_matching sowohl die exakt benannte VM als "
    "auch von ESXi bei Namenskollisionen automatisch umbenannte Duplikate "
    "(z.B. 'PC4_1', 'PC4 (1)') findet, aber keine unverwandten VMs mit "
    "ähnlichem Namen wie 'PC40' oder 'MyPC4'"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_014() -> None:
    conn = _make_esxi_connection()
    conn.content = MagicMock()

    vms = []
    for name in ["PC4", "PC4_1", "PC4 (1)", "PC40", "MyPC4", "PC5"]:
        vm = MagicMock()
        vm.name = name
        vms.append(vm)

    container_view = MagicMock()
    container_view.view = vms
    conn.view_manager.CreateContainerView.return_value = container_view

    matches = {vm.name for vm in conn.find_vms_matching("PC4")}
    assert matches == {"PC4", "PC4_1", "PC4 (1)"}


@allure.title("delete_vm fährt eine laufende VM herunter und zerstört sie danach")
@allure.description(
    "Überprüft, dass delete_vm eine laufende VM zuerst über PowerOffVM_Task "
    "herunterfährt und danach über Destroy_Task entfernt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_015() -> None:
    from pyVmomi import vim

    _reset_settings()
    conn = _make_esxi_connection()

    vm = MagicMock()
    vm.name = "PC4"
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOn
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.success
    vm.PowerOffVM_Task.return_value = task
    vm.Destroy_Task.return_value = task

    conn.delete_vm(vm)

    vm.PowerOffVM_Task.assert_called_once()
    vm.Destroy_Task.assert_called_once()


@allure.title("delete_vm überspringt alles im Dry-Run-Modus")
@allure.description(
    "Überprüft, dass delete_vm im Dry-Run-Modus weder PowerOffVM_Task noch "
    "Destroy_Task aufruft"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_016() -> None:
    _reset_settings()
    Settings.IS_DRY_RUN = True
    conn = _make_esxi_connection()
    vm = MagicMock()
    vm.name = "PC4"

    try:
        conn.delete_vm(vm)
    finally:
        _reset_settings()

    vm.PowerOffVM_Task.assert_not_called()
    vm.Destroy_Task.assert_not_called()


@allure.title("delete_port_group löscht eine vorhandene Port-Group")
@allure.description(
    "Überprüft, dass delete_port_group eine vorhandene Port-Group über "
    "RemovePortGroup entfernt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_017() -> None:
    _reset_settings()
    conn = _make_esxi_connection()

    existing = MagicMock()
    existing.spec.name = "VM1_ens160"
    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = [existing]
    conn._get_object_by_name = MagicMock(return_value=host_system)

    conn.delete_port_group("VM1_ens160")

    host_system.configManager.networkSystem.RemovePortGroup.assert_called_once_with(
        pgName="VM1_ens160"
    )


@allure.title("delete_port_group ist ein No-Op, wenn die Port-Group nicht existiert")
@allure.description(
    "Überprüft, dass delete_port_group keine Löschanfrage sendet, wenn die "
    "Port-Group nicht existiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_018() -> None:
    _reset_settings()
    conn = _make_esxi_connection()

    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = []
    conn._get_object_by_name = MagicMock(return_value=host_system)

    conn.delete_port_group("VM1_ens160")

    host_system.configManager.networkSystem.RemovePortGroup.assert_not_called()


@allure.title("list_port_groups gibt Name, VLAN-ID und vSwitch jeder Port-Group zurück")
@allure.description(
    "Überprüft, dass list_port_groups für jede Port-Group auf dem "
    "konfigurierten vSwitch ein {'name', 'vlan_id', 'vswitch'} Dict "
    "zurückgibt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_019() -> None:
    conn = _make_esxi_connection()

    pg1 = MagicMock()
    pg1.spec.name = "PG-MGMT"
    pg1.spec.vlanId = 0
    pg2 = MagicMock()
    pg2.spec.name = "VM1_ens160"
    pg2.spec.vlanId = 2
    conn._get_port_groups = MagicMock(return_value=[pg1, pg2])

    result = conn.list_port_groups()

    assert result == [
        {"name": "PG-MGMT", "vlan_id": 0, "vswitch": Settings.ESXI.VIRTUAL_SWITCH},
        {"name": "VM1_ens160", "vlan_id": 2, "vswitch": Settings.ESXI.VIRTUAL_SWITCH},
    ]
