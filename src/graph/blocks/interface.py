from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generic_node import GenericNode

from src.graph.environment import Environment
from .vlan import VirtualLan
from .formatter import nested_formatter

__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


# @TODO ExceptionHandling
# @TODO Logging
# @TODO Complete and recursive Exception Documentation.
class Interface:
    """
    Object which represents an interface of a Node,
    which can be connected and disconnected to other nodes as liking.
    """

    def __init__(self, if_name: str, node: GenericNode):
        """
        :param if_name: name of the interface
        :param node: Node which owns this interface

        :raises ValueError: Is thrown when too many interfaces are created, which have a vlan object. i <= 4093
        """
        self._name: str = if_name
        self._parent: GenericNode = node
        self._neighbour: GenericNode | None = None
        self._vlan: VirtualLan | None = None

        if node.env == Environment.ON_ESXI:
            self._vlan = VirtualLan(node.name, if_name)

    @property
    def name(self) -> str:
        """
        Name of the interface.
        :return: Returns this attribute
        """
        return self._name

    @property
    def parent(self) -> GenericNode:
        """
        Node which owns this interface.
        :return: Returns this attribute
        """
        return self._parent

    @property
    def vlan(self) -> VirtualLan | None:
        """
        VirtualLan for this Interface.
        Is only not None, when the environment of the parent Node is ON_ESXi,
        since this object will be used for the creation of the portgroups on the vSwtich.
        :return: Returns this attribute
        """
        return self._vlan

    @property
    def neighbour(self) -> GenericNode | None:
        """
        Neighbour Node for this Interface.
        Property to which neighbour node this interface is connected to.
        This can only be a 1-to-1 connection.
        :return: Neighbour Node for this Interface. Is only then None if the interface is not connected to any node.
        """
        return self._neighbour

    def connect_to(self, new_neighbour: GenericNode) -> None:
        """
        Connects this interface to the given neighbour Node.
        :param new_neighbour: Node to which this interface will be connected to.
        :return:
        """
        self._neighbour = new_neighbour

    def __str__(self) -> str:
        """
        Nicely formatted string representation of this object.
        :return: String representing this object.
        """
        return (
            f"{self.__class__.__name__}:\n"
            f"  name: {self.name}\n"
            f"  parent: {self.parent.name}\n"
            f"  neighbour: {getattr(self.neighbour, 'name', None)}\n"
            f"  vlan: {getattr(self.vlan, 'name', None)}"
        )

    def __repr__(self) -> str:
        """
        Compact representation of this object.
        :return: String representing this object.
        """
        return (
            f"{self.__class__.__name__}:\n"
            f"  name: {self.name}\n"
            f"  parent: {self.parent.name}\n"
            f"  neighbour: {getattr(self.neighbour, 'name', None)}\n"
            f"  vlan: {nested_formatter('vlan: ', self.vlan)}"
        )
