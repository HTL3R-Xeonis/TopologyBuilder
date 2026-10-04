from pyVmomi import vim

from src.connections.esxi_connection import ESXiConnection

from ..graph import Environment, Graph
from ..graph.blocks import GenericNode
from .status import Status


class ESXiDoctor:
    """
    Object to check the state of the ESXi host and properties of its resources.
    """

    def __init__(self, esxi_connection: ESXiConnection) -> None:
        """
        :param esxi_connection: Running connection to the ESXi API.
        """
        self.connection = esxi_connection

    def _check_virtual_machine_port_groups(
        self, node: GenericNode, virtual_machine: vim.VirtualMachine
    ) -> list[Status]:
        """
        Checks if the virtual machine is attached to all the needed portgroups according to the graph node.
        :param node: Corresponding node of the Graph. Is the source of truth.
        :param virtual_machine: Virtual machine to be checked.
        :return: List of statuses.
        """
        statuses = []
        needed_node_port_groups = {intf.vlan.name: intf for intf in node.interfaces.values() if intf.vlan is not None}
        virtual_machine_nics = self.connection.get_virtual_machine_nics(virtual_machine)
        for nic in virtual_machine_nics:
            if not isinstance(nic.backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                continue
            statuses.append(
                Status.ok(f"Port group {nic.backing.deviceName} attached to virtual machine {virtual_machine.name}.")
            )
            if not nic.backing.deviceName in needed_node_port_groups:
                statuses.append(
                    Status.info(
                        f"Additional Portgroup {nic.backing.deviceName} attached to virtual machine {virtual_machine.name}."
                    )
                )
                continue
            del needed_node_port_groups[nic.backing.deviceName]

        for port_groups in needed_node_port_groups:
            statuses.append(
                Status.missing(f"Port group {port_groups} not attached to virtual machine {virtual_machine.name}.")
            )
        return statuses

    def _check_port_group_vlan_id(self, node: GenericNode, virtual_machine: vim.VirtualMachine) -> list[Status]:
        """
        Checks if all portgroups attached to the virtual machine have the correct Vlan ID.
        :param node: Corrsponding node of the Graph. Is the source of truth.
        :param virtual_machine: Virtual machine to be checked.
        :return: List of statuses.
        """
        statuses = []
        vlans_mapping = {intf.vlan.name: intf.vlan for intf in node.interfaces.values() if intf.vlan is not None}

        for portgroup in virtual_machine.runtime.host.config.network.portgroup:
            if not portgroup.spec.name in vlans_mapping:
                continue
            graph_vlan_id = vlans_mapping[portgroup.spec.name].id
            if portgroup.spec.vlanId != graph_vlan_id:
                statuses.append(
                    Status.fault(
                        f"VlanId {portgroup.spec.vlanId} of portgroup {portgroup.spec.name} does not match the VlanId in the graph: {graph_vlan_id}."
                    )
                )
                continue
            statuses.append(
                Status.ok(
                    f"VlanId {portgroup.spec.vlanId} of portgroup {portgroup.spec.name} matches the VlanId in the graph."
                )
            )
        return statuses

    def _check_virtual_machine_existence(self, virtual_machine_name: str) -> tuple[vim.VirtualMachine | None, Status]:
        """
        Checks if a virtual machine with given name exists.
        :param virtual_machine_name: Name of the virtual machine to look for.
        :return: A tuple with the virtual machine or ``None``, if not found, and the corresponding status.
        """
        virtual_machine = self.connection.get_virtual_machine(virtual_machine_name)
        if virtual_machine is None:
            return virtual_machine, Status.missing(f"Virtual machine {virtual_machine_name} does not exist.")
        return virtual_machine, Status.ok(f"Virtual machine {virtual_machine_name} exists.")

    def is_graph_esxi_sided_deployed(self, graph: Graph) -> list[Status]:
        """
        Checks whether the graph is correctly deployed on the ESXi side.
        :param graph: Corresponding graph to check for. Is the source of truth.
        :return: List of statuses.
        """
        statuses: list[Status] = []

        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue

            virtual_machine, virtual_machine_status = self._check_virtual_machine_existence(node.name)
            statuses.append(virtual_machine_status)
            if virtual_machine is None:
                continue

            statuses.extend(self._check_virtual_machine_port_groups(node, virtual_machine))
            statuses.extend(self._check_port_group_vlan_id(node, virtual_machine))
        return statuses
