"""
Module which contains multiple classes for creating graph elements
"""

from __future__ import annotations

__license__ = "GNU GPLv3"

import re
import zlib
from enum import Enum
from functools import lru_cache
from typing import Literal, Tuple

from src.logger_adapter import get_logger
from src.connections_handler import APIFunctions

logger = get_logger(__name__)

_LINUX_IFNAME_MAX_LENGTH = 15  # kernel's IFNAMSIZ - 1


def _sanitize_ifname(raw: str, max_length: int = _LINUX_IFNAME_MAX_LENGTH) -> str:
    """
    Sanitizes a string into a name valid for a Linux network interface: only
    alphanumerics, hyphens and underscores, at most `max_length` characters.
    Names that need truncating get a short hash suffix appended, so distinct
    inputs that would otherwise collide after truncation stay unique.
    :param raw: the string to sanitize (e.g. "PC4_gi0/0")
    :param max_length: maximum length of the result
    :return: a valid, unique-enough interface name
    """
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "-", raw)
    if len(sanitized) <= max_length:
        return sanitized

    suffix = format(zlib.crc32(raw.encode()) & 0xFFFF, "04x")
    return f"{sanitized[: max_length - len(suffix) - 1]}-{suffix}"


def normalize_template_name(name: str) -> str:
    """
    Normalizes a template/image name for lenient comparison: case-insensitive,
    with ALL whitespace removed (not just collapsed) - real-world template
    names have been observed to disagree with a topology config's image name
    on whether a space exists at a given position at all, not just how many
    (e.g. "Cisco IOSv 15.6(1)T" vs "Cisco IOSv 15.6(1) T"), so collapsing
    whitespace runs to a single space still wouldn't make those equal.
    :param name: the name to normalize
    :return: normalized name, safe to compare with ==
    """
    return "".join(name.split()).lower()


class Environment(Enum):
    ON_NOTHING = 0
    ON_ESXI = 1
    ON_GNS3 = 2

    @staticmethod
    @lru_cache(maxsize=1)
    def get_templates() -> Tuple[frozenset, frozenset]:
        """
        Returns a tuple Frozen-sets with the available template names on GNS3 and ESXi
        :return: Tupel with two Frozen-sets. First index is for GNS3, second is for ESXi
        """
        gns3_templates = frozenset(APIFunctions.get_gns3_template_names())
        esxi_templates = frozenset(APIFunctions.get_esxi_template_names())
        return gns3_templates, esxi_templates

    @staticmethod
    def get_environment(
        image: str,
    ) -> Literal[Environment.ON_GNS3, Environment.ON_ESXI, Environment.ON_NOTHING]:
        """
        Returns the environment based on the image. Matching ignores case and
        whitespace differences (see normalize_template_name).
        #@TODO add description and tests
        :param image: image to judge the environment on
        :return: Either returns ON_ESXI or ON_GNS3. When the template-name isn't on either then it returns ON_NOTHING
        """
        normalized_image = normalize_template_name(image)
        gns3_templates, esxi_templates = Environment.get_templates()
        if any(normalize_template_name(t) == normalized_image for t in gns3_templates):
            return Environment.ON_GNS3
        if any(normalize_template_name(t) == normalized_image for t in esxi_templates):
            return Environment.ON_ESXI
        return Environment.ON_NOTHING


def compute_esxi_vlan_assignments(nodes: dict[str, GenericNode]) -> dict[str, int]:
    """
    Assigns a sequential VLAN ID (starting at 2) to every interface of every
    ESXi-hosted node in the topology. Deterministic for a given `nodes` dict,
    so independent callers (the GNS3 VM's subinterfaces, the ESXi vSwitch port
    groups) can derive the same VLAN numbering without sharing state.

    An edge directly connecting two ESXi-hosted interfaces (no GNS3 device in
    between) gets both sides assigned the SAME VLAN ID, since there's no
    bridging device to translate between two different VLANs - the two VMs
    only reach each other if their vNICs share a VLAN. Every other interface
    (unconnected, or bridged to a GNS3 node via a Cloud node) keeps its own
    unique VLAN, same as before.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    :return: map of Interface.esxi_vlan name to its assigned VLAN ID
    """
    assignments: dict[str, int] = {}
    vlan_id = 2
    for node in nodes.values():
        if node.env != Environment.ON_ESXI:
            continue
        for interface in node.interfaces.values():
            if interface.esxi_vlan in assignments:
                continue

            edge = interface.edge
            if edge is not None:
                neighbour = (
                    edge.incidence_2
                    if edge.incidence_1 is interface
                    else edge.incidence_1
                )
                if (
                    neighbour.node.env == Environment.ON_ESXI
                    and neighbour.esxi_vlan in assignments
                ):
                    assignments[interface.esxi_vlan] = assignments[neighbour.esxi_vlan]
                    continue

            if vlan_id >= 4094:
                raise logger.alert(
                    ValueError,
                    "VLANs on ESXi exceed the limit of 4094. Reduce the number of interfaces on VMs on ESXi",
                )
            assignments[interface.esxi_vlan] = vlan_id
            vlan_id += 1
    return assignments


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
        self._esxi_vlan = None
        if node.env == Environment.ON_ESXI:
            self._esxi_vlan = _sanitize_ifname(f"{node.name}_{if_name}")

    @property
    def esxi_vlan(self) -> str | None:
        return self._esxi_vlan

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

        @TODO add tests for self.env variable
        """
        self.image = image
        self.name = name
        self._interfaces = {}

        self.env = Environment.get_environment(image)
        if self.env == Environment.ON_NOTHING:
            raise logger.alert(ValueError, f"Image {image} not found on ESXi or GNS3.")

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
