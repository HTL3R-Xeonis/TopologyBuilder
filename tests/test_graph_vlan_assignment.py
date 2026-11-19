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


@allure.title(
    "Graph.edges liefert die Kanten so, wie sie in der Config stehen, auch parallele"
)
@allure.description(
    "Überprüft, dass Graph.edges jede Kante als (Knoten1, Interface1, Knoten2, Interface2) "
    "behält, auch wenn zwei Knoten über verschiedene Interfaces mehrfach verbunden sind - "
    "die Interfaces kennen als neighbour nur den Knoten, nicht das Interface der Gegenseite"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.NORMAL)
def graph_vlan_005() -> None:
    Settings.API.LITERAL_API_VALUES = True
    VirtualLan.reset()
    edges = [["R1", "gi0/0", "VM1", "ens160"], ["R1", "gi0/1", "VM1", "ens192"]]
    graph = Graph(_NODES, edges)

    assert graph.edges == [
        ("R1", "gi0/0", "VM1", "ens160"),
        ("R1", "gi0/1", "VM1", "ens192"),
    ]


@allure.title("Jedes Interface kennt seine Gegenstelle, auch bei parallelen Kanten")
@allure.description(
    "Überprüft, dass Interface.peer bei zwei Kanten zwischen denselben Nodes jeweils das Interface der "
    "Gegenseite ist (get_interface liefert dagegen immer nur das erste)"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_006() -> None:
    Settings.API.LITERAL_API_VALUES = True
    VirtualLan.reset()
    edges = [["R1", "gi0/0", "VM1", "ens160"], ["R1", "gi0/1", "VM1", "ens192"]]
    graph = Graph(_NODES, edges)
    r1, vm1 = graph.nodes["R1"], graph.nodes["VM1"]

    assert r1.interfaces["gi0/1"].peer is vm1.interfaces["ens192"]
    assert vm1.interfaces["ens192"].peer is r1.interfaces["gi0/1"]
    assert (
        r1.get_interface("VM1") is r1.interfaces["gi0/0"]
    )  # first only, which is why peer exists


_PC_NODES = [
    {"image": "Ubuntu-Server", "role": "VM", "names": ["PC1", "PC2", "PC3"]},
    {"image": "VPCS", "role": "ROUTER", "names": ["R1"]},
]
_PC_EDGES = [
    ["PC1", "eth0", "R1", "gi0/0"],
    ["PC2", "eth0", "PC3", "eth0"],
    ["PC3", "eth1", "R1", "gi0/1"],
]
# what ESXi holds after the first deploy of _PC_EDGES (ids by position: 2, 3 shared, 4)
_DEPLOYED_IDS = {
    "PC1_eth0": 2,
    "PC2_eth0": 3,
    "PC3_eth1": 4,
    "PG_GNS3_TRUNK": 4095,
}


def _ids(graph: Graph) -> dict[str, int]:
    return {vlan.name: vlan.id for vlan in graph.vlans()}


@allure.title(
    "adopt_vlan_ids hält die Ids bestehender Port-Groups beim Einfügen eines Links stabil"
)
@allure.description(
    "Ein neuer Link in der Mitte der Datei verschiebt die positionsbasierten Ids aller späteren "
    "(Design 10.3, H1). adopt_vlan_ids gibt den bestehenden VLANs die Id ihrer Port-Group und dem "
    "neuen die nächste freie."
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_007() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [*_PC_EDGES[:1], ["PC1", "eth1", "R1", "gi0/2"], *_PC_EDGES[1:]]
    graph = Graph(_PC_NODES, edges)
    # by position the new link takes 3 and pushes the shared link to 4, PC3_eth1 to 5
    assert _ids(graph) == {
        "PC1_eth0": 2,
        "PC1_eth1": 3,
        "PC2_eth0": 4,
        "PC3_eth1": 5,
    }

    conflicts = graph.adopt_vlan_ids(_DEPLOYED_IDS)

    assert conflicts == []
    assert _ids(graph) == {
        "PC1_eth0": 2,
        "PC1_eth1": 5,
        "PC2_eth0": 3,
        "PC3_eth1": 4,
    }
    shared = graph.nodes["PC2"].interfaces["eth0"].vlan
    assert graph.nodes["PC3"].interfaces["eth0"].vlan is shared


@allure.title("adopt_vlan_ids ändert ohne bestehende Port-Groups nichts")
@allure.description(
    "Erster Deploy (oder keine Port-Groups lesbar): die positionsbasierten Ids bleiben, wie sie waren"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_008() -> None:
    Settings.API.LITERAL_API_VALUES = True
    graph = Graph(_PC_NODES, _PC_EDGES)
    before = _ids(graph)

    assert graph.adopt_vlan_ids({}) == []
    assert graph.adopt_vlan_ids({"PG_GNS3_TRUNK": 4095}) == []

    assert _ids(graph) == before == {"PC1_eth0": 2, "PC2_eth0": 3, "PC3_eth1": 4}


@allure.title(
    "adopt_vlan_ids meldet zwei Port-Groups mit derselben Id und vergibt eine neue"
)
@allure.description(
    "Zustand eines früheren, verschobenen Deploys: PC1_eth1 und PC2_eth0 haben beide Id 3. "
    "Nur eine behält sie, die andere bekommt eine freie Id und wird als Konflikt gemeldet."
)
@allure.tag("negativ-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.CRITICAL)
def graph_vlan_009() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [*_PC_EDGES[:1], ["PC1", "eth1", "R1", "gi0/2"], *_PC_EDGES[1:]]
    graph = Graph(_PC_NODES, edges)

    conflicts = graph.adopt_vlan_ids({**_DEPLOYED_IDS, "PC1_eth1": 3})

    ids = _ids(graph)
    assert len(set(ids.values())) == len(ids)
    assert ids["PC1_eth1"] == 3  # first in the file keeps it
    assert conflicts == [("PC2_eth0", 3, ids["PC2_eth0"])]
    assert ids["PC2_eth0"] not in (2, 3, 4)


@allure.title("adopt_vlan_ids vergibt keine Id einer fremden Port-Group neu")
@allure.description(
    "Eine Port-Group, die nicht (mehr) zum Graphen gehört (z. B. Rest eines entfernten Links), "
    "behält ihre Id: ein neuer Link bekommt sie nicht, sonst wären beide Links im selben VLAN"
)
@allure.tag("positiv-test", "graph")
@allure.feature("graph")
@allure.severity(allure.severity_level.NORMAL)
def graph_vlan_010() -> None:
    Settings.API.LITERAL_API_VALUES = True
    edges = [*_PC_EDGES, ["PC1", "eth1", "R1", "gi0/2"]]
    graph = Graph(_PC_NODES, edges)

    graph.adopt_vlan_ids({**_DEPLOYED_IDS, "LEFTOVER_eth0": 5})

    assert _ids(graph)["PC1_eth1"] == 6
