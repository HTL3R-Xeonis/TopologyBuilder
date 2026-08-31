from __future__ import annotations

import atexit
import ssl
from typing import Optional, List, TypeVar
from typing import TYPE_CHECKING

import pyVmomi
from loguru import logger
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

from .api_handler import APIHandler
from .generic_connection import GenericConnection

if TYPE_CHECKING:
    from src.graph import Graph
    from src.graph.blocks import VirtualLan, GenericNode

from src.settings import Settings, Verbosity


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

    def _get_object_by_name(self, vim_type: type[T], name: str = None) -> T | None:
        """
        Finds the object on the ServiceInstance by type and name.
        :param vim_type: Specifies the type of the object to look for. Should be a type of the pyVmomi library.
        :param name: Name of the object to look for. If this is set to None, the first object will be returned.
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
                if self.is_valid_ipv4_address(address):
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
            if vswitch.name == Settings.ESXI.VIRTUAL_SWITCH:
                return vswitch

        logger.error(
            msg
            := f"virtual switch {Settings.ESXI.VIRTUAL_SWITCH} not found on host: {self.ip}"
        )
        raise ValueError(msg)

    def _add_port_group(self, vlan: VirtualLan) -> None:
        """
        Creates a port groups on the virtual switch based on the given ``vlan``.
        The policies are inherited from the virtual Switch on ESXi.
        :param vlan: VLAN Object of the ``graph.blocks.Interface`` to create the port group
        :return:
        :raises RuntimeError: Is thrown when a portgroup already exists  on the ESXi host.
        May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        if Settings.ONLY_ON_GNS3:
            return
        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Would add portgroup {vlan.name}"
            )
            return
        Verbosity.volumatic_print(Verbosity.NORMAL, f"Adds portgroup {vlan.name}")
        # ----------------------------------------------------------------------------------------------------------

        spec = vim.host.PortGroup.Specification()
        spec.name = vlan.name
        spec.vswitchName = Settings.ESXI.VIRTUAL_SWITCH
        spec.vlanId = vlan.id
        spec.policy = vim.host.NetworkPolicy()

        host_system = self._get_object_by_name(vim.HostSystem)
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
            logger.error(msg := f"Port group {vlan.name} already exists on ESXi.")
            raise RuntimeError(msg) from exc
        except Exception as exc:
            logger.error(
                msg := f"Something went wrong while adding port group {vlan.name}."
            )
            raise RuntimeError(msg) from exc

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
        :raises RuntimeError: Is thrown when the portgroup does not exist, is currently in use or some other Exception occurs.
        """
        if Settings.ONLY_ON_GNS3:
            return
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

        host = self._get_object_by_name(vim.HostSystem)
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

    def _remove_port_groups(self) -> None:
        """
        Deletes all port groups from the virtual switch, except for those specified in ``Settings.Esxi.IGNORE_PORT_GROUPS``.
        :return:
        :raises ValueError: Is thrown when no virtual Switch was found.
        :raises RuntimeError: Is thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
        """
        port_groups = self._get_port_groups()
        for pg in port_groups:
            if pg.spec.name in Settings.ESXI.IGNORE_PORT_GROUPS | {"PG_GNS3_TRUNK"}:
                continue
            self._remove_port_group(pg.spec.name)

    # @TODO upgrade resetting vSwitch
    def reset_virtual_switch(self) -> None:
        """
        Removes the necessary assets from the virtual switch to reduce the number of problems which could occur.
        :return:
        :raises ValueError: Is thrown when no virtual Switch was found.
        :raises RuntimeError: Is thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
        """
        self._remove_port_groups()

    def initialize_virtual_switch(self, graph: Graph) -> None:
        """
        Creates the needed port groups on the virtual switch, then ensures
        the trunk port group (``Settings.ESXI.TRUNK_PORT_GROUP``) accepts
        promiscuous mode/MAC changes/forged transmits - required for GNS3's
        Cloud nodes to bridge in topology devices' own MACs through it.
        ESXi's default security policy silently drops that traffic
        otherwise, with no error on either side.
        :param graph: Port groups are based of the VLANs on each ``Interface`` of each ``Node`` in given ``graph``.
        :return:
        :raises RuntimeError: Is thrown when a portgroup already exists  on the ESXi host.
        May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None:
                    continue
                self._add_port_group(vlan)

        self.ensure_bridging_security_policy(Settings.ESXI.TRUNK_PORT_GROUP)

    def ensure_bridging_security_policy(self, port_group_name: str) -> None:
        """
        Ensures an existing port group accepts promiscuous mode, MAC address
        changes, and forged transmits - required for a port group whose VM
        relays traffic for MAC addresses other than its own vNIC's, e.g. the
        GNS3 VM's trunk NIC, which GNS3's Cloud nodes use to bridge in
        arbitrary topology devices' own MACs. ESXi's default security policy
        rejects promiscuous mode and forged transmits, which silently drops
        all such relayed traffic without any visible error on either side.
        :param port_group_name: name of an existing port group to update
        :return:
        :raises RuntimeError: Is thrown when the port group does not exist,
            or when no host-system or network-system was found on the ESXi host.
        """
        if Settings.ONLY_ON_GNS3:
            return
        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"Would ensure bridging security policy on {port_group_name}",
            )
            return
        Verbosity.volumatic_print(
            Verbosity.NORMAL, f"Ensures bridging security policy on {port_group_name}"
        )
        # ----------------------------------------------------------------------------------------------------------

        host_system = self._get_object_by_name(vim.HostSystem)
        if host_system is None:
            logger.error(msg := "No host system found on ESXi.")
            raise RuntimeError(msg)
        network_system = host_system.configManager.networkSystem
        if network_system is None:
            logger.error(msg := "No network system found on ESXi.")
            raise RuntimeError(msg)

        port_group = next(
            (
                pg
                for pg in network_system.networkInfo.portgroup
                if pg.spec.name == port_group_name
            ),
            None,
        )
        if port_group is None:
            logger.error(msg := f"Port group {port_group_name} not found on ESXi.")
            raise RuntimeError(msg)

        spec = port_group.spec
        spec.policy = spec.policy or vim.host.NetworkPolicy()
        security = spec.policy.security or vim.host.NetworkPolicy.SecurityPolicy()
        if (
            security.allowPromiscuous
            and security.macChanges
            and security.forgedTransmits
        ):
            return

        security.allowPromiscuous = True
        security.macChanges = True
        security.forgedTransmits = True
        spec.policy.security = security

        network_system.UpdatePortGroup(pgName=port_group_name, portgrp=spec)

    @staticmethod
    def _create_mapped_network(node: GenericNode) -> dict[str, str]:
        """
        Creates a network mapping for ESXi, so that the interfaces of the VM will connect to the correct port groups on the virtual switch.
        :param node: Node to create this mapping for.
        :return: Returns a dictionary with the interface name, mapped to its vlan name.
        :raises RuntimeError: Is thrown when a vlan, which should exist, does not exist on the corresponding interface.
        """
        mapped_network = {}
        for interface in node.interfaces.values():
            vlan = interface.vlan
            if vlan is None:
                logger.error(
                    msg
                    := f"Something went wrong with the graph initialization. Needed VLAN does not exist on {node.name}.{interface.name}"
                )
                raise RuntimeError(msg)
            mapped_network[interface.name] = vlan.name
        return mapped_network

    def deploy_virtual_machine(self, node: GenericNode, datastore: str) -> None:
        """
        Deploys the virtual machine on the ESXi host.
        :param node: Node which represents the virtual machine to be deployed.
        :param datastore: Name of the datastore, to store the virtual machine on.
        :return:
        :raises TimeoutError: Is thrown when it took too long to receive a response.
        """
        if Settings.ONLY_ON_GNS3:
            return
        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Would deploy {node.name} on ESXi: {node.image}"
            )
            return
        Verbosity.volumatic_print(
            Verbosity.NORMAL, f"Deploys {node.name} on ESXi: {node.image}"
        )
        # --------------------------------------------------------------------------------------------------------------

        ova_filename = APIHandler.get_ova(node.image)
        mapped_network = self._create_mapped_network(node)

        # @TODO CONTROL IF RESOURCES ARE EVEN ON THE ESXI HOST. PROPABLY BEST TO CHECK ON THE DEPLOYMENT API.
        json = {
            "ip": self.ip,
            "port": self.port,
            "vm_name": node.name,
            "ova_filename": ova_filename,
            "datastore": datastore,
            "network": mapped_network,
        }

        Verbosity.volumatic_print(
            Verbosity.DEBUG, ("VM_Deployment_JSON_Data: " + str(json))
        )

        APIHandler.post(url="http://10.20.20.172:8003/deploy/ova", json=json)
