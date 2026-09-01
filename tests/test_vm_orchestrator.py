"""
Tests to validate functionality of src/vm_orchestrator/vm_orchestrator.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest

from src.graph import Graph
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


@allure.title("verify_graph meldet eine nicht gefundene ESXi-VM als fehlgeschlagen")
@allure.description(
    "Überprüft, dass verify_graph einen fehlgeschlagenen Check meldet, "
    "wenn die erwartete ESXi-VM nicht gefunden wird"
)
@allure.tag("negativ-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_004() -> None:
    Settings.API.LITERAL_API_VALUES = True
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.list_port_groups.return_value = []
    esxi_connection.get_vm.return_value = None

    graph = Graph([{"image": "Ubuntu-Server", "role": "VM", "names": ["VM1"]}], [])

    with patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection") as gns3_cls:
        gns3_cls.list_all_projects.return_value = []
        results = orchestrator.verify_graph(graph, "lab")

    assert any(not ok and "VM1" in d and "not found" in d for ok, d in results)


@allure.title(
    "verify_graph erkennt eine fehlende Port-Group bei einem direkten ESXi-Link"
)
@allure.description(
    "Überprüft, dass verify_graph einen fehlgeschlagenen Check meldet, "
    "wenn die von beiden Seiten einer direkten ESXi-ESXi-Verbindung "
    "geteilte Port-Group auf dem ESXi-Host nicht existiert. Main's "
    "Graph._assign_vlans lässt beide Interfaces exakt dieselbe VirtualLan "
    "teilen, es gibt also nur eine Port-Group zu prüfen, keine zwei "
    "potenziell divergierenden."
)
@allure.tag("negativ-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_005() -> None:
    Settings.API.LITERAL_API_VALUES = True
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm.return_value = MagicMock()
    esxi_connection.is_vm_powered_on.return_value = True
    esxi_connection.get_vm_ip_address.return_value = "10.0.0.1"
    esxi_connection.list_port_groups.return_value = []

    graph = Graph(
        [
            {"image": "Ubuntu-Server", "role": "VM", "names": ["VM1"]},
            {"image": "Rocky 9.2", "role": "VM", "names": ["VM2"]},
        ],
        [["VM1", "ens160", "VM2", "ens160"]],
    )
    assert (
        graph.nodes["VM1"].interfaces["ens160"].vlan
        is graph.nodes["VM2"].interfaces["ens160"].vlan
    )

    with patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection") as gns3_cls:
        gns3_cls.list_all_projects.return_value = []
        results = orchestrator.verify_graph(graph, "lab")

    assert any(not ok and "port group" in d and "missing" in d for ok, d in results)


@allure.title(
    "verify_graph bestätigt eine ESXi<->GNS3-Bridge, wenn der gleichnamige Cloud-Node existiert"
)
@allure.description(
    "Überprüft, dass verify_graph einen bestandenen Check meldet, wenn für "
    "eine ESXi<->GNS3-Kante ein GNS3-Node mit dem Namen der ESXi-Node "
    "existiert (main's create_node benennt den Cloud-Node genauso wie die "
    "ESXi-Node, die er bridged)"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_006() -> None:
    Settings.API.LITERAL_API_VALUES = True
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.list_port_groups.return_value = []
    esxi_connection.get_vm.return_value = None

    graph = Graph(
        [
            {"image": "VPCS", "role": "ROUTER", "names": ["R1"]},
            {"image": "Ubuntu-Server", "role": "VM", "names": ["VM1"]},
        ],
        [["R1", "gi0/0", "VM1", "ens160"]],
    )

    with patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection") as gns3_cls:
        gns3_cls.list_all_projects.return_value = [{"project_id": "p1", "name": "lab"}]
        gns3_cls.list_project_nodes.return_value = [
            {"node_id": "n1", "name": "R1", "status": "started"},
            {"node_id": "c1", "name": "VM1", "status": "started"},
        ]
        gns3_cls.list_project_links.return_value = []
        results = orchestrator.verify_graph(graph, "lab")

    assert any(ok and "bridged via Cloud node 'VM1'" in d for ok, d in results)


@allure.title("verify_graph bestätigt einen bestehenden GNS3-internen Link")
@allure.description(
    "Überprüft, dass verify_graph einen bestandenen Check meldet, wenn "
    "zwischen zwei rein GNS3-gehosteten Nodes tatsächlich ein Link mit den "
    "erwarteten Node-IDs existiert"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_007() -> None:
    Settings.API.LITERAL_API_VALUES = True
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.list_port_groups.return_value = []
    esxi_connection.get_vm.return_value = None

    graph = Graph(
        [{"image": "VPCS", "role": "ROUTER", "names": ["R1", "R2"]}],
        [["R1", "gi0/0", "R2", "gi0/0"]],
    )

    with patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection") as gns3_cls:
        gns3_cls.list_all_projects.return_value = [{"project_id": "p1", "name": "lab"}]
        gns3_cls.list_project_nodes.return_value = [
            {"node_id": "n1", "name": "R1", "status": "started"},
            {"node_id": "n2", "name": "R2", "status": "started"},
        ]
        gns3_cls.list_project_links.return_value = [
            {"nodes": [{"node_id": "n1"}, {"node_id": "n2"}]}
        ]
        results = orchestrator.verify_graph(graph, "lab")

    assert any(ok and "R1:gi0/0 <-> R2:gi0/0: linked" in d for ok, d in results)


@allure.title("delete_unused_vms löscht getaggte, nicht mehr im Graph vorkommende VMs")
@allure.description(
    "Überprüft, dass delete_unused_vms nur VMs löscht, die (a) eine "
    "'topologybuilder-image:'-Annotation tragen, (b) nicht die per "
    "find_gns3_vm gefundene GNS3-VM sind, und (c) nicht (auch nicht als "
    "umbenanntes Duplikat) im aktuellen Graph vorkommen - Annotation-lose "
    "VMs wie fremde, nicht von diesem Tool erstellte VMs bleiben immer "
    "unangetastet"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_008() -> None:
    Settings.API.LITERAL_API_VALUES = True
    Settings.ESXI.DELETE_UNUSED_VMS = True
    orchestrator, esxi_connection = _make_orchestrator()

    current_node = GenericNode("Ubuntu-Server", "VM", "PC4")
    graph = MagicMock()
    graph.nodes = {"PC4": current_node}

    gns3_vm = MagicMock()
    gns3_vm.name = "GNS3-VM (1)"
    gns3_vm.config.annotation = "topologybuilder-image:Ubuntu-Server"
    esxi_connection.find_gns3_vm.return_value = gns3_vm

    stale_vm = MagicMock()
    stale_vm.name = "VM1"
    stale_vm.config.annotation = "topologybuilder-image:Ubuntu-Server"

    current_vm = MagicMock()
    current_vm.name = "PC4 (1)"
    current_vm.config.annotation = "topologybuilder-image:Ubuntu-Server"

    untagged_vm = MagicMock()
    untagged_vm.name = "U_U (1)"
    untagged_vm.config.annotation = "user: root"

    esxi_connection.get_all_vms.return_value = [
        gns3_vm,
        stale_vm,
        current_vm,
        untagged_vm,
    ]

    orchestrator.delete_unused_vms(graph)

    esxi_connection.delete_vm.assert_called_once_with(stale_vm)


@allure.title("delete_unused_vms ist ein No-Op, wenn DELETE_UNUSED_VMS deaktiviert ist")
@allure.description(
    "Überprüft, dass delete_unused_vms bei Settings.ESXI.DELETE_UNUSED_VMS "
    "= False weder VMs auflistet noch löscht"
)
@allure.tag("negativ-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_009() -> None:
    Settings.ESXI.DELETE_UNUSED_VMS = False
    orchestrator, esxi_connection = _make_orchestrator()

    graph = MagicMock()
    graph.nodes = {}

    try:
        orchestrator.delete_unused_vms(graph)
    finally:
        Settings.ESXI.DELETE_UNUSED_VMS = True

    esxi_connection.get_all_vms.assert_not_called()
    esxi_connection.delete_vm.assert_not_called()


@allure.title("deploy_graph räumt unused VMs vor dem vSwitch-Reset auf")
@allure.description(
    "Überprüft, dass deploy_graph im Normalbetrieb delete_unused_vms mit "
    "dem Graph aufruft, bevor es fortfährt"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_010() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection"),
        patch.object(orchestrator, "delete_unused_vms") as mock_delete_unused,
    ):
        orchestrator.deploy_graph(graph, "gns3", "gns3pw")

    mock_delete_unused.assert_called_once_with(graph)


@allure.title("deploy_graph überspringt delete_unused_vms im incremental-Modus")
@allure.description(
    "Überprüft, dass deploy_graph im incremental-Modus delete_unused_vms "
    "nicht aufruft, aus demselben Grund wie reset_virtual_switch"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_011() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection"),
        patch.object(orchestrator, "delete_unused_vms") as mock_delete_unused,
    ):
        orchestrator.deploy_graph(graph, "gns3", "gns3pw", incremental=True)

    mock_delete_unused.assert_not_called()


@allure.title(
    "deploy_graph räumt VMs von einer früheren Deploy derselben Topologie auf"
)
@allure.description(
    "Überprüft, dass deploy_graph im Normalbetrieb delete_stale_esxi_"
    "resources mit dem Graph aufruft, bevor es fortfährt - ohne das würde "
    "eine zweite non-incremental Deploy derselben Topologie an der "
    "Port-Group der ersten Deploy scheitern, da deren VM-NIC noch daran "
    "hängt (delete_unused_vms allein greift hier nicht, da diese VM "
    "namentlich zur aktuellen Topologie gehört)"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_012() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection"),
        patch.object(orchestrator, "delete_unused_vms"),
        patch.object(orchestrator, "delete_stale_esxi_resources") as mock_delete_stale,
    ):
        orchestrator.deploy_graph(graph, "gns3", "gns3pw")

    mock_delete_stale.assert_called_once_with(graph)


@allure.title(
    "deploy_graph überspringt delete_stale_esxi_resources im incremental-Modus"
)
@allure.description(
    "Überprüft, dass deploy_graph im incremental-Modus delete_stale_esxi_"
    "resources nicht aufruft, aus demselben Grund wie reset_virtual_switch"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_013() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3Connection"),
        patch.object(orchestrator, "delete_unused_vms"),
        patch.object(orchestrator, "delete_stale_esxi_resources") as mock_delete_stale,
    ):
        orchestrator.deploy_graph(graph, "gns3", "gns3pw", incremental=True)

    mock_delete_stale.assert_not_called()


@allure.title("deploy_graph erfasst SSH-Diagnostik bei einer Console-Port-Kollision")
@allure.description(
    "Überprüft, dass deploy_graph _log_console_port_collision_diagnostics "
    "aufruft, wenn gns3_conn.start_all_nodes mit einem Fehler scheitert, "
    "der wie eine Console-Port-Kollision aussieht, und den Fehler danach "
    "trotzdem weiterwirft"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_014() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch(
            "src.vm_orchestrator.vm_orchestrator.GNS3Connection"
        ) as gns3_connection_cls,
        patch.object(orchestrator, "delete_unused_vms"),
        patch.object(orchestrator, "delete_stale_esxi_resources"),
        patch.object(
            orchestrator, "_log_console_port_collision_diagnostics"
        ) as mock_diagnostics,
    ):
        gns3_connection_cls.return_value.start_all_nodes.side_effect = RuntimeError(
            "Failed to start 1/3 node(s): ['R1']. Errors: ['address already in use']"
        )
        with pytest.raises(RuntimeError):
            orchestrator.deploy_graph(graph, "gns3", "gns3pw")

    mock_diagnostics.assert_called_once_with("gns3", "gns3pw")


@allure.title(
    "deploy_graph erfasst keine SSH-Diagnostik bei einem anderen Node-Start-Fehler"
)
@allure.description(
    "Überprüft, dass deploy_graph _log_console_port_collision_diagnostics "
    "NICHT aufruft, wenn gns3_conn.start_all_nodes mit einem Fehler ohne "
    "Console-Port-Kollisions-Signatur scheitert"
)
@allure.tag("negativ-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_015() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    graph = MagicMock()
    graph.nodes = {}

    with (
        patch("src.vm_orchestrator.vm_orchestrator.SSHConnection"),
        patch("src.vm_orchestrator.vm_orchestrator.GNS3VMInterfaceSetup"),
        patch(
            "src.vm_orchestrator.vm_orchestrator.GNS3Connection"
        ) as gns3_connection_cls,
        patch.object(orchestrator, "delete_unused_vms"),
        patch.object(orchestrator, "delete_stale_esxi_resources"),
        patch.object(
            orchestrator, "_log_console_port_collision_diagnostics"
        ) as mock_diagnostics,
    ):
        gns3_connection_cls.return_value.start_all_nodes.side_effect = RuntimeError(
            "Failed to start 1/3 node(s): ['R1']. Errors: ['500 server error']"
        )
        with pytest.raises(RuntimeError):
            orchestrator.deploy_graph(graph, "gns3", "gns3pw")

    mock_diagnostics.assert_not_called()


@allure.title("_partially_link_gns3_nodes überspringt eine direkte ESXi-ESXi-Kante")
@allure.description(
    "Überprüft, dass _partially_link_gns3_nodes connect_nodes NICHT "
    "aufruft, wenn beide Enden einer Kante ESXi-gehostet sind - beide VMs "
    "teilen sich bereits direkt eine Port-Group auf ESXi-Ebene "
    "(Graph._assign_vlans), ein GNS3-Link zwischen ihren Cloud-Nodes wäre "
    "redundant und wird von GNS3 ohnehin mit 409 Conflict abgelehnt"
)
@allure.tag("negativ-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_016() -> None:
    Settings.API.LITERAL_API_VALUES = True
    vm_a = GenericNode("Ubuntu-Server", "VM", "VM-A")
    vm_b = GenericNode("Ubuntu-Server", "VM", "VM-B")
    if_a = vm_a.add_interface("gi0/0")
    if_b = vm_b.add_interface("gi0/0")
    if_a.connect_to(vm_b)
    if_b.connect_to(vm_a)
    vm_a.gns3_node_info = {"node_id": "cloud-a"}
    vm_b.gns3_node_info = {"node_id": "cloud-b"}

    gns3_connection = MagicMock()
    VMOrchestrator._partially_link_gns3_nodes(gns3_connection, vm_a)

    gns3_connection.connect_nodes.assert_not_called()


@allure.title("_partially_link_gns3_nodes verlinkt weiterhin eine ESXi-GNS3-Brücke")
@allure.description(
    "Überprüft, dass _partially_link_gns3_nodes connect_nodes weiterhin "
    "aufruft, wenn eine Kante ein ESXi-gehostetes Node mit einem "
    "GNS3-gehosteten Node verbindet - nur die reine ESXi-ESXi-Kante wird "
    "übersprungen, die Cloud-Node-Brücke wird weiterhin verlinkt"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_017() -> None:
    Settings.API.LITERAL_API_VALUES = True
    esxi_node = GenericNode("Ubuntu-Server", "VM", "VM-A")
    gns3_node = GenericNode("VPCS", "ROUTER", "R1")
    esxi_if = esxi_node.add_interface("gi0/0")
    gns3_if = gns3_node.add_interface("gi0/0")
    esxi_if.connect_to(gns3_node)
    gns3_if.connect_to(esxi_node)
    esxi_node.gns3_node_info = {"node_id": "cloud-a"}
    gns3_node.gns3_node_info = {"node_id": "r1"}

    gns3_connection = MagicMock()
    VMOrchestrator._partially_link_gns3_nodes(gns3_connection, esxi_node)

    gns3_connection.connect_nodes.assert_called_once_with(esxi_node, gns3_node)
