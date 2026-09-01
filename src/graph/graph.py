__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.graph.blocks import GenericNode
from src.graph.blocks.formatter import nested_formatter
from src.graph.blocks.vlan import VirtualLan
from src.graph.environment import Environment
from loguru import logger
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
        :raises ValueError: Is thrown when the image is not found on ESXi or GNS3. May also be thrown when an interface already exists with the given name on the node or too many interfaces with a vlan were created.
        """

        self._nodes: dict[str, GenericNode] = {}
        self._build_nodes(nodes)
        self._build_edges(edges)
        self._assign_vlans()

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
        :raises ValueError: Is thrown when the image is not found on ESXi or GNS3
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
        :raise RuntimeError: Is thrown when a node which should have existed in the graph doesn't exist.
        :raises ValueError: Is thrown when an interface already exists with the given name on the node or too many interfaces with a vlan were created.
        """
        for edge in edges_config:
            if edge[0] not in self.nodes:
                logger.error(msg := f"Node {edge[0]} not found in graph")
                raise RuntimeError(msg)
            if edge[2] not in self.nodes:
                logger.error(msg := f"Node {edge[2]} not found in graph")
                raise RuntimeError(msg)

            node_1 = self.nodes[edge[0]]
            node_2 = self.nodes[edge[2]]
            if_1 = node_1.add_interface(edge[1])
            if_2 = node_2.add_interface(edge[3])

            if_1.connect_to(node_2)
            if_2.connect_to(node_1)

    def _assign_vlans(self) -> None:
        """
        Assigns a VirtualLan to every ESXi-hosted node's interface, now that
        the full edge set is known. A direct ESXi-to-ESXi link (no GNS3
        device between them) gets both sides assigned the SAME VirtualLan,
        since there's no bridging device to translate between two different
        VLANs - the two VMs only reach each other if their vNICs share a
        VLAN. Every other ESXi interface (unconnected, or linked to a GNS3
        node) gets its own unique VLAN. Resets the VLAN id counter first, so
        a freshly built Graph doesn't inherit numbers from a previous one
        built earlier in the same process.
        :return:
        :raises ValueError: Is thrown when the number of VLANs needed exceeds the limit of 4093.
        """
        VirtualLan.reset()
        for node in self.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue
            for if_name, interface in node.interfaces.items():
                if interface.vlan is not None:
                    continue

                neighbour = interface.neighbour
                if neighbour is not None and neighbour.env == Environment.ON_ESXI:
                    neighbour_interface = neighbour.get_interface(node)
                    if neighbour_interface is not None and (
                        neighbour_interface.vlan is not None
                    ):
                        interface.vlan = neighbour_interface.vlan
                        continue

                interface.vlan = VirtualLan(node.name, if_name)

    def visualize(self) -> None:
        """
        Visualizes the graph in the terminal.
        :return:
        """
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
            options=LayoutOptions(node_style=NodeStyle.SQUARE),
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
