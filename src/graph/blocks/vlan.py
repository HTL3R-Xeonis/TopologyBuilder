from loguru import logger


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

        :raise ValueError: Is thrown when the vlan_id exceeds the limit of 4093. The vlan_id is automatically incremented with the creation of this object.
        """
        self._name: str = f"{node_name}_{interface_name.replace('/', '-')}"

        if VirtualLan._vlan_id >= 4094:
            logger.error(
                msg
                := "VLANs on ESXi exceed the limit of 4094. Reduce the number of interfaces on VMs which will be located on ESXi."
            )
            raise ValueError(msg)

        self._vlan_id: int = VirtualLan._vlan_id
        VirtualLan._vlan_id += 1

    @classmethod
    def reset(cls) -> None:
        """
        Resets the VLAN id counter back to its starting value (2), so a
        freshly built Graph doesn't inherit VLAN numbers left over from a
        previous Graph built earlier in the same process.
        :return:
        """
        cls._vlan_id = 2

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
        Used as the ESXi port group name - vSphere allows long names, so
        no length constraint applies here. For the GNS3 VM's own Linux
        subinterface, use `subinterface_name` instead.
        :return: Returns this attribute
        """
        return self._name

    @property
    def subinterface_name(self) -> str:
        """
        Name for this VLAN's subinterface on the GNS3 VM's own guest OS -
        deliberately distinct from `name` (the ESXi port group name).
        Linux interface names are capped at 15 characters (IFNAMSIZ), so
        `name` (built from node_name + interface_name, unbounded length)
        is not safe to use here - a long node/interface name combination
        makes `ip link add ... name <name>` fail with "not a valid
        ifname". Derived from `id` alone instead, which is always a short
        (2-4093) integer, so this stays short and unique regardless of
        how long the node/interface names are.
        :return: a short, Linux-ifname-safe subinterface name
        """
        return f"vlan{self.id}"

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
