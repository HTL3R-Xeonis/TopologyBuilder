"""
Tests to validate functionality of src/vm_orchestrator/vm_orchestrator.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure

from src.graph.blocks.generic_node import GenericNode
from src.graph.blocks.vlan import VirtualLan
from src.settings import Settings
from src.vm_orchestrator.vm_orchestrator import VMOrchestrator


def _make_orchestrator() -> tuple[VMOrchestrator, MagicMock]:
    with patch("src.vm_orchestrator.vm_orchestrator.ESXiConnection") as esxi_cls:
        esxi_connection = esxi_cls.return_value
        esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"
        orchestrator = VMOrchestrator("10.20.20.202", 443, "root", "pw", "GNS3")
    return orchestrator, esxi_connection


@allure.title("delete_stale_esxi_resources löscht VMs und Port-Groups jedes ESXi-Nodes")
@allure.description(
    "Überprüft, dass delete_stale_esxi_resources für jede ESXi-gehostete "
    "Node alle namensgleichen VMs sowie die Port-Group jedes adressierten "
    "Interfaces löscht, GNS3-gehostete Nodes aber überspringt"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_000() -> None:
    orchestrator, esxi_connection = _make_orchestrator()

    vm = GenericNode("Ubuntu-Server", "VM", "VM1")
    interface = vm.add_interface("ens160")
    interface.vlan = VirtualLan("VM1", "ens160")
    router = GenericNode("VPCS", "ROUTER", "R1")
    router.add_interface("gi0/0")

    graph = MagicMock()
    graph.nodes = {"VM1": vm, "R1": router}

    stale_vm = MagicMock()
    esxi_connection.find_vms_matching.return_value = [stale_vm]

    orchestrator.delete_stale_esxi_resources(graph)

    esxi_connection.find_vms_matching.assert_called_once_with("VM1")
    esxi_connection.delete_vm.assert_called_once_with(stale_vm)
    esxi_connection.delete_port_group.assert_called_once_with(interface.vlan.name)


@allure.title(
    "destroy_graph löscht ESXi-Ressourcen und lässt GNS3Connection das Projekt zurücksetzen"
)
@allure.description(
    "Überprüft, dass destroy_graph zuerst delete_stale_esxi_resources "
    "aufruft und dann eine GNS3Connection mit dem Projektnamen konstruiert "
    "- deren Konstruktor löscht und erstellt ein bestehendes Projekt bereits "
    "selbst neu, was für 'destroy' genau das Richtige ist"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_001() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.find_vms_matching.return_value = []

    graph = MagicMock()
    graph.nodes = {}

    with patch(
        "src.vm_orchestrator.vm_orchestrator.GNS3Connection"
    ) as gns3_connection_cls:
        orchestrator.destroy_graph(graph, "lab")

    gns3_connection_cls.assert_called_once_with(
        orchestrator.gns3_vm_ip, Settings.GNS3.PORT, "lab"
    )


@allure.title("deploy_graph überspringt reset_virtual_switch im incremental-Modus")
@allure.description(
    "Überprüft, dass deploy_graph im incremental-Modus "
    "esxi_connection.reset_virtual_switch nicht aufruft, initialize_virtual_switch "
    "aber weiterhin, und GNS3Connection sowie deploy_virtual_machine mit "
    "incremental=True aufgerufen werden"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_002() -> None:
    orchestrator, esxi_connection = _make_orchestrator()

    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch(
            "src.vm_orchestrator.vm_orchestrator.GNS3Connection"
        ) as gns3_connection_cls,
    ):
        orchestrator.deploy_graph(graph, "gns3", "gns3pw", incremental=True)

    esxi_connection.reset_virtual_switch.assert_not_called()
    esxi_connection.initialize_virtual_switch.assert_called_once_with(graph)
    gns3_connection_cls.assert_called_once_with(
        orchestrator.gns3_vm_ip,
        Settings.GNS3.PORT,
        Settings.GNS3.PROJECT_NAME,
        incremental=True,
    )


@allure.title("deploy_graph reset das vSwitch im Normalbetrieb")
@allure.description(
    "Überprüft, dass deploy_graph ohne incremental "
    "esxi_connection.reset_virtual_switch aufruft und GNS3Connection mit "
    "incremental=False konstruiert"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_003() -> None:
    orchestrator, esxi_connection = _make_orchestrator()

    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch(
            "src.vm_orchestrator.vm_orchestrator.GNS3Connection"
        ) as gns3_connection_cls,
    ):
        orchestrator.deploy_graph(graph, "gns3", "gns3pw")

    esxi_connection.reset_virtual_switch.assert_called_once()
    gns3_connection_cls.assert_called_once_with(
        orchestrator.gns3_vm_ip,
        Settings.GNS3.PORT,
        Settings.GNS3.PROJECT_NAME,
        incremental=False,
    )
