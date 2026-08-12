"""
Provides classes for connection types like SSH or the API connections to GNS3 and ESXi.
These classes have methods which can be used to operate these APIs.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import atexit
import ipaddress
from abc import ABC, abstractmethod
from typing import Optional, Any, List
from src.logger_adapter import get_logger

import paramiko
import ssl

import pyVmomi
import requests
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from pyVmomi.VmomiSupport import ManagedObject
from src.settings import Settings

logger = get_logger()


class APIFunctions:
    """
    Provides various methods for API calls.
    """

    @staticmethod
    def _send_get_request(url: str) -> dict[str, Any] | str:
        """
        General method to make an API GET request
        :param url: API url
        :return:
        """
        response = requests.get(url)
        response.raise_for_status()
        try:
            return response.json()
        except not ValueError:
            return response.text

    @staticmethod
    def get_esxi_template_names():
        """
        Returns a set of available template names for ESXi
        :return:
        """
        if Settings.Testing.GithubWorkflow.LITERAL_API_VALUES:
            return Settings.Testing.GithubWorkflow.LITERAL_ESXI_TEMPLATES
        json = APIFunctions._send_get_request("http://10.20.20.171:8000/api/templates")
        return {template["name"] for template in json["templates"]}

    @staticmethod
    def get_gns3_template_names():
        """
        Returns a set of available template names for GNS3
        :return:
        """
        if Settings.Testing.GithubWorkflow.LITERAL_API_VALUES:
            return Settings.Testing.GithubWorkflow.LITERAL_GNS3_TEMPLATES
        json = APIFunctions._send_get_request("http://10.20.20.171:8001/api/templates")
        return {template["name"] for template in json["templates"]}


class GenericConnection(ABC):
    def __init__(self, ip_address: str, username: str, password: str | None) -> None:
        """
        :param ip_address: IP address of the instance
        :param username: Hosts username
        :param password: corresponding password for user
        @TODO create pytest
        """
        ipaddress.ip_address(ip_address)

        self._ip_address = ip_address
        self._username = username
        self._password = password

        self._connection = self.connect()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    @property
    def ip_address(self) -> str:
        return self._ip_address

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str | None:
        return self._password

    @property
    def connection(self):
        return self._connection

    @abstractmethod
    def connect(self) -> None:
        pass


class SSHConnection(GenericConnection, paramiko.SSHClient):
    def connect(self) -> paramiko.SSHClient:
        """
        Connect to an SSH server.
        :return: Returns the client
        @TODO create pytest
        """
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=self.ip_address,
            port=22,
            username=self.username,
            password=self.password,
            timeout=10,
        )

        return client


class GNS3Connection(GenericConnection):
    def connect(self):
        pass


class ESXiConnection(GenericConnection):
    def __init__(self, ip_address: str, username: str, password: str | None):
        super().__init__(ip_address, username, password)

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
