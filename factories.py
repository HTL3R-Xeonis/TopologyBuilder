__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


class NodeFactory:
    _registry: dict[str, type] = {}

    @classmethod
    def register_role(cls, role: str):
        def wrapper(func):
            cls._registry[role] = func
            return func

        return wrapper

    def create_node(self, image: str, role: str, name: str) -> GenericNode:
        node = self._registry[role](image, name)
        return node


class EdgeFactory:
    @staticmethod
    def create_edge(edge_group: list, nodes: dict[str, GenericNode]) -> Edge:
        intf_1 = nodes[edge_group[0]].add_interface(edge_group[1])
        intf_2 = nodes[edge_group[2]].add_interface(edge_group[3])
        edge = Edge(intf_1, intf_2)
        intf_1.edge = edge
        intf_2.edge = edge
        return edge


class Interface:
    def __init__(self, if_name: str, node: GenericNode):
        self._if_name = if_name
        self._node = node

    @property
    def name(self) -> str:
        return self._if_name

    @property
    def node(self) -> GenericNode:
        return self._node

    @property
    def edge(self):
        return getattr(self, "_edge", None)

    @edge.setter
    def edge(self, edge: Edge) -> None:
        self._edge = edge

    def __str__(self) -> str:
        return f"{self.name}"

    def __repr__(self) -> str:
        return f"Interface({self.name}, {self.node.name})"


class Edge:
    def __init__(self, interface_1: Interface, interface_2: Interface):
        self.incidence_1 = interface_1
        self.incidence_2 = interface_2

    def __repr__(self) -> str:
        return f"Edge({repr(self.incidence_1)}, {repr(self.incidence_2)})"

    def __str__(self) -> str:
        return f"{self.incidence_1.node} <--> {self.incidence_2.node}"


class GenericNode:
    def __init__(self, image: str, name: str):
        self.image = image
        self.name = name
        self._interfaces = {}

    def add_interface(self, if_name: str) -> Interface:
        if if_name in self._interfaces:
            raise ValueError(f"Interface {if_name} already exists on node {self.name}")
        intf = Interface(if_name, self)
        self._interfaces[if_name] = intf
        return intf

    def __repr__(self):
        return f"{self.__class__.__name__}({self.image}, {self.name})"

    def __str__(self):
        return f"{self.name}"


@NodeFactory.register_role("PC")
class PC(GenericNode):
    pass


@NodeFactory.register_role("VM")
class VM(GenericNode):
    pass


@NodeFactory.register_role("SWITCH")
class Switch(GenericNode):
    pass


@NodeFactory.register_role("ROUTER")
class Router(GenericNode):
    pass


@NodeFactory.register_role("FW")
class Firewall(GenericNode):
    pass
