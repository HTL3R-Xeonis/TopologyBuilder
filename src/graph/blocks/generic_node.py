from __future__ import annotations

from typing import Any

from src.graph import Environment
from .interface import Interface
from .formatter import nested_formatter

__autor__ = "Leon Eiböck"
__date__ = "17/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


class GenericNode:
    """
    Object which represents a node in a graph.
    Can be connected through interfaces to other nodes.
    """

    def __init__(self, image: str, role: str, name: str):
        """
        :param image: which image to use for this node
        :param role: what does this node represent in the graph
        :param name: which name to use for this node
        """
        self._image: str = image
        self._role: str = role
        self._name: str = name

        self._interfaces: dict[str, Interface] = {}
        self._gns3_node_info: dict[str, Any] | None = None
        self._env: Environment = Environment.get_environment(image)

        if self._env == Environment.ON_NOTHING:
            raise ValueError(f"Image {image} not found on ESXi or GNS3.")

    @property
    def image(self) -> str:
        """
        The image to use for this node.
        :return: Returns this attribute
        """
        return self._image

    @property
    def role(self) -> str:
        """
        The role of this node.
        :return: Returns this attribute
        """
        return self._role

    @property
    def name(self) -> str:
        """
        The name of this node.
        :return: Returns this attribute
        """
        return self._name

    @property
    def interfaces(self) -> dict[str, Interface]:
        """
        The interface of this node.
        :return: Returns this attribute
        """
        return self._interfaces

    @property
    def gns3_node_info(self) -> dict[str, Any] | None:
        """
        The gns3 node info of this node. Will only be set, if a Node on gns3 exists.
        :return: Returns this attribute
        """
        return self._gns3_node_info

    @gns3_node_info.setter
    def gns3_node_info(self, gns3_node_info: dict[str, Any]) -> None:
        """
        Sets the gns3 node info for this node.
        :param gns3_node_info: the gns3 node info which is acquired through the GNS3 API
        :return:
        :raise TypeError: Is thrown when the parameters are of the wrong types.
        """
        if not isinstance(gns3_node_info, dict):
            raise TypeError
        self._gns3_node_info = gns3_node_info

    @property
    def env(self) -> Environment:
        """
        The environment of this node. May only be Environment.ON_GNS3 or Environment.ON_ESXI.
        :return: Returns this attribute
        """
        return self._env

    def get_neighbour(self, interface: Interface | str) -> GenericNode | None:
        """
        Returns the neighbour of this node through given interface.
        :param interface: Interface which is connected to the neighbour. Can also only be the interface name
        :return: Returns the neighbour node or None if no node is connected.

        :raise TypeError: Is thrown when the parameters are of the wrong types.
        :raise ValueError: Is thrown when the given interface name does not exist on this node.
        """
        if isinstance(interface, str):
            intf_obj = self.interfaces.get(interface, None)
            if intf_obj is None:
                raise ValueError(
                    f"Interface {interface} does not exist on node {self.name}"
                )
            return intf_obj.neighbour

        if isinstance(interface, Interface):
            return interface.neighbour
        raise TypeError

    def get_interface(self, neighbour: GenericNode | str) -> Interface | None:
        """
        Determines the interface, on this node, which is connected to given neighbour.
        :param neighbour: Neighbour of this node as a Node object or only the node name.
        :return: Returns the interface if this node has a connection to given neighbour, else None.

        :raise TypeError: Is thrown when the parameters are of the wrong types.
        """
        if isinstance(neighbour, str):
            for intf in self.interfaces.values():
                if getattr(intf.neighbour, "name", None) == neighbour:
                    return intf
            return None

        if isinstance(neighbour, GenericNode):
            for intf in self.interfaces.values():
                if intf.neighbour == neighbour:
                    return intf
            return None
        raise TypeError

    def add_interface(self, if_name: str) -> Interface:
        """
        Adds a new interface to this node.
        :param if_name: Name of the new interface
        :return: Returns the newly added interface.

        :raise TypeError: Is thrown when the parameters are of the wrong types.
        :raise ValueError: Is thrown when an interface already exists with the given name on the node.
        """
        if not isinstance(if_name, str):
            raise TypeError

        if if_name in self.interfaces:
            raise ValueError(f"Interface {if_name} already exists on node {self.name}")

        intf = Interface(if_name, self)
        self.interfaces[if_name] = intf
        return intf

    def __str__(self) -> str:
        """
        Nicely formatted string representation of this object.
        :return: String representing this object.
        """
        return (
            f"{self.__class__.__name__}:\n"
            f"  image: {self.image}\n"
            f"  name: {self.name}\n"
            f"  role: {self.role}\n"
            f"  interfaces: {list(self.interfaces)}\n"
            f"  gns3 info set: {self.gns3_node_info is not None}\n"
            f"  environment: {self.env}"
        )

    def __repr__(self) -> str:
        """
        Compact representation of this object.
        :return: String representing this object.
        """
        return (
            f"{self.__class__.__name__}:\n"
            f"  image: {self.image}\n"
            f"  name: {self.name}\n"
            f"  role: {self.role}\n"
            f"  gns3_node_info: {self.gns3_node_info}\n"
            f"  environment: {self.env}\n"
            f"  interfaces: {nested_formatter('  interfaces: ', list(self.interfaces.values()))}\n"
        )
