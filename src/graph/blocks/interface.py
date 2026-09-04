from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generic_node import GenericNode

from .vlan import VirtualLan
from .formatter import nested_formatter

__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


class Interface:
    """
    Object which represents an interface of a Node,
    which can be connected and disconnected to other nodes as liking.
    """

    def __init__(self, if_name: str, node: GenericNode):
        """
        :param if_name: name of the interface
        :param node: Node which owns this interface
        """
        self._name: str = if_name
        self._parent: GenericNode = node
        self._neighbour: GenericNode | None = None
        self._vlan: VirtualLan | None = None

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

    @vlan.setter
    def vlan(self, vlan: VirtualLan) -> None:
        """
        Sets the VirtualLan for this Interface. Assigned by Graph once the
        full edge set is known, since which VLAN (if any) a direct
        ESXi-to-ESXi link's two interfaces should share can't be decided at
        Interface construction time - neighbours aren't connected yet.
        :param vlan: the VirtualLan to assign
        :return:
        """
        self._vlan = vlan

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
