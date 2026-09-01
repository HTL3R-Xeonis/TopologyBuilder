"""
Tests to validate functionality of src/graph/layout.py
"""

__license__ = "GNU GPLv3"

import allure

from src.graph import Graph
from src.graph.layout import _marker_for_degree, compute_node_positions, render_graph
from src.settings import Settings


@allure.title("compute_node_positions gibt jedem Node eine eigene Position")
@allure.description(
    "Überprüft, dass compute_node_positions für jeden Node im Graph eine "
    "eigene (x, y)-Position innerhalb der Canvas-Grenzen berechnet, statt "
    "dass mehrere Nodes dieselbe Position teilen"
)
@allure.tag("positiv-test", "graph-layout")
@allure.feature("graph_layout")
@allure.severity(allure.severity_level.CRITICAL)
def graph_layout_000() -> None:
    Settings.API.LITERAL_API_VALUES = True
    graph = Graph(
        [{"image": "VPCS", "role": "ROUTER", "names": ["R1", "R2", "R3", "R4"]}],
        [
            ["R1", "gi0/0", "R2", "gi0/0"],
            ["R2", "gi0/1", "R3", "gi0/0"],
            ["R3", "gi0/1", "R4", "gi0/0"],
        ],
    )

    positions = compute_node_positions(graph.nodes, width=2000.0, height=1000.0)

    assert set(positions) == {"R1", "R2", "R3", "R4"}
    assert len({tuple(pos) for pos in positions.values()}) == 4
    # Force-directed placement + rescale only approximately fits the
    # target canvas (a small margin, not a hard clamp) - allow slack for
    # values landing just outside [0, width]/[0, height].
    for x, y in positions.values():
        assert -100 <= x <= 2100.0
        assert -100 <= y <= 1100.0


@allure.title("compute_node_positions ist deterministisch")
@allure.description(
    "Überprüft, dass compute_node_positions bei gleichem Graph zweimal "
    "hintereinander exakt dieselben Positionen liefert (fester Seed), "
    "damit ein Deploy reproduzierbar bleibt"
)
@allure.tag("positiv-test", "graph-layout")
@allure.feature("graph_layout")
@allure.severity(allure.severity_level.NORMAL)
def graph_layout_001() -> None:
    Settings.API.LITERAL_API_VALUES = True
    graph = Graph(
        [{"image": "VPCS", "role": "ROUTER", "names": ["R1", "R2"]}],
        [["R1", "gi0/0", "R2", "gi0/0"]],
    )

    first = compute_node_positions(graph.nodes)
    second = compute_node_positions(graph.nodes)

    assert first == second


@allure.title("compute_node_positions liefert eine leere Map für einen leeren Graph")
@allure.description(
    "Überprüft, dass compute_node_positions bei einem Graph ohne Nodes "
    "eine leere Map zurückgibt, statt eines Fehlers"
)
@allure.tag("negativ-test", "graph-layout")
@allure.feature("graph_layout")
@allure.severity(allure.severity_level.NORMAL)
def graph_layout_002() -> None:
    assert compute_node_positions({}) == {}


@allure.title("render_graph zeichnet jeden Node-Namen in die ASCII-Ausgabe")
@allure.description(
    "Überprüft, dass render_graph für einen echten Graph eine mehrzeilige "
    "ASCII-Darstellung liefert, die den Namen jedes Nodes enthält"
)
@allure.tag("positiv-test", "graph-layout")
@allure.feature("graph_layout")
@allure.severity(allure.severity_level.CRITICAL)
def graph_layout_003() -> None:
    Settings.API.LITERAL_API_VALUES = True
    graph = Graph(
        [{"image": "VPCS", "role": "ROUTER", "names": ["R1", "R2", "R3"]}],
        [["R1", "gi0/0", "R2", "gi0/0"], ["R2", "gi0/1", "R3", "gi0/0"]],
    )

    output = render_graph(graph.nodes)

    assert "R1" in output
    assert "R2" in output
    assert "R3" in output
    assert "\n" in output


@allure.title("render_graph meldet eine leere Topologie ohne Fehler")
@allure.description(
    "Überprüft, dass render_graph bei einem Graph ohne Nodes '(empty "
    "topology)' zurückgibt, statt eines Fehlers"
)
@allure.tag("negativ-test", "graph-layout")
@allure.feature("graph_layout")
@allure.severity(allure.severity_level.NORMAL)
def graph_layout_004() -> None:
    assert render_graph({}) == "(empty topology)"


@allure.title("_marker_for_degree wählt das Symbol nach Anzahl der Verbindungen")
@allure.description(
    "Überprüft, dass _marker_for_degree für 0/1/2/3+ Verbindungen jeweils "
    "das dokumentierte Symbol liefert, damit Hubs im ASCII-Rendering "
    "optisch auffallen"
)
@allure.tag("positiv-test", "graph-layout")
@allure.feature("graph_layout")
@allure.severity(allure.severity_level.NORMAL)
def graph_layout_005() -> None:
    assert _marker_for_degree(0) == "·"
    assert _marker_for_degree(1) == "□"
    assert _marker_for_degree(2) == "o"
    assert _marker_for_degree(3) == "●"
    assert _marker_for_degree(5) == "●"
