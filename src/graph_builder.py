__license__ = "GNU GPLv3"

from src.factories import NodeFactory, GenericNode


class GraphBuilder:
    """
    Facade of factories to build easier graphs
    """

    def __init__(self, nodes, edges, addressing=None):
        """
        Initializes the GraphBuilder class
        :param nodes: dict of nodes from the config file
        :param edges: list of edges from the config file
        :param addressing: list of optional per-interface IP addressing
            entries from the config file's 'addressing' key, or None
        """
        self._config_nodes = nodes
        self._config_edges = edges
        self._config_addressing = addressing or []
        self._nodes = {}

    def _build_nodes(self):
        """
        Builds all the nodes in the graph. Saves the result to self._nodes
        :return:
        """
        for node_group in self._config_nodes:
            image = node_group["image"]
            role = node_group["role"]
            if node_group["names"] is None:
                continue
            for name in node_group["names"]:
                self._nodes[name] = NodeFactory().create_node(image, role, name)

    def _build_edges(self):
        """
        Builds all the edges in the graph. In-Place operation for self._nodes
        :return:
        """
        if not self._nodes:
            raise ValueError("No nodes created. Call _build_nodes() first.")
        for edge in self._config_edges:
            intf_1 = self._nodes[edge[0]].add_interface(edge[1])
            intf_2 = self._nodes[edge[2]].add_interface(edge[3])
            NodeFactory().create_edge(intf_1, intf_2)

    def _apply_addressing(self):
        """
        Applies the optional per-interface IP addressing from the config
        file's 'addressing' list onto the already-built interfaces. In-Place
        operation for self._nodes
        :return:
        """
        for entry in self._config_addressing:
            node = self._nodes[entry["node"]]
            node.interfaces[entry["interface"]].ip = entry["ip"]

    def build(self) -> dict[str, GenericNode]:
        """
        Builds the graph
        :return: new graph
        """
        self._build_nodes()
        self._build_edges()
        self._apply_addressing()
        return self._nodes
