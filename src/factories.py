"""
Module which contains multiple classes for creating graph elements
"""

__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


class NodeFactory:
    """
    Class which creates nodes based on node groups
    """

    _registry: dict[str, type] = {}

    @classmethod
    def register_role(cls, role: str):
        """
        Decorator to register a role
        :param role: to be registered
        :return: new Function
        @TODO doctests/unittests
        """

        def wrapper(func):
            cls._registry[role] = func
            return func

        return wrapper

    def create_node(self, image: str, role: str, name: str) -> GenericNode:
        """
        Create a new node based on role.
        :param image: which image to use for this node
        :param role: which role to use for this node
        :param name: which name to use for this node
        :return: new Node
        @TODO doctests/unittests
        """
        node = self._registry[role](image, name)
        return node


class EdgeFactory:
    """
    Class which connects the nodes based on given edge groups
    """

    @staticmethod
    def create_edge(edge_group: list, nodes: dict[str, GenericNode]) -> Edge:
        """
        Adds new Interfaces to both nodes and connects them via a new edge
        :param edge_group: list with two Nodes and two Interfaces
        :param nodes: Dictionary of Nodes to resolve name of nodes
        :return:
        @TODO doctests/unittests
        """
        intf_1 = nodes[edge_group[0]].add_interface(edge_group[1])
        intf_2 = nodes[edge_group[2]].add_interface(edge_group[3])
        edge = Edge(intf_1, intf_2)
        intf_1.edge = edge
        intf_2.edge = edge
        return edge


class Interface:
    """
    Object which is used to connect Nodes and Edges
    """

    def __init__(self, if_name: str, node: GenericNode):
        """
        Initializes the Interface class
        :param if_name: name of the interface
        :param node: Node which owns this interface
        @TODO doctests/unittests
        """
        self._if_name = if_name
        self._node = node

    @property
    def name(self) -> str:
        """
        Returns the name of the interface
        :return:
        @TODO doctests/unittests
        """
        return self._if_name

    @property
    def node(self) -> GenericNode:
        """
        Returns the Node which owns this interface
        :return:
        @TODO doctests/unittests
        """
        return self._node

    @property
    def edge(self):
        """
        Returns the Edge which is connected to this interface
        :return:
        @TODO doctests/unittests
        """
        return getattr(self, "_edge", None)

    @edge.setter
    def edge(self, edge: Edge) -> None:
        """
        Sets the Edge which is connected to this interface
        :param edge:
        :return:
        @TODO doctests/unittests
        """
        self._edge = edge

    def __repr__(self) -> str:
        """
        Makes object into a string. Can be used in eval()
        :return:
        @TODO doctests/unittests
        """
        return f"Interface({self.name}, {self.node.name})"

    def __str__(self) -> str:
        """
        Makes object into a more human-readable string.
        :return:
        @TODO doctests/unittests
        """
        return f"{self.name}"


class Edge:
    """
    Object which is used to connect interfaces of nodes
    """

    incidence_1 = None
    incidence_2 = None

    def __init__(self, interface_1: Interface, interface_2: Interface):
        """
        Initializes the Edge class
        :param interface_1: to be connected to other interface
        :param interface_2:  to be connected to other interface
        @TODO doctests/unittests
        """
        self.incidence_1 = interface_1
        self.incidence_2 = interface_2

    def __repr__(self) -> str:
        """
        Makes object into a string. Can be used in eval()
        :return:
        @TODO doctests/unittests
        """
        return f"Edge({repr(self.incidence_1)}, {repr(self.incidence_2)})"

    def __str__(self) -> str:
        """
        Makes object into a more human-readable string.
        :return:
        @TODO doctests/unittests
        """
        return f"{self.incidence_1.node} <--> {self.incidence_2.node}"


class GenericNode:
    """
    Node object to save each node in the graph. Is the parent object for other nodes.
    """

    def __init__(self, image: str, name: str):
        """
        Initializes the Node class
        :param image: which image to use for this node
        :param name: which name to use for this node
        @TODO doctests/unittests
        """
        self.image = image
        self.name = name
        self._interfaces = {}

    @property
    def interfaces(self):
        return self._interfaces

    def get_neighbour(self, intf):
        """
        Finds the node which is connected to given interface
        :param intf: connection to look for neighbour
        :return: Node object
        """
        if intf not in self._interfaces:
            raise ValueError(f"Interface {intf} does not exist on node {self.name}")
        i: Interface = self._interfaces[intf]

        if i.edge is None:
            raise ValueError(f"Edge on {i} does not exist on node {self.name}")
        if i.edge.incidence_1 is None or i.edge.incidence_2 is None:
            raise ValueError(f"Edge is partially connected {self.name}/{i}")

        if not i == i.edge.incidence_1:
            return i.edge.incidence_1.node
        if not i == i.edge.incidence_2:
            return i.edge.incidence_2.node

    def add_interface(self, if_name: str) -> Interface:
        """
        Adds an interface to the graph. Raises an exception if the interface name already exists
        :param if_name: Name of new Interface
        :return: added Interface
        @TODO doctests/unittests
        """
        if if_name in self._interfaces:
            raise ValueError(f"Interface {if_name} already exists on node {self.name}")
        intf = Interface(if_name, self)
        self._interfaces[if_name] = intf
        return intf

    def __repr__(self):
        """
        Makes object into a string. Can be used in eval()
        :return:
        @TODO doctests/unittests
        """
        return f"{self.__class__.__name__}({self.image}, {self.name})"

    def __str__(self):
        """
        Makes object into a more human-readable string.
        :return:
        @TODO doctests/unittests
        """
        return f"{self.name}"


@NodeFactory.register_role("PC")
class PC(GenericNode):
    """
    Node object which represents the role PC.
    @TODO doctests/unittests
    """

    pass


@NodeFactory.register_role("VM")
class VM(GenericNode):
    """
    Node object which represents the role VM.
    @TODO doctests/unittests
    """

    pass


@NodeFactory.register_role("SWITCH")
class Switch(GenericNode):
    """
    Node object which represents the role SWITCH.
    @TODO doctests/unittests
    """

    pass


@NodeFactory.register_role("ROUTER")
class Router(GenericNode):
    """
    Node object which represents the role ROUTER.
    @TODO doctests/unittests
    """

    pass


@NodeFactory.register_role("FW")
class Firewall(GenericNode):
    """
    Node object which represents the role FW.
    @TODO doctests/unittests
    """

    pass
