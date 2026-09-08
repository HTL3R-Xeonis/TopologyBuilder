import atexit
import ssl
from typing import Optional, TypeVar

import pyVmomi
from loguru import logger
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

from src.settings import Settings, Verbosity
from .generic_connection import GenericConnection

T = TypeVar("T")


# @TODO upgrade resetting vSwitch
class ESXiConnection(GenericConnection):
    """
    Object which manages the communication between APIs regarding ESXi.
    """

    def __init__(self, ip: str, port: int, username: str, password: str | None):
        """
        :param ip: IP address of the ESXi host.
        :param port: Port number of the ESXi host, where the API requests are expected.
        :param username: ESXi username.
        :param password: ESXi password. Set to ``None`` if no password is set.
        :raises RuntimeError: Is thrown when no ViewManager is available on the ESXi host.
        :raises ValueError: Is thrown when invalid credentials are provided or the IPv4 address is not a public, private or loopback address.
        :raises TimeoutError: Is thrown when timeout occurs.
        :raises ConnectionError: Is thrown when the connection buildup fails.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        """
        if password is None:
            password = ""
        super().__init__(ip, port, username, password)

        self.content: vim.ServiceInstanceContent = self.connection.RetrieveContent()

        view_manager = self.content.viewManager
        if view_manager is None:
            raise RuntimeError("vSphere ViewManager is not available.")
        self.view_manager = view_manager

    def connect(self) -> vim.ServiceInstance:
        """
        Connect to the ESXi API.
        :return: Returns the client
        :raises ValueError: Is thrown when invalid credentials are provided.
        :raises TimeoutError: Is thrown when timeout occurs.
        :raises ConnectionError: Is thrown when the connection buildup fails.
        """
        try:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            instance = SmartConnect(
                host=self.ip,
                user=self.username,
                pwd=self.password,
                port=self.port,
                sslContext=ssl_context,
            )

            atexit.register(Disconnect, instance)
        except vim.fault.InvalidLogin as exc:
            logger.error(
                msg
                := "Invalid ESXi credentials. If more than 5 invalid attempts were made, the user enters in a lockout-state."
            )
            raise ValueError(msg) from exc
        except TimeoutError as err:
            logger.error(msg := "Connection timed out. Try again later.")
            raise TimeoutError(msg) from err
        except Exception as exc:
            logger.error(msg := f"Could not connect to ESXi host: {self.ip}.")
            raise ConnectionError(msg) from exc
        return instance

    def get_object_by_name(
        self, vim_type: type[T], name: str = None, get_all: bool = False
    ) -> T | None | list[T]:
        """
        Finds the object on the ServiceInstance by type and name.
        :param vim_type: Specifies the type of the object to look for. Should be a type of the pyVmomi library.
        :param name: Name of the object to look for. If this is set to None, the first object will be returned.
        :param get_all: Whether to return all objects found or not.
        :return: Returns the pyVmomi object or None.
        :raises RuntimeError: Is thrown when no ContainerView can be created.
        """
        try:
            view = self.view_manager.CreateContainerView(
                self.content.rootFolder, [vim_type], True
            )
        except vmodl.RuntimeFault as fault:
            logger.error(msg := "Failed to create container view.")
            raise RuntimeError(msg) from fault

        try:
            if get_all:
                return view.view
            for obj in view.view:
                if name is None:
                    return obj
                if obj.name == name:
                    return obj
            return None
        finally:
            view.Destroy()

    def get_virtual_switch(
        self, virtual_switch_name: str
    ) -> vim.host.VirtualSwitch | None:
        """
        Looks for a virtual Switch with the name, specified in ``Settings.Esxi.VIRTUAL_SWITCH``, on the ESXi Host.
        :param virtual_switch_name: Name of the virtual switch to look for.
        :return: Returns the virtual Switch if found, else ``None``.
        """
        host = self.get_object_by_name(vim.HostSystem)
        config = getattr(host, "config", vim.host.ConfigInfo)
        vswitch = getattr(config.network, "vswitch", [])

        for vswitch in vswitch:
            if (
                isinstance(vswitch, vim.host.VirtualSwitch)
                and vswitch.name == virtual_switch_name
            ):
                return vswitch
        return None

    def create_virtual_switch(self, virtual_switch_name: str) -> vim.host.VirtualSwitch:
        """
        Creates a new virtual switch on the ESXi Host.
        :param virtual_switch_name: Name of the virtual switch to create.
        :return:
        :raises RuntimeError: Is thrown when the virtual switch already exists on the ESXi host. May also be thrown when no host-system or network-system was found.
        :raises ValueError: Is thrown when the name length of the vswitch exceeds the character limit of 32.
        """
        host = self.get_object_by_name(vim.HostSystem)
        if host is None:
            logger.error(msg := f"Hostsystem not found on ESXi host: {self.ip}")
            raise RuntimeError(msg)

        network_system = host.configManager.networkSystem
        if network_system is None:
            logger.error(msg := f"NetworkSystem not found on ESXi host: {self.ip}")
            raise RuntimeError(msg)

        if len(virtual_switch_name) > 32:
            logger.error(
                msg
                := f"Virtual Switch name is limited to 32 characters. ({len(virtual_switch_name)} characters)"
            )
            raise ValueError(msg)
        try:
            network_system.AddVirtualSwitch(vswitchName=virtual_switch_name, spec=None)
        except vim.fault.AlreadyExists:
            logger.error(
                msg := f"Virtual Switch already exists on ESXi host: {self.ip}"
            )
            raise RuntimeError(msg)

        vswitch = self.get_virtual_switch(virtual_switch_name)
        if vswitch is None:
            logger.error(
                msg
                := f"Created Virtual switch not found on ESXi host: {self.ip} - vswitch name: {virtual_switch_name}"
            )
            raise RuntimeError(msg)
        return vswitch

    def add_port_group(self, pg_name: str, pg_id: int) -> None:
        """
        Creates a port groups on the virtual switch based on the given ``vlan``.
        The policies are inherited from the virtual Switch on ESXi.
        :param pg_name: Name of the port group.
        :param pg_id: ID of the port group.
        :return:
        :raises RuntimeError: Is thrown when a portgroup already exists  on the ESXi host.
        May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        if pg_name in Settings.ESXI.IGNORE_PORT_GROUPS:
            return
        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Would add portgroup {pg_name}"
            )
            return
        Verbosity.volumatic_print(Verbosity.NORMAL, f"Adds portgroup {pg_name}")
        # ----------------------------------------------------------------------------------------------------------

        spec = vim.host.PortGroup.Specification()
        spec.name = pg_name
        spec.vswitchName = Settings.ESXI.VIRTUAL_SWITCH
        spec.vlanId = pg_id
        spec.policy = vim.host.NetworkPolicy()

        host_system = self.get_object_by_name(vim.HostSystem)
        if host_system is None:
            logger.error(msg := "No host system found on ESXi.")
            raise RuntimeError(msg)
        network_system = host_system.configManager.networkSystem
        if network_system is None:
            logger.error(msg := "No network system found on ESXi.")
            raise RuntimeError(msg)

        try:
            network_system.AddPortGroup(spec)
        except vim.fault.AlreadyExists as exc:
            logger.error(msg := f"Port group {pg_name} already exists on ESXi.")
            raise RuntimeError(msg) from exc
        except Exception as exc:
            logger.error(
                msg := f"Something went wrong while adding port group {pg_name}."
            )
            raise RuntimeError(msg) from exc

    def get_all_port_groups(self) -> dict[str, pyVmomi.vim.host.PortGroup]:
        """
        Returns a list of all port groups on the ESXi host.
        :return: A list of port groups.
        """
        host = self.get_object_by_name(vim.HostSystem)

        return {
            port_group.spec.name: port_group
            for port_group in host.config.network.portgroup
        }

    def _get_vswitch_port_groups(
        self, virtual_switch: vim.host.VirtualSwitch
    ) -> dict[str, pyVmomi.vim.host.PortGroup]:
        """
        Returns a list of all port groups connected to the virtual switch.
        :return: A list of port groups or empty list.
        """
        if Settings.IS_DRY_RUN and virtual_switch is None:
            # ----------------------------------------------------------------------------------------------------------
            if Settings.IS_DRY_RUN:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL,
                    f"Would create virtual switch: {Settings.ESXI.VIRTUAL_SWITCH}",
                )
                return {}
            # ----------------------------------------------------------------------------------------------------------
            return {}
        if virtual_switch is None:
            # ----------------------------------------------------------------------------------------------------------
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"Creates virtual switch: {Settings.ESXI.VIRTUAL_SWITCH}",
            )
            # ----------------------------------------------------------------------------------------------------------

        self._ensure_virtual_switch_policy(virtual_switch)
        host = self.get_object_by_name(vim.HostSystem)

        return {
            port_group.spec.name: port_group
            for port_group in host.config.network.portgroup
            if port_group.key in virtual_switch.portgroup
        }

    def remove_port_group(self, port_group_name: str) -> None:
        """
        Removes the port group, on the virtual switch.
        :param port_group_name: Name of the port group.
        :return:
        :raises RuntimeError: Is thrown when the portgroup does not exist, is currently in use or some other Exception occurs.
        """
        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Would remove portgroup {port_group_name}"
            )
            return
        Verbosity.volumatic_print(
            Verbosity.NORMAL, f"Removes portgroup {port_group_name}"
        )
        # ----------------------------------------------------------------------------------------------------------

        host = self.get_object_by_name(vim.HostSystem)
        network = host.configManager.networkSystem
        try:
            network.RemovePortGroup(pgName=port_group_name)
        except vim.fault.NotFound as fault:
            logger.error(
                msg := f"Port group {port_group_name} not found on host: {self.ip}"
            )
            raise RuntimeError(msg) from fault
        except vim.fault.ResourceInUse as fault:
            logger.error(msg := f"Port group is currently in use on host: {self.ip}")
            raise RuntimeError(msg) from fault
        except Exception as exc:
            logger.error(
                msg
                := f"Something went wrong while removing port group {port_group_name} on host: {self.ip}"
            )
            raise RuntimeError(msg) from exc

    def get_vm(self, vm_name: str) -> vim.VirtualMachine | None:
        """
        Searches for a VM with given name.
        :param vm_name: Name of VM to look for.
        :return: Returns Virtual Machine if found, else None.
        """
        return self.get_object_by_name(vim.VirtualMachine, vm_name)

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
                if self.is_valid_ipv4_address(address):
                    return address
        return None
