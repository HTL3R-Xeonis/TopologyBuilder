__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from loguru import logger

from src.graph.blocks import GenericNode
from src.graph.blocks.formatter import nested_formatter
from src.graph.topology_layout import TopologyLayout, TopologyPattern


class Graph:
    """
    Object which represents a graph of nodes.
    """

    def __init__(self, nodes: list[dict[str, str]], edges: list[list[str]]):
        """
        :param nodes: Node definitions from the topology file.
        :param edges: Links with the interfaces at both endpoints.
        :raises RuntimeError: If a link references an unknown node.
        :raises ValueError: If a node image or interface is invalid.
        :raises IndexError: If a link definition is incomplete.
        """

        self._nodes: dict[str, GenericNode] = {}
        self._edges: list[tuple[str, str, str, str]] = []
        self._build_nodes(nodes)
        self._build_edges(edges)
        self._ensure_esxi_interfaces()

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
        :param edges_config: Links with their source and target interfaces.
        :raises RuntimeError: If a referenced node does not exist.
        :raises ValueError: If an interface is invalid or already in use.
        :raises IndexError: If a link definition is incomplete.
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
            self._edges.append((edge[0], edge[1], edge[2], edge[3]))

    def _ensure_esxi_interfaces(self) -> None:
        """
        Adds a default interface to ESXi nodes without graph connections.
        :raises ValueError: If no VLAN ID is available for the default interface.
        """
        from src.graph import Environment

        for node in self.nodes.values():
            if node.env == Environment.ON_ESXI and not node.interfaces:
                node.add_interface("Gi0/0")

    def _create_layout(self) -> TopologyLayout:
        """
        Creates a layout engine for the current topology.
        :return: Structure-aware topology layout instance.
        """
        return TopologyLayout(self.nodes, ((source, target) for source, _, target, _ in self._edges))

    def get_node_positions(
        self, spacing: tuple[int, int] = (180, 110), origin: tuple[int, int] = (0, 0)
    ) -> dict[str, tuple[int, int]]:
        """
        Returns stable graph node coordinates for visualization or GNS3.
        :param spacing: Horizontal and vertical distances per layout unit.
        :param origin: Offset added to all node positions.
        :return: Dictionary mapping node names to integer coordinates.
        :raises ValueError: If the coordinate spacing is invalid.
        """
        return self._create_layout().get_positions(spacing=spacing, origin=origin)

    def get_topology_patterns(self) -> list[TopologyPattern]:
        """
        Returns recognized structures of the topology graph.
        :return: Detected whole-graph and subgraph patterns.
        """
        return self._create_layout().get_patterns()

    def visualize(self, show_interfaces: bool = False, interactive: bool = True) -> None:
        """
        Displays the structure-aware graph in the terminal.
        :param show_interfaces: Whether to label link endpoints with their interfaces.
        :param interactive: Whether to navigate oversized diagrams in a viewport.
        :raises OSError: If interactive terminal input cannot be configured.
        """
        from src.graph.visualizer import GraphVisualizer

        GraphVisualizer(self).render(show_interfaces=show_interfaces, interactive=interactive)

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
        return f"{self.__class__.__name__}:\n  nodes: {nested_formatter('  nodes: ', list(self.nodes.values()))}"
