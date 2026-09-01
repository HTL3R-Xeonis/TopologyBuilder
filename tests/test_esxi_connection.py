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
        patch.object(conn, "set_vm_annotation") as mock_set_annotation,
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
    mock_set_annotation.assert_called_once_with(
        fake_vm, "topologybuilder-image:Ubuntu-Server"
    )
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


@allure.title("_add_port_group ist ein No-Op, wenn die Port-Group bereits existiert")
@allure.description(
    "Überprüft, dass _add_port_group AddPortGroup nicht aufruft, wenn "
    "bereits eine Port-Group mit dem VLAN-Namen existiert - Voraussetzung "
    "dafür, dass ein incremental-Deploy auf denselben Port-Groups erneut "
    "laufen kann, ohne einen Fehler zu werfen"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_020() -> None:
    from src.graph.blocks.vlan import VirtualLan

    _reset_settings()
    conn = _make_esxi_connection()

    existing = MagicMock()
    existing.spec.name = "VM1_ens160"
    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = [existing]
    conn._get_object_by_name = MagicMock(return_value=host_system)

    vlan = VirtualLan("VM1", "ens160")
    conn._add_port_group(vlan)

    host_system.configManager.networkSystem.AddPortGroup.assert_not_called()


@allure.title("_add_port_group erstellt eine fehlende Port-Group")
@allure.description(
    "Überprüft, dass _add_port_group AddPortGroup aufruft, wenn noch keine "
    "Port-Group mit dem VLAN-Namen existiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_021() -> None:
    from src.graph.blocks.vlan import VirtualLan

    _reset_settings()
    conn = _make_esxi_connection()

    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = []
    conn._get_object_by_name = MagicMock(return_value=host_system)

    vlan = VirtualLan("VM1", "ens160")
    conn._add_port_group(vlan)

    host_system.configManager.networkSystem.AddPortGroup.assert_called_once()


@allure.title(
    "deploy_virtual_machine überspringt eine bereits existierende VM im incremental-Modus"
)
@allure.description(
    "Überprüft, dass deploy_virtual_machine im incremental-Modus weder die "
    "OVA herunterlädt noch importiert, wenn bereits eine VM mit dem "
    "Node-Namen existiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_022() -> None:
    from src.graph.blocks.generic_node import GenericNode

    _reset_settings()
    Settings.API.LITERAL_API_VALUES = True
    conn = _make_esxi_connection()
    conn.find_vms_matching = MagicMock(return_value=[MagicMock()])

    node = GenericNode("Ubuntu-Server", "VM", "VM1")
    node.add_interface("ens160")

    with patch(
        "src.connections.esxi_connection.APIHandler.download_ova"
    ) as mock_download:
        conn.deploy_virtual_machine(node, "datastore1", incremental=True)

    mock_download.assert_not_called()


@allure.title("is_vm_powered_on erkennt eine eingeschaltete VM")
@allure.description(
    "Überprüft, dass is_vm_powered_on True zurückgibt, wenn "
    "vm.runtime.powerState 'poweredOn' ist"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_023() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOn

    assert conn.is_vm_powered_on(vm) is True


@allure.title("is_vm_powered_on erkennt eine ausgeschaltete VM")
@allure.description(
    "Überprüft, dass is_vm_powered_on False zurückgibt, wenn "
    "vm.runtime.powerState nicht 'poweredOn' ist"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_024() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOff

    assert conn.is_vm_powered_on(vm) is False


@allure.title("get_vm_network_names liefert die Port-Group jedes Ethernet-Adapters")
@allure.description(
    "Überprüft, dass get_vm_network_names für jedes "
    "VirtualEthernetCard-Gerät den Namen der verbundenen Port-Group "
    "zurückgibt und andere Gerätetypen überspringt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_025() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    disk = MagicMock()
    disk.__class__ = vim.vm.device.VirtualDisk
    nic = MagicMock()
    nic.__class__ = vim.vm.device.VirtualEthernetCard
    nic.backing.deviceName = "PG-GNS3-TRUNK"
    vm = MagicMock()
    vm.config.hardware.device = [disk, nic]

    assert conn.get_vm_network_names(vm) == ["PG-GNS3-TRUNK"]


@allure.title("get_all_vms liefert jede registrierte VM")
@allure.description(
    "Überprüft, dass get_all_vms alle VMs aus der ContainerView zurückgibt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_026() -> None:
    conn = _make_esxi_connection()
    conn.content = MagicMock()

    vms = [MagicMock(), MagicMock()]
    container_view = MagicMock()
    container_view.view = vms
    conn.view_manager.CreateContainerView.return_value = container_view

    assert conn.get_all_vms() == vms
    container_view.Destroy.assert_called_once()


@allure.title("find_gns3_vm findet die einzige VM mit 'gns3' im Namen")
@allure.description(
    "Überprüft, dass find_gns3_vm die einzige VM zurückgibt, deren Name "
    "'gns3' enthält (Groß-/Kleinschreibung wird ignoriert), und andere VMs "
    "ignoriert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_027() -> None:
    conn = _make_esxi_connection()
    conn.content = MagicMock()

    gns3_vm = MagicMock()
    gns3_vm.name = "GNS3-VM (1)"
    other_vm = MagicMock()
    other_vm.name = "PC4"
    container_view = MagicMock()
    container_view.view = [other_vm, gns3_vm]
    conn.view_manager.CreateContainerView.return_value = container_view

    assert conn.find_gns3_vm() is gns3_vm


@allure.title("find_gns3_vm gibt None zurück, wenn keine VM passt")
@allure.description(
    "Überprüft, dass find_gns3_vm None zurückgibt, wenn keine VM 'gns3' im "
    "Namen enthält"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_028() -> None:
    conn = _make_esxi_connection()
    conn.content = MagicMock()

    other_vm = MagicMock()
    other_vm.name = "PC4"
    container_view = MagicMock()
    container_view.view = [other_vm]
    conn.view_manager.CreateContainerView.return_value = container_view

    assert conn.find_gns3_vm() is None


@allure.title("find_gns3_vm wirft einen Fehler bei mehreren passenden VMs")
@allure.description(
    "Überprüft, dass find_gns3_vm einen ValueError wirft, wenn mehr als "
    "eine VM 'gns3' im Namen enthält, da dann nicht sicher geraten werden "
    "kann, welche die echte GNS3-VM ist"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_029() -> None:
    conn = _make_esxi_connection()
    conn.content = MagicMock()

    vm_a = MagicMock()
    vm_a.name = "GNS3-VM (1)"
    vm_b = MagicMock()
    vm_b.name = "GNS3-VM-backup"
    container_view = MagicMock()
    container_view.view = [vm_a, vm_b]
    conn.view_manager.CreateContainerView.return_value = container_view

    with pytest.raises(ValueError, match="Multiple VMs look like a GNS3 VM"):
        conn.find_gns3_vm()


@allure.title("set_vm_annotation setzt das Annotation-Feld über ReconfigVM_Task")
@allure.description(
    "Überprüft, dass set_vm_annotation ReconfigVM_Task mit einem ConfigSpec "
    "aufruft, dessen annotation-Feld den übergebenen Text trägt, und auf "
    "den Task wartet"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_030() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()
    vm = MagicMock()
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.success
    vm.ReconfigVM_Task.return_value = task

    conn.set_vm_annotation(vm, "topologybuilder-image:Ubuntu-Server")

    vm.ReconfigVM_Task.assert_called_once()
    spec = vm.ReconfigVM_Task.call_args.kwargs["spec"]
    assert spec.annotation == "topologybuilder-image:Ubuntu-Server"


@allure.title("remove_vm_network_adapters entfernt die letzten N Ethernet-Adapter")
@allure.description(
    "Überprüft, dass remove_vm_network_adapters nur die letzten `count` "
    "Ethernet-Geräte über ReconfigVM_Task entfernt, in Geräte-Reihenfolge, "
    "und andere Gerätetypen (z.B. eine Disk) unangetastet lässt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_031() -> None:
    from pyVmomi import vim

    conn = _make_esxi_connection()

    disk = MagicMock()
    disk.__class__ = vim.vm.device.VirtualDisk
    nic_0 = MagicMock()
    nic_0.__class__ = vim.vm.device.VirtualVmxnet3
    nic_1 = MagicMock()
    nic_1.__class__ = vim.vm.device.VirtualVmxnet3
    nic_2 = MagicMock()
    nic_2.__class__ = vim.vm.device.VirtualVmxnet3

    vm = MagicMock()
    vm.config.hardware.device = [disk, nic_0, nic_1, nic_2]
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.success
    vm.ReconfigVM_Task.return_value = task

    conn.remove_vm_network_adapters(vm, 2)

    vm.ReconfigVM_Task.assert_called_once()
    device_changes = vm.ReconfigVM_Task.call_args.kwargs["spec"].deviceChange
    assert [change.device for change in device_changes] == [nic_1, nic_2]
    assert all(
        change.operation == vim.vm.device.VirtualDeviceSpec.Operation.remove
        for change in device_changes
    )


@allure.title("deploy_virtual_machine staged die OVA in Settings.ESXI.OVA_STAGING_DIR")
@allure.description(
    "Überprüft, dass deploy_virtual_machine die OVA in dem via "
    "Settings.ESXI.OVA_STAGING_DIR konfigurierten Verzeichnis statt im "
    "OS-Standard-Temp-Verzeichnis staged (relevant wenn /tmp ein "
    "größenbegrenztes tmpfs ist), und dieses Verzeichnis bei Bedarf anlegt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_032(tmp_path) -> None:
    from src.graph.blocks.generic_node import GenericNode
    from src.graph.blocks.vlan import VirtualLan

    _reset_settings()
    Settings.API.LITERAL_API_VALUES = True
    staging_dir = str(tmp_path / "does-not-exist-yet")
    Settings.ESXI.OVA_STAGING_DIR = staging_dir
    conn = _make_esxi_connection()

    node = GenericNode("Ubuntu-Server", "VM", "VM1")
    interface = node.add_interface("ens160")
    interface.vlan = VirtualLan("VM1", "ens160")

    fake_vm = MagicMock()
    try:
        with (
            patch("src.connections.esxi_connection.APIHandler.download_ova"),
            patch("src.connections.esxi_connection.OVAImporter") as mock_importer_cls,
            patch.object(conn, "set_vm_annotation"),
            patch.object(conn, "power_on_vm"),
        ):
            mock_importer_cls.return_value.import_ova.return_value = fake_vm
            conn.deploy_virtual_machine(node, "datastore1")
    finally:
        Settings.ESXI.OVA_STAGING_DIR = None

    assert (tmp_path / "does-not-exist-yet").is_dir()


@allure.title("ensure_virtual_switch_exists erstellt eine fehlende vSwitch intern")
@allure.description(
    "Überprüft, dass ensure_virtual_switch_exists AddVirtualSwitch mit "
    "einer reinen internen Spec aufruft (kein physisches Uplink-NIC), "
    "wenn die konfigurierte vSwitch noch nicht existiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_033() -> None:
    _reset_settings()
    conn = _make_esxi_connection()
    conn._find_virtual_switch = MagicMock(return_value=None)

    host_system = MagicMock()
    conn._get_object_by_name = MagicMock(return_value=host_system)

    conn.ensure_virtual_switch_exists()

    network_system = host_system.configManager.networkSystem
    network_system.AddVirtualSwitch.assert_called_once()
    _, kwargs = network_system.AddVirtualSwitch.call_args
    assert kwargs["vswitchName"] == Settings.ESXI.VIRTUAL_SWITCH
    assert not hasattr(kwargs["spec"], "bridge") or kwargs["spec"].bridge is None


@allure.title("ensure_virtual_switch_exists ist ein No-Op, wenn die vSwitch existiert")
@allure.description(
    "Überprüft, dass ensure_virtual_switch_exists AddVirtualSwitch nicht "
    "aufruft, wenn die konfigurierte vSwitch bereits existiert"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_034() -> None:
    _reset_settings()
    conn = _make_esxi_connection()
    conn._find_virtual_switch = MagicMock(return_value=MagicMock())
    conn._get_object_by_name = MagicMock()

    conn.ensure_virtual_switch_exists()

    conn._get_object_by_name.assert_not_called()


@allure.title("ensure_virtual_switch_exists überspringt alles im Dry-Run-Modus")
@allure.description(
    "Überprüft, dass ensure_virtual_switch_exists im Dry-Run-Modus keine "
    "ESXi-API aufruft, wenn die vSwitch fehlt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_035() -> None:
    _reset_settings()
    Settings.IS_DRY_RUN = True
    conn = _make_esxi_connection()
    conn._find_virtual_switch = MagicMock(return_value=None)
    conn._get_object_by_name = MagicMock()

    try:
        conn.ensure_virtual_switch_exists()
    finally:
        _reset_settings()

    conn._get_object_by_name.assert_not_called()


@allure.title("find_biggest_datastore wählt das Datastore mit dem meisten freien Platz")
@allure.description(
    "Überprüft, dass find_biggest_datastore aus allen Datastores das mit "
    "dem größten summary.freeSpace zurückgibt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_036() -> None:
    conn = _make_esxi_connection()

    small = MagicMock()
    small.summary.freeSpace = 100 * 1024**3
    big = MagicMock()
    big.summary.freeSpace = 3000 * 1024**3
    conn.get_all_datastores = MagicMock(return_value=[small, big])

    assert conn.find_biggest_datastore() is big


@allure.title(
    "find_biggest_datastore wirft einen Fehler, wenn kein Datastore existiert"
)
@allure.description(
    "Überprüft, dass find_biggest_datastore einen ValueError wirft, wenn "
    "der Host gar kein Datastore hat"
)
@allure.tag("negativ-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_037() -> None:
    conn = _make_esxi_connection()
    conn._ip_address = "10.20.20.202"
    conn.get_all_datastores = MagicMock(return_value=[])

    with pytest.raises(ValueError, match="No datastore found"):
        conn.find_biggest_datastore()


@allure.title("ensure_trunk_port_group_exists erstellt eine fehlende Trunk-Port-Group")
@allure.description(
    "Überprüft, dass ensure_trunk_port_group_exists AddPortGroup mit VLAN "
    "4095 (pass-all-tags) aufruft, wenn die konfigurierte Trunk-Port-Group "
    "noch nicht existiert, und danach die Bridging-Security-Policy setzt"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.CRITICAL)
def esxi_connection_038() -> None:
    _reset_settings()
    conn = _make_esxi_connection()

    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = []
    conn._get_object_by_name = MagicMock(return_value=host_system)
    conn.ensure_bridging_security_policy = MagicMock()

    conn.ensure_trunk_port_group_exists()

    network_system = host_system.configManager.networkSystem
    network_system.AddPortGroup.assert_called_once()
    spec = network_system.AddPortGroup.call_args.args[0]
    assert spec.name == Settings.ESXI.TRUNK_PORT_GROUP
    assert spec.vlanId == 4095
    conn.ensure_bridging_security_policy.assert_called_once_with(
        Settings.ESXI.TRUNK_PORT_GROUP
    )


@allure.title(
    "ensure_trunk_port_group_exists setzt nur die Policy, wenn die Trunk-Port-Group existiert"
)
@allure.description(
    "Überprüft, dass ensure_trunk_port_group_exists AddPortGroup nicht "
    "aufruft, wenn die Trunk-Port-Group bereits existiert, aber "
    "ensure_bridging_security_policy trotzdem aufruft"
)
@allure.tag("positiv-test", "esxi-connection")
@allure.feature("esxi_connection")
@allure.severity(allure.severity_level.NORMAL)
def esxi_connection_039() -> None:
    _reset_settings()
    conn = _make_esxi_connection()

    existing = MagicMock()
    existing.spec.name = Settings.ESXI.TRUNK_PORT_GROUP
    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = [existing]
    conn._get_object_by_name = MagicMock(return_value=host_system)
    conn.ensure_bridging_security_policy = MagicMock()

    conn.ensure_trunk_port_group_exists()

    host_system.configManager.networkSystem.AddPortGroup.assert_not_called()
    conn.ensure_bridging_security_policy.assert_called_once_with(
        Settings.ESXI.TRUNK_PORT_GROUP
    )
