from __future__ import annotations

import json
import re
from typing import Any

from pyVmomi import vim

from src.connections import ESXiConnection, GNS3Connection
from src.graph import Environment, Graph
from src.graph.blocks import GenericNode
from src.orchestrator import ESXiOrchestrator, GNS3Orchestrator
from src.orchestrator.gns3 import GNS3VMInterfaceSetup
from src.settings import Settings


class TopologyState:
    """Contains the existing infrastructure relevant to a graph."""

    def __init__(self) -> None:
        """Initializes the resources of one topology inspection."""
        self.virtual_switch: vim.host.VirtualSwitch | None = None
        self.port_groups: dict[str, Any] = {}
        self.virtual_machines: dict[str, vim.VirtualMachine | None] = {}
        self.gns3_nodes: dict[str, dict[str, Any]] = {}
        self.gns3_links: list[dict[str, Any]] = []
        self.conflicts: list[str] = []

    def get_topology_state(self, graph: Graph, esxi_conn: ESXiConnection, gns3_conn: GNS3Connection) -> None:
        """
        Reads ESXi and GNS3 resources relevant to the graph.
        :param esxi_conn: ESXi API connection.
        :param gns3_conn: GNS3 API connection.
        :param graph: Graph identifying the relevant resources.

        """
        base = gns3_conn.get_project_url()

        for item in gns3_conn.get(f"{base}/nodes"):
            if item["name"] not in graph.nodes:
                continue
            if item["name"] in self.gns3_nodes:
                self.conflicts.append(f"Duplicate GNS3 node: {item['name']}")
                continue
            self.gns3_nodes[item["name"]] = item
        for node in graph.nodes.values():
            node_gns3_info = self.gns3_nodes.get(node.name)
            if node_gns3_info is None:
                continue
            node.node_gns3_info = node_gns3_info

        self.gns3_links = gns3_conn.get(f"{base}/links")
        self.virtual_switch = esxi_conn.get_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
        self.port_groups = esxi_conn.get_all_port_groups()

        esxi_vm_names = {node.name for node in graph.nodes.values() if node.env == Environment.ON_ESXI}
        esxi_vm_names.add(Settings.ESXI.GNS3_VM_NAME)
        self.virtual_machines = {name: esxi_conn.get_virtual_machine(name) for name in esxi_vm_names}


