from __future__ import annotations

import atexit
import re
import ssl
import time
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

    def get_host_system(self) -> vim.HostSystem:
        """
        Returns the ESXi host system. Assumes a standalone host connection
        (one datacenter, one compute resource, one host), which is what
        SmartConnect gives us when connecting directly to an ESXi host
        rather than through vCenter.
        :return: the ESXi HostSystem
        """
        return self._get_object_by_name(vim.HostSystem)

    def find_datastore(self, name: str) -> vim.Datastore:
        """
        Finds a datastore by name.
        :param name: name of the datastore
        :return: the matching Datastore
        :raises ValueError: Is thrown when no datastore with the given name is found.
        """
        datastore = self._get_object_by_name(vim.Datastore, name)
        if datastore is None:
            logger.error(msg := f"Datastore '{name}' not found")
            raise ValueError(msg)
        return datastore

    def get_all_datastores(self) -> list[vim.Datastore]:
        """
        Returns every datastore registered on the host.
        :return: list of all datastores
        """
        view = self.view_manager.CreateContainerView(
            self.content.rootFolder, [vim.Datastore], True
        )
        try:
            return list(view.view)
        finally:
            view.Destroy()

    def find_biggest_datastore(self) -> vim.Datastore:
        """
        Finds the datastore with the most free space - used to auto-pick
        a datastore when ``Settings.ESXI.DATASTORE`` is left unset.
        :return: the datastore with the largest summary.freeSpace
        :raises ValueError: Is thrown when no datastore exists on the host.
        """
        datastores = self.get_all_datastores()
        if not datastores:
            logger.error(msg := f"No datastore found on host: {self.ip}")
            raise ValueError(msg)
        return max(datastores, key=lambda datastore: datastore.summary.freeSpace)

    def find_network(self, name: str) -> vim.Network:
        """
        Finds a network (port group) by name.
        :param name: name of the port group
        :return: the matching Network
        :raises ValueError: Is thrown when no network/port group with the given name is found.
        """
        network = self._get_object_by_name(vim.Network, name)
        if network is None:
            logger.error(msg := f"Network/port group '{name}' not found")
            raise ValueError(msg)
        return network

    def get_vm(self, vm_name: str) -> vim.ManagedEntity | None:
        """
        Searches for a VM with given name.
        :param vm_name: Name of VM to look for.
        :return: Returns Virtual Machine if found, else None.
        """
        return self._get_object_by_name(vim.VirtualMachine, vm_name)

    def get_all_vms(self) -> list[vim.VirtualMachine]:
        """
        Returns every VM registered on the host.
        :return: list of all VMs
        """
        view = self.view_manager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            return list(view.view)
        finally:
            view.Destroy()

    def find_gns3_vm(self) -> vim.VirtualMachine | None:
        """
        Searches for a VM whose name contains 'gns3' (case-insensitive) -
        used to auto-detect the GNS3 VM without relying on
        ``Settings.ESXI.GNS3_VM_NAME`` being exactly right, since a stale
        or misconfigured name there must never cause the real GNS3 VM to
        be auto-deleted as an 'unused' leftover by delete_unused_vms.
        :return: the matching VM if exactly one was found, else None
        :raises ValueError: Is thrown when more than one VM's name contains 'gns3', since it's then not safe to guess which one is the real GNS3 VM.
        """
        matches = [vm for vm in self.get_all_vms() if "gns3" in vm.name.lower()]
        if len(matches) > 1:
            names = [vm.name for vm in matches]
            logger.error(
                msg := f"Multiple VMs look like a GNS3 VM: {names}. Cannot "
                f"safely auto-detect which one to protect from deletion."
            )
            raise ValueError(msg)
        return matches[0] if matches else None

    def set_vm_annotation(self, vm: vim.VirtualMachine, annotation: str) -> None:
        """
        Sets the VM's annotation/notes field. Used to tag every VM this
        tool imports with 'topologybuilder-image:<image>', so
        delete_unused_vms can later tell which VMs it's safe to clean up
        automatically versus VMs it never created.
        :param vm: the VM to tag
        :param annotation: the annotation text to set
        :return:
        """
        self._wait_for_task(
            vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(annotation=annotation))
        )

    def find_vms_matching(self, name: str) -> list[vim.ManagedEntity]:
        """
        Finds every VM whose name exactly matches ``name``, or looks like an
        auto-renamed duplicate of it (ESXi appends e.g. '_1' or ' (1)' when
        an import collides with an existing VM's name). Used to clean up
        VMs left over from an earlier deploy of a topology node before
        redeploying or destroying it, so redeploys don't accumulate
        duplicates.
        :param name: the node name to match against
        :return: list of matching VMs
        """
        pattern = re.compile(rf"^{re.escape(name)}([ _]\(?\d+\)?)?$")
        view = self.view_manager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            return [vm for vm in view.view if pattern.match(vm.name)]
        finally:
            view.Destroy()

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

    def is_vm_powered_on(self, vm: vim.VirtualMachine) -> bool:
        """
        Checks whether the given VM is currently powered on.
        :param vm: the VM to check
        :return: True if powered on
        """
        return vm.runtime.powerState == vim.VirtualMachine.PowerState.poweredOn

    def get_vm_network_names(self, vm: vim.VirtualMachine) -> list[str]:
        """
        Returns the ESXi port group name each of the VM's Ethernet network
        adapters is currently connected to, in device order. Used to
        verify a NIC is actually wired to an expected port group before
        trusting traffic sent to it - ESXi gives no error or warning for a
        NIC left connected to the wrong port group, it just silently
        doesn't carry the traffic anyone expects it to.
        :param vm: the VM to inspect
        :return: list of port group names, one per Ethernet adapter
        """
        names = []
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                names.append(getattr(device.backing, "deviceName", None))
        return names

    def find_vm_nic_mac_by_port_group(
        self, vm: vim.VirtualMachine, port_group_name: str
    ) -> str | None:
        """
        Finds the MAC address of the VM's Ethernet adapter connected to
        the given port group. Used to correlate an ESXi-side port group
        with a guest-OS network interface by MAC, since the guest-OS
        interface name isn't guaranteed to match any particular
        convention (see VMOrchestrator._resolve_gns3_parent_interface).
        :param vm: the VM to inspect
        :param port_group_name: name of the port group to look for
        :return: the matching adapter's MAC address, or None if no adapter is connected to that port group
        """
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                if getattr(device.backing, "deviceName", None) == port_group_name:
                    return device.macAddress
        return None

    def find_virtual_switch(self) -> vim.host.VirtualSwitch | None:
        """
        Looks for a virtual Switch with the name, specified in ``Settings.Esxi.VIRTUAL_SWITCH``, on the ESXi Host.
        :return: the virtual Switch if found, else None.
        """
        host = self._get_object_by_name(vim.HostSystem)
        config = getattr(host, "config", vim.host.ConfigInfo)
        vswitches = getattr(config.network, "vswitch", [])

        for vswitch in vswitches:
            if vswitch.name == Settings.ESXI.VIRTUAL_SWITCH:
                return vswitch
        return None

    def _get_virtual_switch(self) -> vim.host.VirtualSwitch:
        """
        Looks for a virtual Switch with the name, specified in ``Settings.Esxi.VIRTUAL_SWITCH``, on the ESXi Host.
        :return: Returns the virtual Switch if found.
        :raises ValueError: Is thrown when no fitting virtual Switch was found.
        """
        vswitch = self.find_virtual_switch()
        if vswitch is None:
            logger.error(
                msg
                := f"virtual switch {Settings.ESXI.VIRTUAL_SWITCH} not found on host: {self.ip}"
            )
            raise ValueError(msg)
        return vswitch

    def ensure_virtual_switch_exists(self) -> None:
        """
        Creates ``Settings.ESXI.VIRTUAL_SWITCH`` if it doesn't already
        exist, as a plain internal-only vSwitch (no physical uplink NIC
        attached) - isolated topology traffic never needs to leave the
        host, and guessing which physical NIC to bind as an uplink would
        be unsafe on infra this tool doesn't otherwise know about. A
        no-op if the vSwitch already exists.
        :return:
        :raises RuntimeError: Is thrown when no host-system or network-system was found on the ESXi host, or when creation fails.
        """
        if Settings.ONLY_ON_GNS3:
            return
        if self.find_virtual_switch() is not None:
            return
        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"Would create vSwitch {Settings.ESXI.VIRTUAL_SWITCH}",
            )
            return
        Verbosity.volumatic_print(
            Verbosity.NORMAL, f"Creates vSwitch {Settings.ESXI.VIRTUAL_SWITCH}"
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

        spec = vim.host.VirtualSwitch.Specification()
        spec.numPorts = 128
        try:
            network_system.AddVirtualSwitch(
                vswitchName=Settings.ESXI.VIRTUAL_SWITCH, spec=spec
            )
        except Exception as exc:
            logger.error(
                msg
                := f"Something went wrong while creating vSwitch {Settings.ESXI.VIRTUAL_SWITCH}."
            )
            raise RuntimeError(msg) from exc
        logger.info(f"Created vSwitch '{Settings.ESXI.VIRTUAL_SWITCH}'")

    def _add_port_group(self, vlan: VirtualLan) -> None:
        """
        Ensures a port group for the given ``vlan`` exists on the virtual
        switch, creating it if it's missing.
        :param vlan: VLAN Object of the ``graph.blocks.Interface`` to create the port group
        :return:
        :raises RuntimeError: Is thrown when no host-system or network-system was found on the ESXi host.
        """
        self._ensure_port_group(vlan.name, vlan.id)

    def _ensure_port_group(self, name: str, vlan_id: int) -> None:
        """
        Ensures a port group with the given ``name``/``vlan_id`` exists on
        the virtual switch, creating it if it's missing. A no-op if a port
        group with that name already exists - AddPortGroup itself has no
        "create if missing" mode, so the existing-names check happens here
        instead, which is what lets a redeployed/incremental topology
        reuse port groups from an earlier deploy instead of erroring out.
        The policies are inherited from the virtual Switch on ESXi.
        :param name: name of the port group
        :param vlan_id: VLAN ID to tag the port group with
        :return:
        :raises RuntimeError: Is thrown when no host-system or network-system was found on the ESXi host.
        """
        if Settings.ONLY_ON_GNS3:
            return
        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(Verbosity.NORMAL, f"Would add portgroup {name}")
            return
        # ----------------------------------------------------------------------------------------------------------

        host_system = self._get_object_by_name(vim.HostSystem)
        if host_system is None:
            logger.error(msg := "No host system found on ESXi.")
            raise RuntimeError(msg)
        network_system = host_system.configManager.networkSystem
        if network_system is None:
            logger.error(msg := "No network system found on ESXi.")
            raise RuntimeError(msg)

        existing_names = {
            portgroup.spec.name for portgroup in network_system.networkInfo.portgroup
        }
        if name in existing_names:
            return

        Verbosity.volumatic_print(Verbosity.NORMAL, f"Adds portgroup {name}")
        spec = vim.host.PortGroup.Specification()
        spec.name = name
        spec.vswitchName = Settings.ESXI.VIRTUAL_SWITCH
        spec.vlanId = vlan_id
        spec.policy = vim.host.NetworkPolicy()

        try:
            network_system.AddPortGroup(spec)
        except Exception as exc:
            logger.error(msg := f"Something went wrong while adding port group {name}.")
            raise RuntimeError(msg) from exc

    def ensure_trunk_port_group_exists(self) -> None:
        """
        Ensures ``Settings.ESXI.TRUNK_PORT_GROUP`` exists (VLAN 4095 -
        pass-all-tags/VGT mode, the standard convention for a trunk port
        group carrying every VLAN through to the GNS3 VM), creating it if
        missing, then ensures it accepts promiscuous mode/MAC changes/
        forged transmits either way.
        :return:
        :raises RuntimeError: Is thrown when no host-system or network-system was found on the ESXi host, or when creation fails.
        """
        self._ensure_port_group(Settings.ESXI.TRUNK_PORT_GROUP, 4095)
        self.ensure_bridging_security_policy(Settings.ESXI.TRUNK_PORT_GROUP)

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

    def list_port_groups(self) -> list[dict[str, str | int]]:
        """
        Lists the port groups configured on the ESXi host's vSwitch.
        :return: list of {"name", "vlan_id", "vswitch"} dicts
        :raises ValueError: Is thrown when no virtual Switch was found.
        """
        return [
            {
                "name": port_group.spec.name,
                "vlan_id": port_group.spec.vlanId,
                "vswitch": Settings.ESXI.VIRTUAL_SWITCH,
            }
            for port_group in self._get_port_groups()
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
        Deletes all port groups from the virtual switch, except for those
        specified in ``Settings.ESXI.IGNORE_PORT_GROUPS``,
        ``Settings.ESXI.TRUNK_PORT_GROUP``, and
        ``Settings.ESXI.RESERVED_PORT_GROUPS`` - the trunk port group and
        ESXi's own built-in port groups are always protected regardless of
        IGNORE_PORT_GROUPS' contents, since deleting the former would break
        the GNS3 VM's own network bridge, and deleting the latter can sever
        the host's own management access.
        :return:
        :raises ValueError: Is thrown when no virtual Switch was found.
        :raises RuntimeError: Is thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
        """
        port_groups = self._get_port_groups()
        protected = (
            Settings.ESXI.IGNORE_PORT_GROUPS
            | {Settings.ESXI.TRUNK_PORT_GROUP}
            | Settings.ESXI.RESERVED_PORT_GROUPS
        )
        for pg in port_groups:
            if pg.spec.name in protected:
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
        the trunk port group (``Settings.ESXI.TRUNK_PORT_GROUP``) exists
        (creating it if missing) and accepts promiscuous mode/MAC changes/
        forged transmits - required for GNS3's Cloud nodes to bridge in
        topology devices' own MACs through it. ESXi's default security
        policy silently drops that traffic otherwise, with no error on
        either side. Deduped by VLAN ID so a direct ESXi-to-ESXi link's two
        interfaces - which share the exact same VirtualLan object, see
        Graph._assign_vlans - only get one ``_add_port_group`` call
        instead of two (harmless in a real deploy since that call is
        idempotent, but a dry run would otherwise print the same "would
        add" line twice for what is really one port group).
        :param graph: Port groups are based of the VLANs on each ``Interface`` of each ``Node`` in given ``graph``.
        :return:
        :raises RuntimeError: Is thrown when a portgroup already exists  on the ESXi host.
        May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        seen_vlan_ids: set[int] = set()
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None or vlan.id in seen_vlan_ids:
                    continue
                seen_vlan_ids.add(vlan.id)
                self._add_port_group(vlan)

        self.ensure_trunk_port_group_exists()

    def find_port_group(self, port_group_name: str) -> vim.host.PortGroup | None:
        """
        Finds a port group by name on the ESXi host, read-only. Unlike
        ``_get_port_groups``, doesn't require the configured vSwitch to
        exist - used by read-only checks (e.g. ``doctor``) that need to
        report "missing" rather than raise.
        :param port_group_name: name of the port group to look for
        :return: the matching port group, or None if not found (including
            if no host/network system is available at all)
        """
        host_system = self._get_object_by_name(vim.HostSystem)
        if host_system is None:
            return None
        network_system = host_system.configManager.networkSystem
        if network_system is None:
            return None
        return next(
            (
                pg
                for pg in network_system.networkInfo.portgroup
                if pg.spec.name == port_group_name
            ),
            None,
        )

    @staticmethod
    def bridging_security_policy_ok(port_group: vim.host.PortGroup) -> bool:
        """
        Read-only check for whether a port group already accepts
        promiscuous mode, MAC address changes, and forged transmits.
        :param port_group: the port group to check
        :return: True if all three are already accepted
        """
        security = getattr(getattr(port_group.spec, "policy", None), "security", None)
        if security is None:
            return False
        return bool(
            security.allowPromiscuous
            and security.macChanges
            and security.forgedTransmits
        )

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

    def deploy_virtual_machine(
        self, node: GenericNode, datastore: str, incremental: bool = False
    ) -> None:
        """
        Deploys the virtual machine on the ESXi host: resolves the node's
        image to its exact OVA filename on the Template-API's NFS share,
        then has the TopologyBuilderServices OVA-deploy API import it
        directly from there to ESXi, with its network adapters wired to
        the VLAN port groups initialize_virtual_switch already set up,
        then powers it on.
        :param node: Node which represents the virtual machine to be deployed.
        :param datastore: Name of the datastore, to store the virtual machine on.
        :param incremental: if True, skips (re-)deploying a node whose VM
            already exists (matched by name) instead of importing a second,
            auto-renamed duplicate.
        :return:
        :raises TimeoutError: Is thrown when it took too long to receive a response.
        :raises RuntimeError: Is thrown when the OVA deploy fails, or the
            resulting VM cannot be found afterwards.
        :raises ValueError: Is thrown when a vlan, which should exist, does not exist on a corresponding interface.
        """
        if Settings.ONLY_ON_GNS3:
            return
        if incremental and self.find_vms_matching(node.name):
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"ESXi VM {node.name} already exists, skipping (incremental)",
            )
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

        network_mapping = {}
        for interface in node.interfaces.values():
            if interface.vlan is None:
                logger.error(
                    msg
                    := f"Something went wrong with the graph initialization. Needed VLAN does not exist on {node.name}.{interface.name}"
                )
                raise ValueError(msg)
            network_mapping[interface.name] = interface.vlan.name

        ova_filename = APIHandler.find_esxi_template_file(node.image)
        APIHandler.deploy_ova(
            self.ip, self.port, node.name, ova_filename, datastore, network_mapping
        )

        vm = self.get_vm(node.name)
        if vm is None:
            logger.error(
                msg := f"OVA deploy for {node.name} reported success, but no "
                f"matching VM was found afterwards."
            )
            raise RuntimeError(msg)

        self.set_vm_annotation(vm, f"topologybuilder-image:{node.image}")
        self.power_on_vm(vm)

    @staticmethod
    def _wait_for_task(task: vim.Task) -> None:
        """
        Blocks until the given vSphere task finishes, raising if it errors out.
        :param task: the task to wait for
        :return:
        :raises RuntimeError: Is thrown when the task fails.
        """
        while task.info.state not in (
            vim.TaskInfo.State.success,
            vim.TaskInfo.State.error,
        ):
            time.sleep(0.5)
        if task.info.state == vim.TaskInfo.State.error:
            logger.error(msg := f"vSphere task failed: {task.info.error}")
            raise RuntimeError(msg)

    def power_on_vm(self, vm: vim.VirtualMachine) -> None:
        """
        Powers on the given VM, if it isn't already.
        :param vm: the VM to power on
        :return:
        """
        if vm.runtime.powerState != vim.VirtualMachine.PowerState.poweredOn:
            self._wait_for_task(vm.PowerOnVM_Task())

    def power_off_vm(self, vm: vim.VirtualMachine) -> None:
        """
        Powers off the given VM, if it isn't already.
        :param vm: the VM to power off
        :return:
        """
        if vm.runtime.powerState != vim.VirtualMachine.PowerState.poweredOff:
            self._wait_for_task(vm.PowerOffVM_Task())

    def delete_vm(self, vm: vim.VirtualMachine) -> None:
        """
        Powers off (if needed) and permanently deletes the given VM. Used
        to clean up a VM left over from an earlier deploy, e.g. before
        redeploying or destroying a topology.
        :param vm: the VM to delete
        :return:
        """
        if Settings.ONLY_ON_GNS3:
            return
        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(Verbosity.NORMAL, f"Would delete VM {vm.name}")
            return
        Verbosity.volumatic_print(Verbosity.NORMAL, f"Deletes VM {vm.name}")
        # --------------------------------------------------------------------------------------------------------------
        self.power_off_vm(vm)
        self._wait_for_task(vm.Destroy_Task())

    def delete_port_group(self, name: str) -> None:
        """
        Deletes the named port group if it exists. Requires no VM to still
        be using the port group.
        :param name: name of the port group to delete
        :return:
        """
        if Settings.ONLY_ON_GNS3:
            return
        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Would delete portgroup {name}"
            )
            return
        # --------------------------------------------------------------------------------------------------------------

        host_system = self._get_object_by_name(vim.HostSystem)
        network_system = host_system.configManager.networkSystem
        existing_names = {
            portgroup.spec.name for portgroup in network_system.networkInfo.portgroup
        }
        if name not in existing_names:
            return

        Verbosity.volumatic_print(Verbosity.NORMAL, f"Deletes portgroup {name}")
        network_system.RemovePortGroup(pgName=name)
