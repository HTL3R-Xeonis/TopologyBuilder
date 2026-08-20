from typing import Optional, List

from src.connection_handler.generic_connection import GenericConnection

import pyVmomi
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from pyVmomi.VmomiSupport import ManagedObject
import atexit
import ssl
import ipaddress

from src.connection_handler.api_handler import APIHandler
from src.settings import Settings

from src.logger_adapter import get_logger

logger = get_logger()


class ESXiConnection(GenericConnection):
    def __init__(self, ip_address: str, username: str, password: str | None):
        super().__init__(ip_address, 443, username, password)

        self.content: vim.ServiceInstanceContent = self.connection.RetrieveContent()

        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder,
            [vim.HostSystem],
            True,
        )
        self.view = container_view.view
        container_view.Destroy()

    def connect(self) -> vim.ServiceInstance:
        """
        Connect to the ESXi API.
        :return: Returns the client
        @TODO create pytest
        """
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        instance = SmartConnect(
            host=self.ip_address,
            user=self.username,
            pwd=self.password,
            port=443,
            sslContext=ssl_context,
        )

        atexit.register(Disconnect, instance)
        return instance

    def get_vm(self, vm_name: str) -> Optional[ManagedObject]:
        """
        Searches for a VM with given name.
        :param vm_name: Name of VM to look for
        :return: Returns Virtual Machine if found, else None
        @TODO create pytest
        """
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )

        try:
            for vm in container_view.view:
                if vm.name == vm_name:
                    return vm
        finally:
            container_view.Destroy()

        return None

    def get_vm_ip_address(self, vm_name: str) -> Optional[str]:
        """
        Returns the first IPv4 Address it finds on the VM with given name.
        Ignores loopback, link locals and multicast addresses.
        :param vm_name: Name of VM to look on
        :return: IPv4 Address if found, else None.
        @TODO create pytest
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

    def get_virtual_switch(self) -> vim.host.VirtualSwitch:
        """
        Looks for the virtual Switch, specified in Settings.Esxi.VIRTUAL_SWITCH, on the ESXi Host.
        :return: The virtual Switch will be returned.
        :raises: If no virtual Switch with the corresponding name was found, a ValueError will be raised.
        """
        host: ManagedObject = self.view[0]

        network: pyVmomi.vim.host.NetworkSystem = host.configManager.networkSystem
        vswitch_list = network.networkInfo.vswitch

        for vswitch in vswitch_list:
            if vswitch.name == Settings.Esxi.VIRTUAL_SWITCH:
                return vswitch

        raise logger.alert(ValueError, f"vSwitch {vswitch} not found.")

    def get_port_groups(self) -> List[pyVmomi.vim.host.PortGroup]:
        """
        Collects all ports from the virtual Switch specified in Settings.Esxi.VIRTUAL_SWITCH.
        :return: Returns the collected port groups in a list
        """
        host: ManagedObject = self.view[0]
        network: pyVmomi.vim.host.NetworkSystem = host.configManager.networkSystem

        return [
            pg
            for pg in network.networkInfo.portgroup
            if pg.spec.vswitchName == Settings.Esxi.VIRTUAL_SWITCH
        ]

    def remove_port_group(self, port_group: str) -> None:
        """
        Removes the given port group on the virtual Switch, specified in Settings.Esxi.VIRTUAL_SWITCH.
        :param port_group: Name of the port group to remove
        :return:
        """
        host = self.view[0]
        network: pyVmomi.vim.host.NetworkSystem = host.configManager.networkSystem

        network.RemovePortGroup(pgName=port_group)

    def add_port_group(self, port_group: str, vlan_id: int) -> None:
        """
        Adds the given port group with the given VLAN ID to the virtual Switch, specified in Settings.Esxi.VIRTUAL_SWITCH.
        The policies are inherited from the virtual Switch.
        :param port_group: Name of the port group to add
        :param vlan_id: VLAN ID of the port group
        :return:
        """
        host = self.view[0]

        spec = vim.host.PortGroup.Specification()
        spec.name = port_group
        spec.vswitchName = Settings.Esxi.VIRTUAL_SWITCH
        spec.vlanId = vlan_id
        spec.policy = vim.host.NetworkPolicy()

        host.configManager.networkSystem.AddPortGroup(spec)

    def initialize_vswitch(self, mapped_vlans: dict[str, int]) -> None:
        for name, vlan_id in mapped_vlans.items():
            self.add_port_group(name, vlan_id)

    def reset(self) -> None:
        """
        Resets the ESXi host, so that the VM orchestration has no problems with setting the vSwitch and the other VMs up.
        :return:
        @TODO create pytest
        """
        self._remove_port_groups()

    def _remove_port_groups(self) -> None:
        """
        Removes all the port groups from the vSwitch, specified in Settings.Esxi.VIRTUAL_SWITCH,
        except for the port groups which are specified in Settings.Esxi.IGNORE_PORT_GROUPS.
        :return:
        @TODO create pytest
        """
        port_groups = self.get_port_groups()
        for pg in port_groups:
            if pg.spec.name in Settings.Esxi.IGNORE_PORT_GROUPS | {"PG_GNS3_TRUNK"}:
                continue
            self.remove_port_group(pg.spec.name)

    def deploy_vm(
        self, vm_name: str, datastore: str, ova_filename: str, mapped_network: dict
    ):
        APIHandler.post(
            url="http://10.20.20.172:8003/deploy/ova",
            json={
                "ip": self.ip_address,
                "port": self.port,
                "vm_name": vm_name,
                "ova_filename": ova_filename,
                "datastore": datastore,
                "network": mapped_network,
            },
        )
