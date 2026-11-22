from typing import Any

from loguru import logger
from pyVim.task import WaitForTasks
from pyVmomi import vim

from src.connections.esxi_connection import ESXiConnection
from src.graph.blocks import GenericNode
from src.settings import Settings, Verbosity

from .ova_importer import OvaImporter


class ESXiOrchestrator:
    """
    Orchestration object for ESXi.
    """

    def __init__(self, esxi_connection: ESXiConnection):
        """
        :param esxi_connection: API connection to the ESXi host.
        """
        self.esxi_connection = esxi_connection

    def ensure_virtual_switch(self, virtual_switch_name: str) -> vim.host.VirtualSwitch:
        """
        Ensures the ESXi virtual switch exists and has the required security policy.
        :param virtual_switch_name: Virtual switch name.
        :return: Existing or created switch.
        :raises RuntimeError: If the ESXi host network cannot be configured.
        :raises ValueError: If the virtual switch name is invalid.
        """
        virtual_switch = self.esxi_connection.get_virtual_switch(virtual_switch_name)
        if virtual_switch is None:
            logger.info("Creating ESXi virtual switch: name={}", virtual_switch_name)
            Verbosity.volumatic_print(Verbosity.NORMAL, f"Creates virtual switch: {virtual_switch_name}")
            virtual_switch = self.esxi_connection.create_virtual_switch(virtual_switch_name)
        self._ensure_virtual_switch_policy(virtual_switch)
        return virtual_switch

    def _ensure_virtual_switch_policy(self, virtual_switch: vim.host.VirtualSwitch) -> None:
        """
        Ensures the required security policy of the virtual switch.
        :param virtual_switch: Virtual switch to check.
        :return:
        :raises RuntimeError: If the ESXi host network is unavailable.
        """
        update_spec = virtual_switch.spec
        if update_spec.policy is None:
            update_spec.policy = vim.host.NetworkPolicy()
        if update_spec.policy.security is None:
            update_spec.policy.security = vim.host.NetworkPolicy.SecurityPolicy()
        is_change_needed = False
        if not update_spec.policy.security.allowPromiscuous:
            update_spec.policy.security.allowPromiscuous = True
            is_change_needed = True
        if not update_spec.policy.security.forgedTransmits:
            update_spec.policy.security.forgedTransmits = True
            is_change_needed = True
        if not update_spec.policy.security.macChanges:
            update_spec.policy.security.macChanges = True
            is_change_needed = True
        if is_change_needed:
            logger.info("Updating ESXi virtual switch security policy: name={}", virtual_switch.name)
            host = self.esxi_connection.get_esxi_object(vim.HostSystem)
            if host is None:
                logger.error(msg := f"Hostsystem not found on ESXi host: {self.esxi_connection.ip}")
                raise RuntimeError(msg)
            network_system = host.configManager.networkSystem
            if network_system is None:
                logger.error(msg := f"NetworkSystem not found on ESXi host: {self.esxi_connection.ip}")
                raise RuntimeError(msg)

            network_system.UpdateVirtualSwitch(vswitchName=virtual_switch.name, spec=update_spec)

    def remove_port_groups(self, port_groups: set[str] | dict[str, Any], managed_only: bool = True) -> None:
        """
        Deletes unused, unprotected port groups from the configured switch.
        :param port_groups: Port-group names approved for deletion.
        :param managed_only: Restrict removal to the configured virtual switch.
        :raises RuntimeError: If the ESXi port-group inventory or removal fails.
        """
        protected = set(Settings.ESXI.IGNORE_PORT_GROUPS or ())
        protected.update((Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP))
        if managed_only and Settings.ESXI.VIRTUAL_SWITCH in (Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ()):
            return

        existing = self.esxi_connection.get_all_port_groups()
        all_vms = self.esxi_connection.get_esxi_object(vim.VirtualMachine, get_all=True) or []
        host = self.esxi_connection.get_esxi_object(vim.HostSystem)
        if host is None:
            raise RuntimeError("Cannot inspect ESXi VMkernel adapters before deleting port groups")
        vmkernel_groups = {adapter.portgroup for adapter in (host.config.network.vnic or [])}
        switches = {switch.name: switch for switch in host.config.network.vswitch or []}
        for name in sorted(port_groups):
            current = existing.get(name)
            if name in protected or current is None:
                continue
            if current.spec.vswitchName in (Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ()):
                continue
            if managed_only and current.spec.vswitchName != Settings.ESXI.VIRTUAL_SWITCH:
                continue
            switch = switches.get(current.spec.vswitchName)
            if not managed_only and (switch is None or self.esxi_connection.virtual_switch_has_uplinks(switch)):
                logger.warning(f"Keeping port group {name}: switch is unknown or has physical uplinks")
                continue
            if name in vmkernel_groups:
                logger.warning(f"Keeping port group {name}: used by an ESXi VMkernel adapter")
                continue
            users = [
                vm.name
                for vm in all_vms
                if any(
                    self.esxi_connection.get_nic_port_group(nic) == name
                    for nic in self.esxi_connection.get_virtual_machine_nics(vm)
                )
            ]
            if users:
                logger.warning(f"Keeping port group {name}: used by VM(s) {', '.join(users)}")
                continue
            logger.info("Removing ESXi port group: name={}", name)
            self.esxi_connection.remove_port_group(name)

    def destroy_virtual_machines(self, virtual_machines: list[vim.VirtualMachine]) -> None:
        """
        Powers off and deletes explicitly selected graph-owned ESXi VMs.
        :param virtual_machines: ESXi VMs approved for deletion.
        :raises RuntimeError: If a protected VM is selected.
        :raises vim.fault.VimFault: If a VM power-off or deletion task fails.
        """
        protected = set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ())
        protected.add(Settings.ESXI.GNS3_VM_NAME)
        for vm in virtual_machines:
            if ESXiConnection.compare_regular_to_esxi_name(protected, vm.name):
                raise RuntimeError(f"Refusing to delete protected ESXi VM {vm.name}")
        for vm in virtual_machines:
            vm_name = vm.name
            logger.info("Deleting ESXi VM: name={}", vm_name)
            if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOff:
                WaitForTasks([vm.PowerOffVM_Task()])
            WaitForTasks([vm.Destroy_Task()])
            logger.info("ESXi VM deleted: name={}", vm_name)

    # @TODO upgrade resetting vSwitch
    def destroy_old_vms(self, needed_port_groups: dict[str, int]) -> None:
        """
        Destroys the all virtual machines from the needed port groups. Does not destroy the VMs in the ignored port groups.
        :return:
        """
        tasks = []
        for pg_name in needed_port_groups:
            if pg_name in Settings.ESXI.IGNORE_PORT_GROUPS:
                continue
            tasks.extend(self._delete_vms_in_port_group(pg_name))
        WaitForTasks(tasks)

    # @TODO Does not Handle missing adapters. Fix this. And fix parameter requests of None
    def ensure_gns3_vm_adapter(self, gns3_vm_name: str, mgmt_port_group: str, trunk_port_group: str) -> None | vim.Task:
        """
        Checks and corrects the adapters of the GNS3 VM on ESXi to match a correct settings for possible connectivity.
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host to check.
        :param mgmt_port_group: Name of the management-portgroup. This will be assigned to the first NIC.
        :param trunk_port_group: Name of the trunk-portgroup. This portgroup should have a vlanID of 4095. This will be assigned to the second NIC.
        :return: Returns a ``vim.Task`` object if changes were made, ``None`` otherwise.
        """
        gns3_vm = self.esxi_connection.get_virtual_machine(gns3_vm_name)
        device_changes = []
        for device in gns3_vm.config.hardware.device:
            if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                continue
            if not isinstance(device.backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                continue
            device_name = device.backing.deviceName
            if device.deviceInfo.label.endswith("1"):
                if device_name == mgmt_port_group:
                    continue
                device.backing.deviceName = mgmt_port_group

            if device.deviceInfo.label.endswith("2"):
                if device_name == trunk_port_group:
                    continue
                device.backing.deviceName = trunk_port_group

            device.connectable.connected = False
            device_spec = vim.vm.device.VirtualDeviceSpec()
            device_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
            device_spec.device = device
            device_changes.append(device_spec)

        if not device_changes:
            return None
        config_spec = vim.vm.ConfigSpec()
        config_spec.deviceChange = device_changes

        return gns3_vm.ReconfigVM_Task(spec=config_spec)

    def ensure_adapter_connection(
        self,
        vm_names: list[str] | set[str],
        port_group_names: dict[str, Any],
        should_connect: bool = True,
    ) -> None:
        """
        Disconnects or connects the adapters of the VM on the ESXi host from given portgroups.
        :param vm_names: Name of the vm on the ESXi host, to edit the adapters from.
        :param port_group_names: Names of the portgroups on the ESXi host, from which the vm should be disconnected.
        :param should_connect: Set to ``True`` if the adapters should be connected or ``False`` otherwise.
        :return:
        """
        tasks = []
        for vm_name in vm_names:
            vm = self.esxi_connection.get_virtual_machine(vm_name)
            if vm is None:
                continue

            device_changes = []
            for device in vm.config.hardware.device:
                if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                    continue
                if not isinstance(device.backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                    continue
                if device.backing.deviceName not in port_group_names:
                    continue

                device.connectable.connected = should_connect
                device_spec = vim.vm.device.VirtualDeviceSpec()
                device_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
                device_spec.device = device
                device_changes.append(device_spec)

            if not device_changes:
                continue
            config_spec = vim.vm.ConfigSpec()
            config_spec.deviceChange = device_changes

            tasks.append(vm.ReconfigVM_Task(spec=config_spec))
        WaitForTasks(tasks)

    def _delete_vms_in_port_group(self, port_group_name: str) -> list[vim.Task]:
        """
        Deletes all virtual machines which have an adapter to the specified portgroup. VMs specified in ``Settings.ESXI.IGNORE_VIRTUAL_MACHINES`` or ``Settings.ESXI.GNS3_VM_NAME`` will not be deleted.
        :param port_group_name: Name of the portgroup to delete the virtual machines from.
        :return: Returns a list of ``vim.Task`` objects for the deletion process of each virtual machine.
        :raises RuntimeError: Is thrown when no ContainerView can be created.
        """
        virtual_machines = self.esxi_connection.get_esxi_object(vim.VirtualMachine, get_all=True)
        tasks = []
        for vm in virtual_machines:
            if ESXiConnection.compare_regular_to_esxi_name(
                Settings.ESXI.GNS3_VM_NAME, vm.name
            ) or ESXiConnection.compare_regular_to_esxi_name(Settings.ESXI.IGNORE_VIRTUAL_MACHINES, vm.name):
                continue

            hardware = getattr(vm.config, "hardware", [])
            for device in getattr(hardware, "device", []):
                if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                    continue
                backing = device.backing
                if not isinstance(backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                    continue
                if backing.deviceName != port_group_name:
                    continue
                tasks.append(vm.Destroy_Task())

        return tasks

    def create_port_groups(self, needed_port_groups: dict[str, int], update: bool = False) -> None:
        """
        Creates or updates port groups while preserving VM connections.
        :param needed_port_groups: Port-group names mapped to VLAN IDs.
        :param update: Whether to update existing port groups.
        :raises RuntimeError: If a port group or its connected adapters cannot be configured.
        """
        existing = self.esxi_connection.get_all_port_groups() if update else {}
        for pg_name, pg_id in needed_port_groups.items():
            logger.info("Configuring ESXi port group: name={}, vlan={}, update={}", pg_name, pg_id, update)
            current = existing.get(pg_name)
            if current is None or current.spec.vswitchName == Settings.ESXI.VIRTUAL_SWITCH:
                self.esxi_connection.add_port_group(pg_name, pg_id, update=update)
                continue
            logger.info(
                "Moving ESXi port group: name={}, from={}, to={}, vlan={}",
                pg_name, current.spec.vswitchName, Settings.ESXI.VIRTUAL_SWITCH, pg_id,
            )
            host = self.esxi_connection.get_esxi_object(vim.HostSystem)
            if any(nic.portgroup == pg_name for nic in (host.config.network.vnic or [])):
                raise RuntimeError(f"Cannot move port group {pg_name}: used by an ESXi VMkernel adapter")
            adapters = [
                (
                    vm,
                    nic,
                    getattr(nic.connectable, "connected", False),
                    getattr(nic.connectable, "startConnected", False),
                )
                for vm in (self.esxi_connection.get_esxi_object(vim.VirtualMachine, get_all=True) or [])
                for nic in self.esxi_connection.get_virtual_machine_nics(vm)
                if self.esxi_connection.get_nic_port_group(nic) == pg_name
            ]
            source_spec = current.spec
            try:
                self.ensure_adapter_connection({vm.name for vm, _, _, _ in adapters}, {pg_name}, False)
                self.esxi_connection.remove_port_group(pg_name)
                try:
                    self.esxi_connection.add_port_group(pg_name, pg_id)
                    moved = self.esxi_connection.get_all_port_groups().get(pg_name)
                    if moved is None or moved.spec.vswitchName != Settings.ESXI.VIRTUAL_SWITCH or int(moved.spec.vlanId) != pg_id:
                        raise RuntimeError(f"Port group {pg_name} could not be verified on {Settings.ESXI.VIRTUAL_SWITCH}")
                except Exception as exc:
                    logger.warning("ESXi port group move failed; restoring original configuration: name={}", pg_name)
                    if pg_name not in self.esxi_connection.get_all_port_groups():
                        try:
                            self.esxi_connection.add_port_group(
                                pg_name,
                                source_spec.vlanId,
                                virtual_switch_name=source_spec.vswitchName,
                                policy=source_spec.policy,
                            )
                        except RuntimeError as rollback_exc:
                            raise RuntimeError(
                                f"Could not restore port group {pg_name} on {source_spec.vswitchName}: {rollback_exc}"
                            ) from exc
                    raise
            finally:
                restore_errors = []
                for vm, nic, connected, start_connected in adapters:
                    try:
                        self._configure_network_adapter(vm, nic, pg_name, connected, start_connected)
                    except Exception as exc:  # noqa: BLE001
                        restore_errors.append(f"{vm.name} NIC {nic.key}: {exc}")
                if restore_errors:
                    raise RuntimeError(f"Could not restore adapters on {pg_name}: " + "; ".join(restore_errors))

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
        :raises TypeError: If the datastore is not available.
        :raises RuntimeError: If VLAN mapping or VM deployment fails.
        :raises TimeoutError: If VM deployment times out.
        """
        logger.info("Deploying ESXi VM: name={}, image={}, datastore={}", node.name, node.image, datastore)
        Verbosity.volumatic_print(Verbosity.NORMAL, f"Deploys {node.name} on ESXi: {node.image}")
        datastore_object = self.esxi_connection.get_esxi_object(vim.Datastore, datastore)
        if not isinstance(datastore_object, vim.Datastore):
            raise TypeError(f"No datastore found with name: {datastore}")

        importer = OvaImporter(
            esxi_connection=self.esxi_connection,
            node=node,
            datastore=datastore_object,
            network_mapping=self._create_mapped_network(node),
        )
        importer.deploy_ova()
        logger.info("ESXi VM deployment completed: name={}", node.name)

    def _add_virtual_machine_adapters(self, vm: vim.VirtualMachine, groups: list[str]) -> None:
        """
        Adds ESXi adapters connected to the specified port groups.
        :param vm: Existing ESXi virtual machine.
        :param groups: Port groups for new adapters.
        :raises TypeError: If a port group cannot be found.
        """
        changes = []
        for index, name in enumerate(groups):
            network = self.esxi_connection.get_esxi_object(vim.Network, name)
            if not isinstance(network, vim.Network):
                raise TypeError(f"ESXi port group {name} is not available")
            changes.append(OvaImporter._create_new_nic(network, -151 - index))
        spec = vim.vm.ConfigSpec()
        spec.deviceChange = changes
        WaitForTasks([vm.ReconfigVM_Task(spec=spec)])

    def _configure_network_adapter(
        self,
        vm: vim.VirtualMachine,
        nic: vim.vm.device.VirtualEthernetCard,
        group: str,
        connected: bool | None = None,
        start_connected: bool | None = None,
    ) -> None:
        """
        Assigns an ESXi adapter to a port group and restores its connection state.
        :param vm: Existing virtual machine.
        :param nic: Network adapter to update.
        :param group: Target port-group name.
        :param connected: Connection state to restore, or ``None`` to connect a running VM.
        :param start_connected: Startup connection state, or ``None`` to enable it.
        :raises TypeError: If the requested port group is missing.
        """
        network = self.esxi_connection.get_esxi_object(vim.Network, group)
        if not isinstance(network, vim.Network):
            raise TypeError(f"ESXi port group {group} is not available")
        nic.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
            deviceName=group, network=network, useAutoDetect=False
        )
        if nic.connectable is None:
            nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        nic.connectable.startConnected = True if start_connected is None else start_connected
        if connected is not None:
            nic.connectable.connected = connected
        elif vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            nic.connectable.connected = True
        spec = vim.vm.ConfigSpec()
        spec.deviceChange = [
            vim.vm.device.VirtualDeviceSpec(operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=nic)
        ]
        WaitForTasks([vm.ReconfigVM_Task(spec=spec)])
