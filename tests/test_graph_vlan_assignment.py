"""
Tests to validate the VLAN-assignment functionality of src/graph/graph.py
and src/graph/blocks/vlan.py
"""

__license__ = "GNU GPLv3"

import allure

from src.graph import Graph
from src.graph.blocks.vlan import VirtualLan
from src.settings import Settings

_NODES = [
    {"image": "Ubuntu-Server", "role": "VM", "names": ["VM1", "VM2"]},
    {"image": "VPCS", "role": "ROUTER", "names": ["R1"]},
]


@allure.title("VLAN-Zuweisung ist fortlaufend für unabhängige ESXi-Interfaces")
@allure.description(
    "Überprüft, dass Graph jedem unabhängigen ESXi-Interface eine eigene, "
    "fortlaufende VLAN-ID ab 2 zuweist"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_000() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [["VM1", "ens160", "R1", "gi0/0"], ["VM2", "ens160", "R1", "gi0/1"]]
    graph = Graph(_NODES, edges)

    assert graph.nodes["VM1"].interfaces["ens160"].vlan.id == 2
    assert graph.nodes["VM2"].interfaces["ens160"].vlan.id == 3


@allure.title("Direkt verbundene ESXi-Nodes teilen sich dieselbe VLAN")
@allure.description(
    "Überprüft, dass zwei ESXi-gehostete Nodes, die direkt (ohne GNS3-Node "
    "dazwischen) verbunden sind, dieselbe VirtualLan zugewiesen bekommen, da "
    "es keine Bridge gibt, die zwischen zwei unterschiedlichen VLANs "
    "übersetzen könnte"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_001() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [["VM1", "ens160", "VM2", "ens160"]]
    graph = Graph(_NODES, edges)

    vlan_1 = graph.nodes["VM1"].interfaces["ens160"].vlan
    vlan_2 = graph.nodes["VM2"].interfaces["ens160"].vlan
    assert vlan_1 is vlan_2
    assert vlan_1.id == vlan_2.id


@allure.title("Über GNS3 gebrückte ESXi-Interfaces behalten ihr eigenes VLAN")
@allure.description(
    "Überprüft, dass eine Edge zwischen einer ESXi- und einer GNS3-gehosteten "
    "Node weiterhin eine eigene VLAN-ID für das ESXi-Interface erhält, statt "
    "sich fälschlich ein VLAN mit einem anderen, direkt verbundenen ESXi-"
    "Interface zu teilen"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_002() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [
        ["VM1", "ens160", "VM2", "ens160"],
        ["VM1", "ens192", "R1", "gi0/0"],
    ]
    graph = Graph(_NODES, edges)

    assert (
        graph.nodes["VM1"].interfaces["ens192"].vlan.id
        != graph.nodes["VM1"].interfaces["ens160"].vlan.id
    )


@allure.title("VLAN-Zähler wird bei jedem neuen Graph zurückgesetzt")
@allure.description(
    "Überprüft, dass ein neu gebauter Graph nicht die VLAN-Nummerierung "
    "eines vorher im selben Prozess gebauten Graphen erbt"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_003() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [["VM1", "ens160", "R1", "gi0/0"]]

    Graph(_NODES, edges)
    second_graph = Graph(_NODES, edges)

    assert second_graph.nodes["VM1"].interfaces["ens160"].vlan.id == 2


@allure.title("VirtualLan.reset setzt den Zähler auf 2 zurück")
@allure.description("Überprüft, dass VirtualLan.reset() den Zähler auf 2 zurücksetzt")
@allure.tag("positiv-test", "vlan")
@allure.feature("vlan")
@allure.severity(allure.severity_level.NORMAL)
def graph_vlan_004() -> None:
    VirtualLan("A", "eth0")
    VirtualLan("B", "eth0")
    VirtualLan.reset()
    assert VirtualLan("C", "eth0").id == 2