class TopologyChanges:
    """Contains required additions, changes, deletions and conflicts."""

    def __init__(self, esxi_orchestrator: ESXiOrchestrator, gns3_orchestrator: GNS3Orchestrator):
        """
        Initializes the action pools for a topology comparison.
        :param esxi_orchestrator: ESXi resource orchestrator.
        :param gns3_orchestrator: GNS3 resource orchestrator.
        """
        self.esxi_orchestrator = esxi_orchestrator
        self.gns3_orchestrator = gns3_orchestrator
        self.to_add: dict[str, list[Any]] = {
            name: [] for name in ("virtual_switch", "port_group", "esxi_vm", "esxi_nic", "gns3_node", "gns3_link")
        }
        self.to_change: dict[str, list[Any]] = {
            name: [] for name in ("virtual_switch", "port_group", "gns3_vm_adapter", "esxi_nic", "gns3_node", "vlans")
        }
        self.to_delete: dict[str, list[Any]] = {name: [] for name in ("port_group", "gns3_node", "gns3_link")}
        self.conflicts: list[str] = []
        self.gns3_vlan_setup: GNS3VMInterfaceSetup | None = None

    @property
    def has_changes(self) -> bool:
        """:return: Whether the infrastructure requires any changes."""
        return any(items for pool in (self.to_add, self.to_change, self.to_delete) for items in pool.values())

    def init_topology_changes(self, graph: Graph, state: TopologyState) -> None:
        """
        Collects the required topology changes without applying them.
        :param graph: Desired topology.
        :param state: Current infrastructure.

        """
        self.conflicts = list(state.conflicts)
        self._compare_gns3_vm(state)
        self._compare_virtual_machines(graph, state)
        self._compare_port_groups(graph, state)
        self._compare_nodes(graph, state)
        self._compare_vlan_interfaces(graph)
        self._compare_connections(graph, state)

    def _compare_port_groups(self, graph: Graph, state: TopologyState) -> None:
        """
        Compares the managed ESXi switch and its port groups.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        """
        switch_name = Settings.ESXI.VIRTUAL_SWITCH
        if switch_name in (Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ()):
            self.conflicts.append(f"Virtual switch {switch_name} is protected")
            return

        if state.virtual_switch is None:
            self.to_add["virtual_switch"].append(switch_name)
        else:
            security = getattr(getattr(state.virtual_switch.spec, "policy", None), "security", None)
            if security is None or any(
                getattr(security, name, None) is not True
                for name in ("allowPromiscuous", "forgedTransmits", "macChanges")
            ):
                self.to_change["virtual_switch"].append(switch_name)

        required = self._resolve_vlan_ids(graph, state.port_groups)
        ignored = Settings.ESXI.IGNORE_PORT_GROUPS or ()
        for name, vlan_id in required.items():
            current = state.port_groups.get(name)
            if current is None:
                if name in ignored:
                    self.conflicts.append(f"Protected port group {name} is missing")
                else:
                    self.to_add["port_group"].append((name, vlan_id))
            elif name in ignored:
                if int(current.spec.vlanId) != vlan_id:
                    self.conflicts.append(
                        f"Protected port group {name} has VLAN ID {current.spec.vlanId}, expected {vlan_id}"
                    )
            elif current.spec.vswitchName != switch_name or int(current.spec.vlanId) != vlan_id:
                self.to_change["port_group"].append((name, vlan_id))

        for name, group in state.port_groups.items():
            if group.spec.vswitchName == switch_name and name not in required and name not in ignored:
                self.to_delete["port_group"].append(name)

        if not self.to_delete["port_group"]:
            return
        planned_adapters = {
            (vm.name, nic.key) for pool in ("gns3_vm_adapter", "esxi_nic") for vm, nic, _ in self.to_change[pool]
        }
        esxi = self.esxi_orchestrator.esxi_connection
        deleting = set(self.to_delete["port_group"])
        for vm in esxi.get_esxi_object(vim.VirtualMachine, get_all=True) or []:
            still_used = {
                esxi.get_nic_port_group(nic)
                for nic in esxi.get_virtual_machine_nics(vm)
                if (vm.name, nic.key) not in planned_adapters
            }
            for group in sorted(deleting & still_used):
                self.conflicts.append(f"Cannot delete port group {group}: used by VM {vm.name}")

    def _compare_gns3_vm(self, state: TopologyState) -> None:
        """
        Checks the GNS3 virtual machine's network connections.
        :param state: Current infrastructure.
        """
        vm = state.virtual_machines.get(Settings.ESXI.GNS3_VM_NAME)
        if vm is None:
            self.conflicts.append(f"GNS3 VM {Settings.ESXI.GNS3_VM_NAME} is missing")
            return
        devices = vm.config.hardware.device
        expected = (("1", Settings.ESXI.MANAGEMENT_PORT_GROUP), ("2", Settings.ESXI.TRUNK_PORT_GROUP))
        for suffix, group in expected:
            nic = next(
                (
                    device
                    for device in devices
                    if isinstance(device, vim.vm.device.VirtualEthernetCard)
                    and getattr(device.deviceInfo, "label", "").endswith(suffix)
                ),
                None,
            )
            if nic is None:
                self.conflicts.append(f"GNS3 VM network adapter {suffix} is missing")
            elif (
                isinstance(nic, vim.vm.device.VirtualEthernetCard)
                and self.esxi_orchestrator.esxi_connection.get_nic_port_group(nic) != group
                or not getattr(nic.connectable, "startConnected", False)
            ):
                self.to_change["gns3_vm_adapter"].append((vm, nic, group))

    def _compare_virtual_machines(self, graph: Graph, state: TopologyState) -> None:
        """
        Checks graph-owned ESXi virtual machines and their network adapters.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        """
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue
            vm = state.virtual_machines.get(node.name)
            if vm is None:
                self.to_add["esxi_vm"].append(node)
            elif not ESXiConnection.compare_regular_to_esxi_name(node.name, vm.name):
                self.conflicts.append(f"Ambiguous ESXi VM name {node.name}: found {vm.name}")
            else:
                self._compare_virtual_machine_adapters(node, vm)

    def _compare_virtual_machine_adapters(self, node: GenericNode, vm: vim.VirtualMachine) -> None:
        """
        Checks the network adapter positions and port groups of a VM.
        :param node: Graph node represented by the ESXi VM.
        :param vm: Existing ESXi VM.
        """
        esxi = self.esxi_orchestrator.esxi_connection
        nics = esxi.get_virtual_machine_nics(vm)
        by_label = {esxi.get_nic_label(nic).lower(): nic for nic in nics if esxi.get_nic_label(nic)}
        if len(by_label) != len(nics):
            self.conflicts.append(f"{node.name}: ambiguous ESXi adapter labels")
            return
        indices = set()
        for label in by_label:
            match = re.fullmatch(r"network adapter (\d+)", label)
            if match is None:
                self.conflicts.append(f"{node.name}: unsupported ESXi adapter naming")
                return
            indices.add(int(match.group(1)))

        missing = []
        for index, group in enumerate(self.esxi_orchestrator._create_mapped_network(node).values(), 1):
            nic = by_label.get(f"network adapter {index}")
            if nic is None:
                if any(existing_index > index for existing_index in indices):
                    self.conflicts.append(f"{node.name}: missing ESXi NIC position {index}")
                else:
                    missing.append(group)
            elif esxi.get_nic_port_group(nic) != group or not getattr(nic.connectable, "startConnected", False):
                self.to_change["esxi_nic"].append((vm, nic, group))
        if missing:
            self.to_add["esxi_nic"].append((vm, missing))

    def _compare_nodes(self, graph: Graph, state: TopologyState) -> None:
        """
        Checks the types, templates and interfaces of graph-owned GNS3 nodes.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        :raises RuntimeError: If GNS3 template information cannot be retrieved.
        :raises TimeoutError: If a GNS3 request times out.
        """
        connection = self.gns3_orchestrator.gns3_connection
        templates = {}
        for node in graph.nodes.values():
            current = state.gns3_nodes.get(node.name)
            if node.env == Environment.ON_ESXI:
                try:
                    connection._create_ports_mapping(node)
                except (ValueError, RuntimeError) as error:
                    self.conflicts.append(str(error))
                    continue
                if current is None:
                    self.to_add["gns3_node"].append(node)
                elif current.get("node_type") != "cloud":
                    self._replace_node(node)
                else:
                    self._compare_cloud_interfaces(node, current)
                continue

            if node.env != Environment.ON_GNS3:
                self.conflicts.append(f"{node.name}: unsupported execution environment")
                continue
            if node.image not in templates:
                try:
                    templates[node.image] = connection._get_template(node.image)
                except (KeyError, LookupError, ValueError) as error:
                    self.conflicts.append(f"{node.name}: GNS3 template not found ({error})")
                    continue
            if current is None:
                self.to_add["gns3_node"].append(node)
                continue
            template = templates[node.image]
            if not template["builtin"] and current.get("template_id") is None:
                self.conflicts.append(f"{node.name}: GNS3 template ID cannot be verified")
            elif current.get("node_type") != template["template_type"] or (
                not template["builtin"] and current["template_id"] != template["template_id"]
            ):
                self._replace_node(node)
            else:
                self._compare_node_interfaces(node, current)

    def _replace_node(self, node: GenericNode) -> None:
        """
        Schedules replacement of one graph-owned GNS3 node.
        :param node: Node with incompatible type or template.
        """
        self.to_delete["gns3_node"].append(node)
        self.to_add["gns3_node"].append(node)

    def _compare_cloud_interfaces(self, node: GenericNode, current: dict[str, Any]) -> None:
        """
        Schedules additions of missing Cloud ports without altering existing ones.
        :param node: ESXi-backed node to reconcile.
        :param current: Existing GNS3 node information.
        :raises RuntimeError: If existing Cloud ports cannot be preserved.
        """
        connection = self.gns3_orchestrator.gns3_connection
        expected = connection._create_ports_mapping(node, connected_only=True)
        try:
            mapping = connection._missing_cloud_ports_mapping(current, expected)
        except RuntimeError as error:
            self.conflicts.append(f"{node.name}: {error}")
            return
        if mapping is not None:
            properties = current.get("properties") or {}
            self.to_change["gns3_node"].append((node, {"properties": {**properties, "ports_mapping": mapping}}))

    def _compare_node_interfaces(self, node: GenericNode, current: dict[str, Any]) -> None:
        """Checks available GNS3 adapters and schedules supported extensions.

        :param node: Desired GNS3 node.
        :param current: Existing GNS3 node data.
        """
        ports = current.get("ports") or []
        available = {port["name"].lower() for port in ports}
        missing = [name for name in node.interfaces if name.lower() not in available]
        if not missing:
            return
        if current.get("node_type") != "qemu" or current.get("status") != "stopped":
            self.conflicts.append(f"{node.name}: missing interfaces {missing} (unsupported or running node)")
            return
        prototype = next((match for port in ports if (match := re.fullmatch(r"(\D+)(\d+)", port["name"]))), None)
        wanted = [re.fullmatch(r"(\D+)(\d+)", name) for name in missing]
        if not prototype or any(not match or match.group(1).lower() != prototype.group(1).lower() for match in wanted):
            self.conflicts.append(f"{node.name}: cannot safely extend interfaces {missing}")
            return
        properties = current.get("properties") or {}
        count = max(int(properties.get("adapters") or len(ports)), max(int(match.group(2)) for match in wanted) + 1)
        self.to_change["gns3_node"].append((node, {"properties": {**properties, "adapters": count}}))

    def _compare_vlan_interfaces(self, graph: Graph) -> None:
        """
        Checks required VLAN subinterfaces on the GNS3 VM.
        :param graph: Desired topology.
        """
        setup = GNS3VMInterfaceSetup(self.gns3_orchestrator.gns3_ssh_connection, Settings.GNS3.PARENT_INTERFACE)
        try:
            setup.initialize_yaml(graph)
        except (RuntimeError, ValueError) as error:
            self.conflicts.append(f"GNS3 VLAN configuration: {error}")
            return
        self.gns3_vlan_setup = setup
        existing = setup._get_existing_subinterfaces()
        names = {item["ifname"].split("@")[0] for item in json.loads(setup._run_command("ip -j link show"))}
        for name in setup._requested_vlan_names:
            if name not in existing and name in names:
                self.conflicts.append(f"VLAN interface name {name} is already in use")
            elif name not in existing or existing[name] != (setup.vlans[name], True):
                self.to_change["vlans"].append(name)
        previous = setup._run_command(f"sudo sh -c 'if [ -f {setup.NETPLAN_FILE} ]; then cat {setup.NETPLAN_FILE}; fi'")
        if previous != setup.netplan_yaml and not self.to_change["vlans"]:
            self.to_change["vlans"].append("netplan")

    def _compare_connections(self, graph: Graph, state: TopologyState) -> None:
        """
        Checks graph connections while preserving links to unrelated nodes.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        """
        by_port: dict[tuple[str, int, int], dict[str, Any]] = {}
        existing_pairs: set[frozenset] = set()
        for link in state.gns3_links:
            endpoints = frozenset(self._get_link_endpoints(link))
            existing_pairs.add(endpoints)
            for port in endpoints:
                if port in by_port:
                    self.conflicts.append(f"GNS3 port appears in multiple links: {port}")
                by_port[port] = link

        nodes = {
            node.node_gns3_info["node_id"]: node for node in graph.nodes.values() if node.node_gns3_info is not None
        }
        replacing = {node.name for node in self.to_delete["gns3_node"]}
        replacing_ids = {node.node_gns3_info["node_id"] for node in self.to_delete["gns3_node"]}
        scheduled_links = self._check_node_replacements(state.gns3_links, nodes, replacing_ids)
        requested_ports: set[tuple[str, int, int]] = set()
        updates = {node.name for node, _ in self.to_change["gns3_node"]}
        for node, interface, neighbour, reverse in self._get_expected_connections(graph):
            ports = []
            for current_node, current_interface in ((node, interface), (neighbour, reverse)):
                port = self._get_node_port(
                    current_node, current_interface, replacing, updates, self.gns3_orchestrator.gns3_connection
                )
                if port is None:
                    continue
                if port in requested_ports:
                    self.conflicts.append(f"GNS3 port assigned twice: {current_node.name}.{current_interface.name}")
                requested_ports.add(port)
                ports.append(port)

            if len(ports) == 2 and frozenset(ports) in existing_pairs:
                continue
            self.to_add["gns3_link"].append((node, neighbour))
            for port in ports:
                current_link = by_port.get(port)
                if current_link is None or current_link["link_id"] in scheduled_links:
                    continue
                linked_nodes = {end["node_id"] for end in current_link["nodes"]}
                if linked_nodes.intersection(replacing_ids):
                    continue
                if not linked_nodes.issubset(nodes):
                    self.conflicts.append(f"GNS3 port occupied by orphan: {port}")
                else:
                    self.to_delete["gns3_link"].append(current_link["link_id"])
                    scheduled_links.add(current_link["link_id"])

        self._compare_unconnected_interfaces(graph, by_port, nodes, replacing, replacing_ids, scheduled_links)

    @staticmethod
    def _get_link_endpoints(link: dict[str, Any]) -> list[tuple[str, int, int]]:
        """
        Returns the ports connected by a GNS3 link.
        :param link: GNS3 link information.
        :return: Node and adapter coordinates for each endpoint.
        """
        return [(end["node_id"], end["adapter_number"], end["port_number"]) for end in link["nodes"]]

    def _compare_unconnected_interfaces(
        self,
        graph: Graph,
        by_port: dict,
        nodes: dict,
        replacing: set[str],
        replacing_ids: set[str],
        scheduled: set[str],
    ) -> None:
        """
        Checks unused graph interfaces for obsolete graph-owned links.
        :param graph: Desired topology.
        :param by_port: Existing links indexed by GNS3 port.
        :param nodes: Existing nodes represented by the graph.
        :param replacing: Node names scheduled for replacement.
        :param replacing_ids: Existing node IDs scheduled for replacement.
        :param scheduled: Link IDs already scheduled for deletion.
        """
        for node in graph.nodes.values():
            node_gns3_info = node.node_gns3_info
            if node_gns3_info is None or node.name in replacing:
                continue
            for interface in node.interfaces.values():
                if interface.neighbour is not None:
                    continue
                try:
                    adapter = self.gns3_orchestrator.gns3_connection._get_adapter(node_gns3_info, interface)
                except ValueError:
                    continue
                port = (node.node_gns3_info["node_id"], adapter["adapter_number"], adapter["port_number"])
                link = by_port.get(port)
                if link is None or link["link_id"] in scheduled:
                    continue
                linked_ids = {end["node_id"] for end in link["nodes"]}
                if linked_ids.issubset(nodes) and not linked_ids.intersection(replacing_ids):
                    self.to_delete["gns3_link"].append(link["link_id"])
                    scheduled.add(link["link_id"])

    @staticmethod
    def _get_required_port_groups(graph: Graph) -> dict[str, int]:
        """
        Returns the port groups required by a graph.
        :param graph: Desired topology.
        :return: Port-group names mapped to VLAN IDs.
        """
        groups = {}
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is not None:
                    groups[vlan.name] = vlan.id
        groups[Settings.ESXI.TRUNK_PORT_GROUP] = 4095
        groups[Settings.ESXI.MANAGEMENT_PORT_GROUP] = 0
        return groups

    def _resolve_vlan_ids(self, graph: Graph, existing: dict[str, Any]) -> dict[str, int]:
        """
        Reserves VLAN IDs without colliding with unrelated ESXi networks.
        :param graph: Desired topology.
        :param existing: Existing ESXi port groups.
        :return: Required port groups and VLAN IDs.
        """
        requested = self._get_required_port_groups(graph)
        used = {
            int(group.spec.vlanId)
            for name, group in existing.items()
            if name not in requested and 2 <= int(group.spec.vlanId) <= 4094
        }
        allocated: dict[str, int] = {}
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None:
                    continue
                if vlan.name not in allocated:
                    vlan_id = vlan.id
                    if vlan_id in used or not 2 <= vlan_id <= 4094:
                        vlan_id = next((value for value in range(2, 4095) if value not in used), None)
                        if vlan_id is None:
                            self.conflicts.append("No free VLAN IDs")
                            return {}
                    allocated[vlan.name] = vlan_id
                    used.add(vlan_id)
                vlan._vlan_id = allocated[vlan.name]
        return self._get_required_port_groups(graph)

    def _check_node_replacements(
        self, links: list[dict[str, Any]], nodes: dict[str, GenericNode], replacing_ids: set[str]
    ) -> set[str]:
        """
        Schedules obsolete links of replaced graph nodes without affecting unrelated nodes.
        :param links: Existing GNS3 links.
        :param nodes: Existing nodes represented by the graph.
        :param replacing_ids: Existing node IDs scheduled for replacement.
        :return: Link IDs scheduled for deletion.
        """
        scheduled: set[str] = set()
        for link in links:
            linked_ids = {end["node_id"] for end in link["nodes"]}
            if not linked_ids.intersection(replacing_ids):
                continue
            if not linked_ids.issubset(nodes):
                self.conflicts.append(f"Cannot replace a graph node connected to an orphan (link {link['link_id']})")
                continue
            self.to_delete["gns3_link"].append(link["link_id"])
            scheduled.add(link["link_id"])
        return scheduled

    def _get_expected_connections(self, graph: Graph) -> list[tuple[Any, ...]]:
        """
        Collects valid, unique graph connections.
        :param graph: Desired topology.
        :return: Connected graph node/interface pairs.
        """
        expected = []
        seen = set()
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                neighbour = interface.neighbour
                if neighbour is None or neighbour.name not in graph.nodes:
                    continue
                reverse = neighbour.get_interface(node)
                if reverse is None or reverse.neighbour is not node:
                    self.conflicts.append(f"{node.name}.{interface.name}: missing reverse connection")
                    continue
                key = frozenset(((node.name, interface.name), (neighbour.name, reverse.name)))
                if key in seen:
                    continue
                seen.add(key)
                if node.get_interface(neighbour) is not interface or neighbour.get_interface(node) is not reverse:
                    self.conflicts.append(f"Ambiguous parallel links between {node.name} and {neighbour.name}")
                else:
                    expected.append((node, interface, neighbour, reverse))
        return expected

    def _get_node_port(
        self,
        node: GenericNode,
        interface: Any,
        replacing: set[str],
        updating: set[str],
        gns3_connection: GNS3Connection,
    ) -> tuple[str, int, int] | None:
        """
        Resolves a graph interface to its existing GNS3 adapter.
        :param node: Graph node.
        :param interface: Interface on the graph node.
        :param replacing: Node names scheduled for replacement.
        :param updating: Node names with pending interface changes.
        :return: Existing GNS3 port, if resolvable.
        """
        node_gns3_info = node.node_gns3_info
        if node_gns3_info is None or node.name in replacing:
            return None
        try:
            adapter = gns3_connection._get_adapter(node_gns3_info, interface)
        except ValueError:
            if node.name not in updating:
                self.conflicts.append(f"{node.name}.{interface.name}: missing GNS3 adapter")
            return None
        return (node.node_gns3_info["node_id"], adapter["adapter_number"], adapter["port_number"])
