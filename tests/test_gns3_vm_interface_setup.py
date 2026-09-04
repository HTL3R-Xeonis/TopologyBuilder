"""
Tests to validate functionality of src/vm_orchestrator/gns3_vm_interface_setup.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock

import allure

from src.graph.blocks.generic_node import GenericNode
from src.graph.blocks.vlan import VirtualLan
from src.settings import Settings
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup


def _reset_settings() -> None:
    Settings.IS_DRY_RUN = False
    Settings.API.LITERAL_API_VALUES = True


@allure.title(
    "_create_subinterface_creation_commands dedupliziert geteilte VLAN-Objekte"
)
@allure.description(
    "Überprüft, dass _create_subinterface_creation_commands nur ein "
    "'ip link add' pro eindeutiger VLAN-ID erzeugt - ein direkter "
    "ESXi-zu-ESXi-Link teilt sich dasselbe VirtualLan-Objekt zwischen "
    "beiden Interfaces (siehe Graph._assign_vlans), und ohne diese "
    "Deduplizierung würde der zweite 'ip link add' mit demselben Namen "
    "fehlschlagen und wegen 'set -e' das gesamte restliche Skript abbrechen"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_000() -> None:
    _reset_settings()

    node_a = GenericNode("Ubuntu-Server", "VM", "VM_A")
    interface_a = node_a.add_interface("ens160")
    shared_vlan = VirtualLan("VM_A", "ens160")
    interface_a.vlan = shared_vlan

    node_b = GenericNode("Ubuntu-Server", "VM", "VM_B")
    interface_b = node_b.add_interface("ens160")
    interface_b.vlan = shared_vlan

    graph = MagicMock()
    graph.nodes = {"VM_A": node_a, "VM_B": node_b}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert setup.script.count(f"name {shared_vlan.name} type vlan") == 1


@allure.title(
    "_create_subinterface_creation_commands erzeugt einen Befehl pro eigener VLAN-ID"
)
@allure.description(
    "Überprüft, dass zwei Interfaces mit unterschiedlichen VirtualLan-"
    "Objekten (kein geteilter direkter ESXi-ESXi-Link) jeweils ihren "
    "eigenen 'ip link add'-Befehl bekommen"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_001() -> None:
    _reset_settings()
    VirtualLan.reset()

    node_a = GenericNode("Ubuntu-Server", "VM", "PC4")
    interface_a = node_a.add_interface("gi0/0")
    interface_a.vlan = VirtualLan("PC4", "gi0/0")

    node_b = GenericNode("Ubuntu-Server", "VM", "PC5")
    interface_b = node_b.add_interface("gi0/0")
    interface_b.vlan = VirtualLan("PC5", "gi0/0")

    graph = MagicMock()
    graph.nodes = {"PC4": node_a, "PC5": node_b}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert setup.script.count("type vlan") == 2
    assert f"name {interface_a.vlan.name} type vlan" in setup.script
    assert f"name {interface_b.vlan.name} type vlan" in setup.script


@allure.title("_create_subinterface_creation_commands überspringt Interfaces ohne VLAN")
@allure.description(
    "Überprüft, dass ein Interface ohne zugewiesenes VLAN (z.B. ein rein "
    "GNS3-gehostetes Node) keinen 'ip link add'-Befehl erzeugt"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_002() -> None:
    _reset_settings()

    node = GenericNode("VPCS", "PC", "PC1")
    node.add_interface("Ethernet0")

    graph = MagicMock()
    graph.nodes = {"PC1": node}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert "type vlan" not in setup.script


@allure.title(
    "_create_subinterface_creation_commands erzeugt gar keinen Befehl für einen direkten ESXi-ESXi-Link"
)
@allure.description(
    "Überprüft, dass ein direkter ESXi-zu-ESXi-Link (beide Interfaces via "
    "connect_to auf den jeweils anderen Node verweisend, beide Nodes mit "
    "einem ESXi-Image) überhaupt kein 'ip link add' erzeugt - die VLAN "
    "existiert rein an der ESXi-Seite, es gibt nichts, das über die GNS3-VM "
    "geroutet werden müsste"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_003() -> None:
    _reset_settings()

    node_a = GenericNode("Ubuntu-Server", "VM", "VM_A")
    interface_a = node_a.add_interface("ens160")
    shared_vlan = VirtualLan("VM_A", "ens160")
    interface_a.vlan = shared_vlan

    node_b = GenericNode("Ubuntu-Server", "VM", "VM_B")
    interface_b = node_b.add_interface("ens160")
    interface_b.vlan = shared_vlan

    interface_a.connect_to(node_b)
    interface_b.connect_to(node_a)

    graph = MagicMock()
    graph.nodes = {"VM_A": node_a, "VM_B": node_b}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert "type vlan" not in setup.script
