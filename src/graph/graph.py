__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.graph.blocks import GenericNode
from src.graph.blocks.formatter import nested_formatter

import networkx as nx
from phart import ASCIIRenderer, LayoutOptions, NodeStyle


class Graph:
    """
    Object which represents a graph of nodes.
    """

    def __init__(self, nodes: list[dict[str, str]], edges: list[list[str]]):
        """
        :param nodes: dict of nodes from the config file
        :param edges: list of edges from the config file
        """
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise TypeError

        self._nodes: dict[str, GenericNode] = {}
        self._build_nodes(nodes)
        self._build_edges(edges)

    @property
    def nodes(self) -> dict[str, GenericNode]:
        """
        A dictionary of nodes, where each node is mapped to its name.
        :return: Returns this attribute
        """
        return self._nodes

    def _build_nodes(self, node_config: list[dict[str, str]]) -> None:
        """
        Creates all the specified nodes in the graph.
        :param node_config: dict of nodes from the config file
        :return:
        """

        for node_group in node_config:
            image = node_group["image"]
            role = node_group["role"]
            if node_group["names"] is None:
                continue

            for name in node_group["names"]:
                self._nodes[name] = GenericNode(image, role, name)

    def _build_edges(self, edges_config: list[list[str]]) -> None:
        """
        Creates all the needed interfaces for each edge and connects both nodes with each other.
        :param edges_config: list of edges from the config file
        :return:
        :raise ValueError: Is thrown when a node which should have existed in the graph doesn't exist.
        """
        for edge in edges_config:
            if edge[0] not in self.nodes:
                raise ValueError(f"Node {edge[0]} not found in graph")
            if edge[2] not in self.nodes:
                raise ValueError(f"Node {edge[2]} not found in graph")

            node_1 = self.nodes[edge[0]]
            node_2 = self.nodes[edge[2]]
            if_1 = node_1.add_interface(edge[1])
            if_2 = node_2.add_interface(edge[3])

            if_1.connect_to(node_2)
            if_2.connect_to(node_1)

    def visulize(self):
        G = nx.Graph()

        for node_name in self.nodes:
            G.add_node(node_name)

        node_names = {id(node): name for name, node in self.nodes.items()}

        seen = set()

        for node_name, node in self.nodes.items():
            for interface_name, interface in node.interfaces.items():
                neighbour = interface.neighbour

                if neighbour is None:
                    continue

                neighbour_name = node_names.get(id(neighbour))

                if neighbour_name is None:
                    continue

                edge_key = frozenset((node_name, neighbour_name))

                if edge_key in seen:
                    continue

                seen.add(edge_key)

                G.add_edge(
                    node_name,
                    neighbour_name,
                    interface=interface_name,
                )

        renderer = ASCIIRenderer(
            G,
            options=LayoutOptions(
                node_style=NodeStyle.SQUARE,
                layout_strategy="kamada_kawai",
            ),
        )

        print(renderer.render())

    def __str__(self) -> str:
        """
        Nicely formatted string representation of this object.
        :return: String representing this object.
        """
        return f"{self.__class__.__name__}:\n  nodes: {list(self.nodes)}"

    def __repr__(self) -> str:
        """
        Compact representation of this object.
        :return: String representing this object.
        """
        return (
            f"{self.__class__.__name__}:\n"
            f"  nodes: {nested_formatter('  nodes: ', list(self.nodes.values()))}"
        )
