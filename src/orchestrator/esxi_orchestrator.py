from typing import Any

from loguru import logger
from pyVmomi import vim
from pyVim.task import WaitForTasks

from src.connections import APIHandler
from src.connections.esxi_connection import ESXiConnection
from src.graph.blocks import GenericNode
from src.settings import Settings, Verbosity


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
        Ensures that the virtual switch exists on the ESXi Host. If it does not, it will be created.
        :param virtual_switch_name: Name of the virtual Switch.
        :return: Returns the found or created virtual switch.
        """
        virtual_switch = self.esxi_connection.get_virtual_switch(virtual_switch_name)
        if virtual_switch is None:
            virtual_switch = self.esxi_connection.create_virtual_switch(
                virtual_switch_name
            )
        return virtual_switch

    def _ensure_virtual_switch_policy(
        self, virtual_switch: vim.host.VirtualSwitch
    ) -> None:
        """
        Checks whether the virtual switch has the needed policies and sets updates them if needed.
        :param virtual_switch: Virtual switch to check.
        :return:
        :raises RuntimeError: Is thrown when the virtual switch already exists on the ESXi host. May also be thrown when no host-system or network-system was found.
        """
        update_spec = virtual_switch.spec

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
            host = self.esxi_connection.get_object_by_name(vim.HostSystem)
            if host is None:
                logger.error(
                    msg
                    := f"Hostsystem not found on ESXi host: {self.esxi_connection.ip}"
                )
                raise RuntimeError(msg)

            network_system = host.configManager.networkSystem
            if network_system is None:
                logger.error(
                    msg
                    := f"NetworkSystem not found on ESXi host: {self.esxi_connection.ip}"
                )
                raise RuntimeError(msg)

            network_system.UpdateVirtualSwitch(
                vswitchName=virtual_switch.name, spec=update_spec
            )

    def remove_port_groups(self, port_groups: set[str] | dict[str, Any]) -> None:
        """
        Deletes all port groups from the virtual switch, except for those specified in ``Settings.Esxi.IGNORE_PORT_GROUPS``.
        :param port_groups: Set of port groups names to remove.
        :return:
        :raises RuntimeError: Is thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
        """
        existing_port_groups = self.esxi_connection.get_all_port_groups()
        for pg_name in port_groups:
            if pg_name in Settings.ESXI.IGNORE_PORT_GROUPS:
                continue
            if pg_name in existing_port_groups:
                self.esxi_connection.remove_port_group(pg_name)

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
    def ensure_gns3_vm_adapter(
        self, gns3_vm_name: str, mgmt_port_group: str, trunk_port_group: str
    ) -> None | vim.Task:
        """
        Checks and corrects the adapters of the GNS3 VM on ESXi to match a correct settings for possible connectivity.
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host to check.
        :param mgmt_port_group: Name of the management-portgroup. This will be assigned to the first NIC.
        :param trunk_port_group: Name of the trunk-portgroup. This portgroup should have a vlanID of 4095. This will be assigned to the second NIC.
        :return: Returns a ``vim.Task`` object if changes were made, ``None`` otherwise.
        """
        gns3_vm = self.esxi_connection.get_vm(gns3_vm_name)
        device_changes = []
        for device in gns3_vm.config.hardware.device:
            if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                continue
            if not isinstance(
                device.backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo
            ):
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
            vm = self.esxi_connection.get_vm(vm_name)
            if vm is None:
                continue

            device_changes = []
            for device in vm.config.hardware.device:
                if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                    continue
                if not isinstance(
                    device.backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo
                ):
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
        virtual_machines = self.esxi_connection.get_object_by_name(
            vim.VirtualMachine, get_all=True
        )
        tasks = []
        for vm in virtual_machines:
            if (
                vm.name == Settings.ESXI.GNS3_VM_NAME
                or vm.name in Settings.ESXI.IGNORE_VIRTUAL_MACHINES
            ):
                continue

            hardware = getattr(vm.config, "hardware", [])
            for device in getattr(hardware, "device", []):
                if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                    continue
                backing = device.backing
                if not isinstance(
                    backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo
                ):
                    continue
                print(backing.deviceName)
                if not backing.deviceName == port_group_name:
                    continue
                tasks.append(vm.Destroy_Task())

        return tasks

    def create_port_groups(self, needed_port_groups: dict[str, int]) -> None:
        """
        Creates the needed port groups on the virtual switch.
        :param needed_port_groups: A dictionary with the portgroup names mapped to their VLAN id
        :return:
        :raises RuntimeError: Is thrown when a portgroup already exists  on the ESXi host.
        May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        for pg_name, pg_id in needed_port_groups.items():
            self.esxi_connection.add_port_group(pg_name, pg_id)

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
            "ip": self.esxi_connection.ip,
            "port": self.esxi_connection.port,
            "vm_name": node.name,
            "ova_filename": ova_filename,
            "datastore": datastore,
            "network": mapped_network,
        }

        Verbosity.volumatic_print(
            Verbosity.DEBUG, ("VM_Deployment_JSON_Data: " + str(json))
        )

        APIHandler.post(url="http://10.20.20.172:8003/deploy/ova", json=json)
