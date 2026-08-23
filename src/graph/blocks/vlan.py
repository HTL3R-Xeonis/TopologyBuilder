class VirtualLan:
    """
    Object with a unique id starting from 2 and ending at 4093.
    This Object is used by the Interface Object to determine which unique name the portgroup on the vSwitch on ESXi will have.
    """

    _vlan_id: int = 2

    def __init__(self, node_name: str, interface_name: str):
        """
        :param node_name: Name of the node to which the given interface_name belongs to.
        :param interface_name: Name of the interface to which this VirtualLan will belong to.

        :raise TypeError: Is thrown when the parameters are of the wrong types.
        :raise ValueError: Is thrown when the vlan_id exceeds the limit of 4093. The vlan_id is automatically incremented with the creation of this object.
        """
        if not isinstance(node_name, str) or not isinstance(interface_name, str):
            raise TypeError

        self._name: str = f"{node_name}_{interface_name.replace('/', '-')}"

        if VirtualLan._vlan_id >= 4094:
            raise ValueError(
                "VLANs on ESXi exceed the limit of 4094. Reduce the number of interfaces on VMs which will be located on ESXi."
            )

        self._vlan_id: int = VirtualLan._vlan_id
        VirtualLan._vlan_id += 1

    @property
    def id(self) -> int:
        """
        A unique id, expected in the range of 2 <= id <= 4093.
        :return: Returns this attribute
        """
        return self._vlan_id

    @property
    def name(self) -> str:
        """
        Name of this vlan object.
        It is the result of the node_name and interface_name attributes passed at the creation of this object.
        :return: Returns this attribute
        """
        return self._name

    def __str__(self) -> str:
        """
        Nicely formatted string representation of this object.
        :return: String representing this object.
        """
        return f"{self.__class__.__name__}:\n  name: {self.name}\n  vlan_id: {self.id}"

    def __repr__(self) -> str:
        """
        Compact representation of this object.
        :return: String representing this object.
        """
        return str(self)
