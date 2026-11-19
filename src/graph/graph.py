__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from loguru import logger
from rich.console import Console
from rich.tree import Tree

from src.graph.blocks import GenericNode
from src.graph.blocks.formatter import nested_formatter
from src.graph.blocks.vlan import VirtualLan
from src.graph.environment import Environment
from src.graph.layout import render_graph


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
        self._edges: list[tuple[str, str, str, str]] = [
            (edge[0], edge[1], edge[2], edge[3]) for edge in edges
        ]
        self._build_nodes(nodes)
        self._build_edges(edges)
        self._assign_vlans()

    @property
    def edges(self) -> list[tuple[str, str, str, str]]:
        """
        The links as (node1, interface1, node2, interface2), exactly as in the config file. Two nodes can be
        linked more than once over different interfaces, which the interfaces' own ``neighbour`` (a node)
        cannot express.
        :return: Returns a copy of this attribute
        """
        return list(self._edges)

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

            if_1.connect_to(node_2, if_2)
            if_2.connect_to(node_1, if_1)

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
                    neighbour_interface = interface.peer or neighbour.get_interface(
                        node
                    )
                    if neighbour_interface is not None and (
                        neighbour_interface.vlan is not None
                    ):
                        interface.vlan = neighbour_interface.vlan
                        continue

                interface.vlan = VirtualLan(node.name, if_name)

    def vlans(self) -> list[VirtualLan]:
        """
        The distinct VirtualLan objects of the graph in the order ``_assign_vlans`` created them (a direct
        ESXi-to-ESXi link shares one object between its two interfaces and is listed once).
        :return: the VLANs of all ESXi interfaces
        """
        found: list[VirtualLan] = []
        for node in self.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is not None and all(vlan is not other for other in found):
                    found.append(vlan)
        return found

    def adopt_vlan_ids(self, existing: dict[str, int]) -> list[tuple[str, int, int]]:
        """
        Makes the VLAN ids of an incremental deploy stable. ``_assign_vlans`` numbers the VLANs by their position
        in the file, so a link added in the middle of the file would shift every later id, while the port groups
        already on ESXi keep theirs (and a new one could end up sharing an id with an old one). This gives every
        VLAN whose port group already exists that port group's id, and every new VLAN the lowest id that no port
        group on the vSwitch uses. Without any existing port group nothing changes (the positional ids stay).
        A port group whose id another VLAN of this graph already took keeps its place on ESXi but gets a new id
        here; that is reported so the caller can refuse to deploy or repair it.
        :param existing: name -> VLAN id of the port groups on the vSwitch (the trunk and others may be included)
        :return: (port group name, id on ESXi, id assigned here) of every VLAN that could not keep its ESXi id
        :raises ValueError: Is thrown when no free id is left.
        """
        if not existing:
            return []
        vlans = self.vlans()
        graph_names = {vlan.name for vlan in vlans}
        claimed: set[int] = set()
        unresolved: list[VirtualLan] = []
        conflicts: list[tuple[str, int, int]] = []
        for vlan in vlans:
            actual = existing.get(vlan.name)
            if actual is None or actual in claimed or not 2 <= actual <= 4093:
                unresolved.append(vlan)
                continue
            vlan.id = actual
            claimed.add(actual)
        foreign = {
            vlan_id for name, vlan_id in existing.items() if name not in graph_names
        }
        next_id = 2
        for vlan in unresolved:
            while next_id in claimed or next_id in foreign:
                next_id += 1
            if next_id > 4093:
                raise ValueError("VLANs on ESXi exceed the limit of 4093.")
            if vlan.name in existing:
                conflicts.append((vlan.name, existing[vlan.name], next_id))
            vlan.id = next_id
            claimed.add(next_id)
        return conflicts

    def visualize(self) -> None:
        """
        Visualizes the graph in the terminal as a force-directed ASCII
        node-link diagram, sized to fit the current terminal width.
        :return:
        """
        print(render_graph(self.nodes))

    def print_connection_tree(self) -> None:
        """
        Prints a colored tree listing each device and the devices it is
        connected to, via its interfaces - an alternative to visualize()'s
        ASCII diagram, better suited to reading off exact interface-to-
        interface wiring rather than seeing the overall topology shape.
        :return:
        """
        tree = Tree("[bold]Topology[/bold]")

        for name, node in self.nodes.items():
            device = tree.add(
                f"[bold cyan]{name}[/bold cyan] [dim]({node.image})[/dim]"
            )

            interfaces = list(node.interfaces.items())
            if not interfaces:
                device.add("[dim](no interfaces)[/dim]")
                continue

            for if_name, interface in interfaces:
                neighbour = interface.neighbour
                if neighbour is None:
                    device.add(f"[yellow]{if_name}[/yellow] [dim]-- unconnected[/dim]")
                    continue

                neighbour_interface = interface.peer or neighbour.get_interface(node)
                neighbour_if_name = (
                    neighbour_interface.name if neighbour_interface else "?"
                )
                device.add(
                    f"[yellow]{if_name}[/yellow] [dim]->[/dim] "
                    f"[bold green]{neighbour.name}[/bold green]"
                    f"[dim]:{neighbour_if_name}[/dim]"
                )

        Console().print(tree)

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
