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
        """

        def wrapper(func):
            if role in cls._registry:
                raise KeyError(
                    f"{role} already defined for {cls._registry[role].__name__}"
                )
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
        """
        if role not in self._registry:
            raise ValueError(f"Role {role} registered")
        node = self._registry[role](image, name)
        return node

    @staticmethod
    def create_edge(intf_1: Interface, intf_2: Interface) -> Edge:
        """
        Creates a new edge between two interfaces
        :param intf_1: to connect to other interface
        :param intf_2: to connect to other interface
        :return: edge with both interfaces connected
        """
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
        """
        self._if_name = if_name
        self._node = node
        self._edge = None

    @property
    def name(self) -> str:
        """
        Returns the name of the interface
        :return:
        """
        return self._if_name

    @property
    def node(self) -> GenericNode:
        """
        Returns the Node which owns this interface
        :return:
        """
        return self._node

    @property
    def edge(self) -> Edge | None:
        """
        Returns the Edge which is connected to this interface
        :return:
        """
        return self._edge

    @edge.setter
    def edge(self, edge: Edge) -> None:
        """
        Sets the Edge which is connected to this interface
        :param edge:
        :return:
        """
        self._edge = edge

    def __repr__(self) -> str:
        """
        Makes object into a string. Can be used in eval()
        :return:
        """
        return f"Interface('{self.name}', {repr(self.node)})"

    def __str__(self) -> str:
        """
        Makes object into a more human-readable string.
        :return:
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
        """
        if interface_1 is interface_2:
            raise ValueError("Cannot create Edge with identical Interfaces")
        self.incidence_1 = interface_1
        self.incidence_2 = interface_2

    def __repr__(self) -> str:
        """
        Makes object into a string. Can be used in eval()
        :return:
        """
        return f"Edge({repr(self.incidence_1)}, {repr(self.incidence_2)})"

    def __str__(self) -> str:
        """
        Makes object into a more human-readable string.
        :return:
        """
        return f"{self.incidence_1.node.name} <--> {self.incidence_2.node.name}"


class GenericNode:
    """
    Node object to save each node in the graph. Is the parent object for other nodes.
    """

    def __init__(self, image: str, name: str):
        """
        Initializes the Node class
        :param image: which image to use for this node
        :param name: which name to use for this node
        """
        self.image = image
        self.name = name
        self._interfaces = {}

    @property
    def interfaces(self):
        return self._interfaces

    def get_neighbour(self, intf) -> GenericNode:
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
        return i.edge.incidence_2.node

    def add_interface(self, if_name: str) -> Interface:
        """
        Adds an interface to the graph. Raises an exception if the interface name already exists
        :param if_name: Name of new Interface
        :return: added Interface
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
        """
        return f"{self.__class__.__name__}('{self.image}', '{self.name}')"

    def __str__(self):
        """
        Makes object into a more human-readable string.
        :return:
        """
        return f"{self.name}"


@NodeFactory.register_role("PC")
class PC(GenericNode):
    """
    Node object which represents the role PC.
    """

    pass


@NodeFactory.register_role("VM")
class VM(GenericNode):
    """
    Node object which represents the role VM.
    """

    pass


@NodeFactory.register_role("SWITCH")
class Switch(GenericNode):
    """
    Node object which represents the role SWITCH.
    """

    pass


@NodeFactory.register_role("ROUTER")
class Router(GenericNode):
    """
    Node object which represents the role ROUTER.
    """

    pass


@NodeFactory.register_role("FW")
class Firewall(GenericNode):
    """
    Node object which represents the role FW.
    """

    pass
