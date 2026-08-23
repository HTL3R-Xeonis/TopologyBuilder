import atexit
import ipaddress
import ssl
from typing import Optional, List, TypeVar

import pyVmomi
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

from src.connections.api_handler import APIHandler
from src.connections.generic_connection import GenericConnection
from src.graph import Graph
from src.graph.blocks import VirtualLan
from src.logger_adapter import get_logger
from src.settings import Settings

logger = get_logger()
T = TypeVar("T")


# @TODO ExceptionHandling
# @TODO Complete and recursive Exception Documentation.
class ESXiConnection(GenericConnection):
    """
    Object which manages the communication between APIs regarding ESXi.
    """

    def __init__(self, ip: str, username: str, password: str | None):
        """
        :param ip: IP address of the ESXi host.
        :param username: ESXi username.
        :param password: ESXi password. Set to ``None`` if no password is set.
        :raises RuntimeError: Is thrown when no ViewManager is available on this ServiceInstance.
        """
        super().__init__(ip, 443, username, password)

        self.content: vim.ServiceInstanceContent = self.connection.RetrieveContent()

        view_manager = self.content.viewManager
        if view_manager is None:
            raise RuntimeError("vSphere ViewManager is not available.")
        self.view_manager = view_manager

    def connect(self) -> vim.ServiceInstance:
        """
        Connect to the ESXi API.
        :return: Returns the client
        """
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        instance = SmartConnect(
            host=self.ip,
            user=self.username,
            pwd=self.password,
            port=443,
            sslContext=ssl_context,
        )

        atexit.register(Disconnect, instance)
        return instance

    def _get_object_by_name(self, vim_type: type[T], name: str = None) -> T | None:
        """
        Finds the object on the ServiceInstance by type and name.
        :param vim_type: Specifies the type of the object to look for. Should be a type of the pyVmomi library.
        :param name: Name of the object to look for. If this is set to None, the first object will be returned.
        :return: Returns the pyVmomi object or None.
        """
        view = self.view_manager.CreateContainerView(
            self.content.rootFolder, [vim_type], True
        )

        try:
            for obj in view.view:
                if name is None:
                    return obj
                if obj.name == name:
                    return obj
            return None
        finally:
            view.Destroy()

    def get_vm(self, vm_name: str) -> vim.ManagedEntity | None:
        """
        Searches for a VM with given name.
        :param vm_name: Name of VM to look for.
        :return: Returns Virtual Machine if found, else None.
        """
        return self._get_object_by_name(vim.VirtualMachine, vm_name)

    def get_vm_ip_address(self, vm_name: str) -> Optional[str]:
        """
        Returns the first IPv4 Address it finds on the VM with given name.
        Ignores loopback, link locals and multicast addresses.
        :param vm_name: Name of VM to look on.
        :return: Returns a IPv4 address if a valid one was found, else None
        """
        vm = self.get_vm(vm_name)
        for nic in [] if vm is None else vm.guest.net:
            for address in nic.ipAddress or []:
                try:
                    parsed = ipaddress.ip_address(address)
                except ValueError:
                    continue

                if parsed.version != 4:
                    continue

                if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast:
                    continue
                return address
        return None

    def _get_virtual_switch(self) -> vim.host.VirtualSwitch:
        """
        Looks for a virtual Switch with the name, specified in ``Settings.Esxi.VIRTUAL_SWITCH``, on the ESXi Host.
        :return: Returns the virtual Switch if found.
        :raises ValueError: Is thrown when no fitting virtual Switch was found.
        """
        host = self._get_object_by_name(vim.HostSystem)
        config = getattr(host, "config", vim.host.ConfigInfo)
        vswitch = getattr(config.network, "vswitch", [])

        for vswitch in vswitch:
            if vswitch.name == Settings.Esxi.VIRTUAL_SWITCH:
                return vswitch

        raise logger.alert(
            ValueError, f"virtual switch {Settings.Esxi.VIRTUAL_SWITCH} not found."
        )

    def _add_port_group(self, vlan: VirtualLan) -> None:
        """
        Creates a port groups on the virtual switch based on the given ``vlan``.
        The policies are inherited from the virtual Switch on ESXi.
        :param vlan: VLAN Object of the ``graph.blocks.Interface`` to create the port group
        :return:
        :raises RuntimeError: Is thrown when no host-system or network-system was found on the ESXi host.
        """
        spec = vim.host.PortGroup.Specification()
        spec.name = vlan.name
        spec.vswitchName = Settings.Esxi.VIRTUAL_SWITCH
        spec.vlanId = vlan.id
        spec.policy = vim.host.NetworkPolicy()

        host_system = self._get_object_by_name(vim.HostSystem)
        if host_system is None:
            raise RuntimeError("No host system found on ESXi.")

        network_system = host_system.configManager.networkSystem
        if network_system is None:
            raise RuntimeError("No network system found on ESXi.")
        try:
            network_system.AddPortGroup(spec)

        except vim.fault.AlreadyExists:
            raise RuntimeError(f"Port group {vlan.name} already exists on ESXi.")

    def _get_port_groups(self) -> List[pyVmomi.vim.host.PortGroup]:
        """
        Returns a list of all port groups connected to the virtual switch.
        :return: A list of port groups or empty list.
        :raises ValueError: Is thrown when no virtual Switch was found.
        """
        virtual_switch = self._get_virtual_switch()
        host = self._get_object_by_name(vim.HostSystem)

        return [
            port_group
            for port_group in host.config.network.portgroup
            if port_group.key in virtual_switch.portgroup
        ]

    def _remove_port_group(self, port_group_name: str) -> None:
        """
        Removes the port group, on the virtual switch.
        :param port_group_name: Name of the port group.
        :return:
        """
        host = self._get_object_by_name(vim.HostSystem)
        network = host.configManager.networkSystem
        network.RemovePortGroup(pgName=port_group_name)

    def _remove_port_groups(self) -> None:
        """
        Deletes all port groups from the virtual switch, except for those specified in ``Settings.Esxi.IGNORE_PORT_GROUPS``.
        :return:
        """
        port_groups = self._get_port_groups()
        for pg in port_groups:
            if pg.spec.name in Settings.Esxi.IGNORE_PORT_GROUPS | {"PG_GNS3_TRUNK"}:
                continue
            self._remove_port_group(pg.spec.name)

    def reset_virtual_switch(self) -> None:
        """
        Removes the necessary assets from the virtual switch to reduce the number of problems which could occur.
        :return:
        """
        self._remove_port_groups()

    def initialize_virtual_switch(self, graph: Graph) -> None:
        """
        Creates the needed port groups on the virtual switch.
        :param graph: Port groups are based of the VLANs on each ``Interface`` of each ``Node`` in given ``graph``.
        :return:
        """
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None:
                    continue
                self._add_port_group(vlan)

    def deploy_virtual_machine(
        self, vm_name: str, datastore: str, ova_filename: str, mapped_network: dict
    ) -> None:
        """
        Deploys the virtual machine on the ESXi host.
        :param vm_name: Name of the virtual machine.
        :param datastore: Name of the datastore, to store the virtual machine on.
        :param ova_filename: OVA-Filename to use for this deployment.
        :param mapped_network: Network mapping of interface names to port group names.
        :return:
        """
        APIHandler.post(
            url="http://10.20.20.172:8003/deploy/ova",
            json={
                "ip": self.ip,
                "port": self.port,
                "vm_name": vm_name,
                "ova_filename": ova_filename,
                "datastore": datastore,
                "network": mapped_network,
            },
        )
