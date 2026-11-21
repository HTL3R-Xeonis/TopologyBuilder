from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .topology_state import TopologyChanges, TopologyState

if TYPE_CHECKING:
    from src.graph import Graph
from pyVmomi import vim

from src.graph import Environment
from src.settings import Settings

from .status import Status, StatusList


class ESXiDoctor:
    """Checks ESXi configuration and deployed virtual machines."""

    def __init__(self, connection) -> None:
        """Uses an existing ESXi connection for read-only checks."""
        self.connection = connection

    def _check_switch(self, name: str, switch: vim.host.VirtualSwitch | None, security: bool = False) -> StatusList:
        """
        Checks a virtual switch and its security policy.
        :param name: Expected virtual switch name.
        :param switch: Existing switch or None.
        :param security: Whether to validate promiscuous mode and MAC policies.
        :return: Switch health-check results.
        """
        results = StatusList()
        if switch is None:
            results.add(Status.missing("ESXi switch", f"{name} does not exist."))
            return results
        results.add(Status.ok("ESXi switch", f"{name} exists."))
        if security:
            policy = getattr(getattr(getattr(switch, "spec", None), "policy", None), "security", None)
            if policy is None:
                results.add(Status.missing("ESXi switch", f"{name}: security policy unavailable."))
            else:
                for field in ("allowPromiscuous", "macChanges", "forgedTransmits"):
                    if getattr(policy, field, None) is not True:
                        results.add(Status.fault("ESXi switch", f"{name}: {field} must be enabled."))
                if not results.has_failures:
                    results.add(Status.ok("ESXi switch", f"{name}: security policy is valid."))
        return results

    def _check_vm(self, name: str, vm: vim.VirtualMachine | None, port_groups: set[str] | None = None) -> StatusList:
        """
        Checks a VM's power state and required network connections.
        :param name: Expected virtual machine name.
        :param vm: Existing ESXi VM or None.
        :param port_groups: Required port groups, if any.
        :return: Virtual machine health-check results.
        :raises RuntimeError: If ESXi network adapters cannot be inspected.
        """
        results = StatusList()
        if vm is None:
            results.add(Status.missing("ESXi VM", f"{name} does not exist."))
            return results
        power = getattr(getattr(vm, "runtime", None), "powerState", None)
        if power == "poweredOn":
            results.add(Status.ok("ESXi VM", f"{name} is powered on."))
        else:
            results.add(Status.fault("ESXi VM", f"{name} is not powered on ({power or 'unknown'})."))
        if port_groups is not None:
            attached = {self.connection.get_nic_port_group(nic) for nic in self.connection.get_virtual_machine_nics(vm)}
            for group in sorted(port_groups - attached):
                results.add(Status.missing("ESXi VM", f"{name}: network adapter for {group} missing."))
            if port_groups <= attached:
                results.add(Status.ok("ESXi VM", f"{name}: required port groups are connected."))
        return results

    def _check_gns3_adapters(self, vm: vim.VirtualMachine | None) -> StatusList:
        """
        Checks the GNS3 VM's management and trunk adapters.
        :param vm: Existing GNS3 host VM or None.
        :return: GNS3 host adapter health-check results.
        :raises RuntimeError: If ESXi network adapters cannot be inspected.
        """
        results = StatusList()
        if vm is None:
            results.add(Status.missing("GNS3 VM", f"{Settings.ESXI.GNS3_VM_NAME} does not exist."))
            return results
        adapters = self.connection.get_virtual_machine_nics(vm)
        expected = (Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP)
        for index, group in enumerate(expected, 1):
            nic = next(
                (nic for nic in adapters if (self.connection.get_nic_label(nic) or "").endswith(f" {index}")), None
            )
            if nic is None:
                results.add(Status.missing("GNS3 VM", f"Adapter {index} is missing."))
                continue
            actual = self.connection.get_nic_port_group(nic)
            if actual != group:
                results.add(Status.fault("GNS3 VM", f"Adapter {index}: {actual or 'unassigned'}; expected {group}."))
            elif getattr(getattr(nic, "connectable", None), "startConnected", True) is False:
                results.add(Status.fault("GNS3 VM", f"Adapter {index} does not connect at startup."))
            else:
                results.add(Status.ok("GNS3 VM", f"Adapter {index} uses {group}."))
        return results

    def _check_port_groups(self, required: dict[str, int], groups: dict[str, Any]) -> StatusList:
        """
        Checks the required port groups' VLANs and switches.
        :param required: Required port-group names and VLAN IDs.
        :param groups: Existing port-group inventory.
        :return: Port-group health-check results.
        """
        results = StatusList()
        for name, vlan_id in sorted(required.items()):
            group = groups.get(name)
            if group is None:
                results.add(Status.missing("ESXi port group", f"{name} does not exist."))
                continue
            actual_vlan = group.spec.vlanId
            if actual_vlan != vlan_id:
                results.add(Status.fault("ESXi port group", f"{name}: VLAN {actual_vlan}; expected {vlan_id}."))
            else:
                results.add(Status.ok("ESXi port group", f"{name}: VLAN {vlan_id}."))
            if name != Settings.ESXI.MANAGEMENT_PORT_GROUP and group.spec.vswitchName != Settings.ESXI.VIRTUAL_SWITCH:
                results.add(Status.fault("ESXi port group", f"{name} is not on {Settings.ESXI.VIRTUAL_SWITCH}."))
        return results

    def check_esxi_setup(self) -> StatusList:
        """
        Checks the ESXi infrastructure required for deployment.
        :return: Deployment prerequisite health-check results.
        :raises RuntimeError: If the ESXi inventory cannot be inspected.
        """
        results = StatusList()
        datastore = self.connection.get_esxi_object(vim.Datastore, Settings.ESXI.DATASTORE)
        if datastore is None:
            results.add(Status.missing("Datastore", f"{Settings.ESXI.DATASTORE} does not exist."))
        else:
            summary = getattr(datastore, "summary", None)
            if summary is None or getattr(summary, "accessible", None) is False:
                results.add(Status.fault("Datastore", f"{Settings.ESXI.DATASTORE} is not accessible."))
            else:
                free_space = getattr(summary, "freeSpace", None)
                if free_space is None:
                    results.add(Status.info("Datastore", "Free space is unavailable."))
                else:
                    results.add(
                        Status.info("Datastore", f"{Settings.ESXI.DATASTORE}: {free_space / 1024**3:.1f} GiB free.")
                    )

        management = self.connection.get_virtual_switch("vSwitch0")
        results.extend(self._check_switch("vSwitch0", management))
        if management is not None:
            if not (getattr(management, "pnic", None) or []):
                results.add(Status.fault("ESXi switch", "vSwitch0 has no physical uplink."))
            else:
                results.add(Status.ok("ESXi switch", "vSwitch0 has a physical uplink."))
        managed = self.connection.get_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
        results.extend(self._check_switch(Settings.ESXI.VIRTUAL_SWITCH, managed, security=True))
        groups = self.connection.get_all_port_groups()
        if Settings.ESXI.MANAGEMENT_PORT_GROUP not in groups:
            results.add(
                Status.missing(
                    "ESXi port group", f"Management port group {Settings.ESXI.MANAGEMENT_PORT_GROUP} does not exist."
                )
            )
        results.extend(self._check_port_groups({Settings.ESXI.TRUNK_PORT_GROUP: 4095}, groups))
        gns3_vm = self.connection.get_virtual_machine(Settings.ESXI.GNS3_VM_NAME)
        results.extend(self._check_vm(Settings.ESXI.GNS3_VM_NAME, gns3_vm))
        results.extend(self._check_gns3_adapters(gns3_vm))
        return results

    def is_graph_esxi_sided_deployed(self, graph: Graph, state: TopologyState | None = None) -> StatusList:
        """
        Checks ESXi resources against the desired topology.
        :param graph: Expected topology.
        :param state: Previously inspected infrastructure, if available.
        :return: ESXi topology health-check results.
        :raises RuntimeError: If the ESXi inventory cannot be inspected.
        """
        if state is None:
            state = TopologyState()
            state.get_topology_state(graph, self.connection, None)
        results = self._check_switch(Settings.ESXI.VIRTUAL_SWITCH, state.virtual_switch, security=True)
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue
            ports = {interface.vlan.name for interface in node.interfaces.values() if interface.vlan is not None}
            results.extend(self._check_vm(node.name, state.virtual_machines.get(node.name), ports))
        required = TopologyChanges._get_required_port_groups(graph)
        results.extend(self._check_port_groups(required, state.port_groups))
        return results

    def list_port_groups(self) -> list[tuple[str, int, str]]:
        """Returns the configured ESXi port groups."""
        return sorted(
            (name, group.spec.vlanId, group.spec.vswitchName)
            for name, group in self.connection.get_all_port_groups().items()
        )

    def find_orphans(self, graph: Graph, state: TopologyState | None = None) -> StatusList:
        """
        Reports untracked virtual machines attached to the lab switch.
        :param graph: Expected topology.
        :param state: Previously inspected infrastructure, if available.
        :return: Possible orphan health-check results.
        :raises RuntimeError: If the ESXi inventory cannot be inspected.
        """
        if state is None:
            state = TopologyState()
            state.get_topology_state(graph, self.connection, None)
        results = StatusList()
        lab_groups = {
            name for name, group in state.port_groups.items() if group.spec.vswitchName == Settings.ESXI.VIRTUAL_SWITCH
        }
        protected = set(graph.nodes) | set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ()) | {Settings.ESXI.GNS3_VM_NAME}
        for vm in self.connection.get_esxi_object(vim.VirtualMachine, get_all=True) or []:
            if self.connection.compare_regular_to_esxi_name(protected, vm.name):
                continue
            attached = {self.connection.get_nic_port_group(nic) for nic in self.connection.get_virtual_machine_nics(vm)}
            if attached & lab_groups:
                results.add(
                    Status.fault(
                        "Possible orphan", f"ESXi VM {vm.name} is attached to the lab switch but not in the topology."
                    )
                )
        return results
