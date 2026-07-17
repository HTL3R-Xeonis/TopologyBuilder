__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from factories import NodeFactory, EdgeFactory, GenericNode


class GraphBuilder:
    def __init__(self, nodes, edges):
        self._config_nodes = nodes
        self._config_edges = edges
        self._nodes = {}

    def _build_nodes(self):
        for node_group in self._config_nodes:
            image = node_group["image"]
            role = node_group["role"]
            for name in node_group["names"]:
                self._nodes[name] = NodeFactory().create_node(image, role, name)

    def _build_edges(self):
        if not self._nodes:
            raise ValueError("No nodes created. Use first NodeFactory.build_nodes()")
        for edge in self._config_edges:
            EdgeFactory().create_edge(edge, self._nodes)

    def build(self) -> dict[str, GenericNode]:
        self._build_nodes()
        self._build_edges()
        return self._nodes


if __name__ == "__main__":
    import config_file_handler as cfh

    c = cfh.ConfigFileHandler("./config_file_example.yml")
    c.validate_file()
    g = GraphBuilder(c.nodes, c.edges)
    print(g.build()["POP-ISP1-1"]._interfaces)
