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
        self.gns3_all_nodes: list[dict[str, Any]] = []
        self.gns3_links: list[dict[str, Any]] = []
        self.gns3_projects: list[dict[str, Any]] = []
        self.gns3_project_nodes: dict[str, list[dict[str, Any]]] = {}
        self.gns3_project_links: dict[str, list[dict[str, Any]]] = {}
        self.conflicts: list[str] = []

    def get_topology_state(self, graph: Graph, esxi_conn: ESXiConnection, gns3_conn: GNS3Connection | None) -> None:
        """
        Reads ESXi and optional GNS3 resources relevant to a graph.
        :param graph: Topology defining the required resources.
        :param esxi_conn: Existing ESXi connection.
        :param gns3_conn: Optional read-only GNS3 project connection.
        :raises RuntimeError: If an infrastructure inventory cannot be retrieved.
        """
        if gns3_conn is not None:
            self.get_gns3_state(graph, gns3_conn)
        self.virtual_switch = esxi_conn.get_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
        self.port_groups = esxi_conn.get_all_port_groups()
        esxi_vm_names = {node.name for node in graph.nodes.values() if node.env == Environment.ON_ESXI}
        esxi_vm_names.add(Settings.ESXI.GNS3_VM_NAME)
        self.virtual_machines = {name: esxi_conn.get_virtual_machine(name) for name in esxi_vm_names}

    def get_gns3_state(self, graph: Graph, gns3_conn: GNS3Connection) -> None:
        """
        Reads the configured GNS3 project's nodes and links.
        :param graph: Topology identifying the expected nodes.
        :param gns3_conn: Read-only GNS3 project connection.
        :raises RuntimeError: If the GNS3 inventory cannot be retrieved.
        :raises TimeoutError: If the GNS3 API does not respond.
        :raises requests.exceptions.HTTPError: If a GNS3 inventory request fails.
        """
        self.gns3_nodes = {}
        self.gns3_all_nodes = []
        self.gns3_links = []
        self.conflicts = [item for item in self.conflicts if not item.startswith("Duplicate GNS3 node: ")]
        if gns3_conn.project_gns3_info is not None:
            project_id = gns3_conn.project_gns3_info["project_id"]
            self.gns3_all_nodes = gns3_conn.get_project_nodes(project_id)
            self.gns3_links = gns3_conn.get_project_links(project_id)
            for item in self.gns3_all_nodes:
                if item["name"] not in graph.nodes:
                    continue
                if item["name"] in self.gns3_nodes:
                    self.conflicts.append(f"Duplicate GNS3 node: {item['name']}")
                else:
                    self.gns3_nodes[item["name"]] = item
        for node in graph.nodes.values():
            node.node_gns3_info = self.gns3_nodes.get(node.name)

    def get_gns3_projects_state(self, gns3_conn: GNS3Connection) -> None:
        """
        Reads GNS3 nodes and links in every project for safe cleanup planning.
        :param gns3_conn: Read-only GNS3 connection.
        :raises TypeError: If a project or link inventory is malformed.
        :raises RuntimeError: If a project cannot be inspected.
        :raises TimeoutError: If GNS3 does not respond in time.
        :raises requests.exceptions.HTTPError: If an inventory request fails.
        """
        self.gns3_projects = gns3_conn.get_projects()
        self.gns3_project_nodes = {}
        self.gns3_project_links = {}
        current = gns3_conn.project_gns3_info or {}
        for project in self.gns3_projects:
            project_id = project.get("project_id")
            if not isinstance(project_id, str) or not isinstance(project.get("name"), str):
                raise TypeError(f"Invalid GNS3 project information: {project!r}")
            if project_id == current.get("project_id"):
                self.gns3_project_nodes[project_id] = self.gns3_all_nodes
                self.gns3_project_links[project_id] = self.gns3_links
            else:
                self.gns3_project_nodes[project_id] = gns3_conn.get_project_nodes(project_id)
                self.gns3_project_links[project_id] = gns3_conn.get_project_links(project_id)


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
        self.to_delete: dict[str, list[Any]] = {
            name: []
            for name in ("virtual_switch", "port_group", "gns3_node", "gns3_link", "gns3_project", "esxi_vm", "vlans")
        }
        self.to_ok: dict[str, list[Any]] = {
            name: [] for name in ("virtual_switch", "port_group", "esxi_vm", "gns3_node", "gns3_link", "vlans")
        }
        self.conflicts: list[str] = []
        self.gns3_vlan_setup: GNS3VMInterfaceSetup | None = None
        self.gns3_positions: dict[str, tuple[int, int]] = {}
        self.gns3_project_snapshots: dict[str, tuple[set[str], set[str]]] = {}
        self.cleanup_project_id: str | None = None
        self.cleanup_project_snapshot: tuple[set[str], set[str]] | None = None

    @property
    def has_changes(self) -> bool:
        """:return: Whether the infrastructure requires any changes."""
        return any(items for pool in (self.to_add, self.to_change, self.to_delete) for items in pool.values())

    def init_topology_changes(self, graph: Graph, state: TopologyState) -> None:
        """
        Collects topology changes with positions centered on the GNS3 canvas.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        :raises RuntimeError: If ESXi or GNS3 inventory cannot be inspected.
        :raises ValueError: If the topology layout cannot be calculated.
        """
        self.conflicts = list(state.conflicts)
        positions = graph.get_node_positions()
        if positions:
            xs, ys = zip(*positions.values(), strict=True)
            center_x = round((min(xs) + max(xs)) / 2)
            center_y = round((min(ys) + max(ys)) / 2)
            self.gns3_positions = {name: (x - center_x, y - center_y) for name, (x, y) in positions.items()}
        else:
            self.gns3_positions = {}
        recreate = Settings.NEW
        self._compare_gns3_vm(state)
        self._compare_virtual_machines(graph, state, recreate=recreate)
        self._compare_port_groups(graph, state, preserve_unused=recreate)
        self._compare_nodes(graph, state, recreate=recreate)
        self._compare_vlan_interfaces(graph)
        self._compare_connections(graph, state)
        self._compare_node_positions(graph, state)
        self._collect_unchanged(graph, state)

    def _collect_unchanged(self, graph: Graph, state: TopologyState) -> None:
        """
        Records graph components that already match their requested state.
        :param graph: Desired topology.
        :param state: Inspected infrastructure.
        """
        if state.virtual_switch is not None and not self.to_change["virtual_switch"]:
            self.to_ok["virtual_switch"].append(Settings.ESXI.VIRTUAL_SWITCH)
        changing_groups = {name for name, _ in self.to_change["port_group"]}
        adding_groups = {name for name, _ in self.to_add["port_group"]}
        for name in self._get_required_port_groups(graph):
            if name in state.port_groups and name not in changing_groups | adding_groups:
                self.to_ok["port_group"].append(name)

        adding_vms = {node.name for node in self.to_add["esxi_vm"]}
        changing_vms = {vm.name for vm, *_ in self.to_change["esxi_nic"]}
        changing_vms.update(vm.name for vm, _ in self.to_add["esxi_nic"])
        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                vm = state.virtual_machines.get(node.name)
                if (
                    vm is not None
                    and node.name not in adding_vms | changing_vms
                    and ESXiConnection.compare_regular_to_esxi_name(node.name, vm.name)
                ):
                    self.to_ok["esxi_vm"].append(node.name)

        adding_nodes = {node.name for node in self.to_add["gns3_node"]}
        changing_nodes = {node.name for node, _ in self.to_change["gns3_node"]}
        for name in graph.nodes:
            if name in state.gns3_nodes and name not in adding_nodes | changing_nodes:
                self.to_ok["gns3_node"].append(name)

        deleting_links = set(self.to_delete["gns3_link"])
        graph_ids = {node["node_id"] for node in state.gns3_nodes.values()}
        for link in state.gns3_links:
            linked_ids = {end["node_id"] for end in link["nodes"]}
            if linked_ids.issubset(graph_ids) and link["link_id"] not in deleting_links:
                self.to_ok["gns3_link"].append(link["link_id"])
        if self.gns3_vlan_setup is not None:
            for name in self.gns3_vlan_setup._requested_vlan_names:
                if name not in self.to_change["vlans"] and "netplan" not in self.to_change["vlans"]:
                    self.to_ok["vlans"].append(name)

    def init_topology_destruction(self, graph: Graph, state: TopologyState) -> None:
        """
        Plans graph resource removal and cleanup of VLANs belonging to removed VMs.
        :param graph: Topology to remove.
        :param state: Current ESXi and GNS3 resources.
        :raises RuntimeError: If ESXi, GNS3 or VLAN inventory cannot be read.
        """
        from loguru import logger

        self.conflicts = list(state.conflicts)
        esxi = self.esxi_orchestrator.esxi_connection
        protected_vms = set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ())
        protected_vms.add(Settings.ESXI.GNS3_VM_NAME)
        for node in graph.nodes.values():
            if node.name == Settings.ESXI.GNS3_VM_NAME:
                logger.warning(f"Skipping protected GNS3 host node: {node.name}")
                continue
            if node.env == Environment.ON_ESXI and ESXiConnection.compare_regular_to_esxi_name(
                protected_vms, node.name
            ):
                logger.warning(f"Skipping protected ESXi VM and Cloud node: {node.name}")
                continue
            if node.name in state.gns3_nodes:
                self.to_delete["gns3_node"].append(node)
            if node.env != Environment.ON_ESXI:
                continue
            vm = state.virtual_machines.get(node.name)
            if vm is None:
                continue
            if not ESXiConnection.compare_regular_to_esxi_name(
                node.name, vm.name
            ) or ESXiConnection.compare_regular_to_esxi_name(protected_vms, vm.name):
                logger.warning(f"Skipping protected or ambiguous ESXi VM: {vm.name}")
                continue
            self.to_delete["esxi_vm"].append(vm)

        graph_node_ids = {node.node_gns3_info["node_id"] for node in self.to_delete["gns3_node"]}
        self.to_delete["gns3_link"] = [
            link["link_id"]
            for link in state.gns3_links
            if any(end["node_id"] in graph_node_ids for end in link["nodes"])
        ]

        protected_groups = set(Settings.ESXI.IGNORE_PORT_GROUPS or ())
        protected_groups.update((Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP))
        if Settings.ESXI.VIRTUAL_SWITCH not in (Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ()):
            for name in self._get_required_port_groups(graph):
                current = state.port_groups.get(name)
                if (
                    name not in protected_groups
                    and current is not None
                    and current.spec.vswitchName == Settings.ESXI.VIRTUAL_SWITCH
                ):
                    self.to_delete["port_group"].append(name)

        host = esxi.get_esxi_object(vim.HostSystem)
        if host is None and self.to_delete["port_group"]:
            raise RuntimeError("Cannot inspect ESXi VMkernel adapters before deleting port groups")
        vmkernel_groups = {nic.portgroup for nic in (host.config.network.vnic or [])} if host else set()
        for group in list(self.to_delete["port_group"]):
            if group in vmkernel_groups:
                logger.warning(f"Keeping port group {group}: used by an ESXi VMkernel adapter")
                self.to_delete["port_group"].remove(group)

        deleted_vm_names = {vm.name for vm in self.to_delete["esxi_vm"]}
        remaining_vm_groups: set[str] = set()
        for vm in esxi.get_esxi_object(vim.VirtualMachine, get_all=True) or []:
            if vm.name in deleted_vm_names:
                continue
            used = {esxi.get_nic_port_group(nic) for nic in esxi.get_virtual_machine_nics(vm)}
            remaining_vm_groups.update(name for name in used if name is not None)
            for group in sorted(set(self.to_delete["port_group"]) & used):
                logger.warning(f"Keeping port group {group}: still used by VM {vm.name}")
                self.to_delete["port_group"].remove(group)

        # VLANs remain owned by the selected graph even after their VM has been removed.
        selected_nodes = (
            node
            for node in graph.nodes.values()
            if node.env == Environment.ON_ESXI
            and not ESXiConnection.compare_regular_to_esxi_name(protected_vms, node.name)
            and (
                state.virtual_machines.get(node.name) is None
                or any(ESXiConnection.compare_regular_to_esxi_name(node.name, name) for name in deleted_vm_names)
            )
        )
        requested = {
            interface.vlan.name: interface.vlan.id
            for node in selected_nodes
            for interface in node.interfaces.values()
            if interface.vlan is not None
        }
        for name in requested:
            group = state.port_groups.get(name)
            if group is not None and group.spec.vswitchName == Settings.ESXI.VIRTUAL_SWITCH:
                requested[name] = int(group.spec.vlanId)
        for vm in self.to_delete["esxi_vm"]:
            for nic in esxi.get_virtual_machine_nics(vm):
                name = esxi.get_nic_port_group(nic)
                group = state.port_groups.get(name)
                if group is not None and name not in requested:
                    requested[name] = int(group.spec.vlanId)
        if not requested:
            return

        setup = GNS3VMInterfaceSetup(self.gns3_orchestrator.gns3_ssh_connection, Settings.GNS3.PARENT_INTERFACE)
        managed = setup.get_managed_vlan_names()
        running = setup._get_existing_subinterfaces()
        # A Cloud may advertise ports without using them. Protect only owned
        # interfaces and ports connected by links that will survive destruction.
        remaining_link_ports = {
            (endpoint["node_id"], endpoint["port_number"])
            for link in state.gns3_links
            if link["link_id"] not in self.to_delete["gns3_link"]
            for endpoint in link["nodes"]
        }
        remaining_cloud_vlans: set[str] = set()
        for cloud in state.gns3_all_nodes:
            if cloud.get("node_type") != "cloud" or cloud.get("node_id") in graph_node_ids:
                continue
            for port in (cloud.get("properties") or {}).get("ports_mapping") or []:
                if not isinstance(port, dict) or not isinstance(port.get("interface"), str):
                    continue
                interface = port["interface"]
                belongs_to_cloud = interface.startswith(f"{cloud.get('name')}_")
                has_link = (cloud.get("node_id"), port.get("port_number")) in remaining_link_ports
                if belongs_to_cloud or has_link:
                    remaining_cloud_vlans.add(interface)

        logger.info(
            "GNS3 VLAN inventory for destroy: "
            f"candidates={sorted(requested)}, managed={sorted(managed)}, "
            f"running={sorted(running)}, protected_cloud={sorted(remaining_cloud_vlans)}"
        )
        for name, vlan_id in sorted(requested.items()):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", name):
                self.conflicts.append(f"Invalid managed VLAN interface name: {name!r}")
            elif name in protected_groups:
                logger.warning(f"Keeping VLAN interface {name}: protected by settings")
            elif name in remaining_vm_groups:
                logger.warning(f"Keeping VLAN interface {name}: still used by another ESXi VM")
            elif name in remaining_cloud_vlans:
                logger.warning(f"Keeping VLAN interface {name}: referenced by a remaining GNS3 Cloud node")
            elif name in managed or name in running and running[name][0] == vlan_id:
                self.to_delete["vlans"].append(name)
            elif name in running:
                logger.warning(f"Keeping VLAN interface {name}: existing VLAN ID does not match the topology")
            else:
                logger.warning(
                    f"VLAN interface {name} was not found on the GNS3 VM "
                    f"(Netplan: {setup.NETPLAN_FILE}, parent: {setup.parent_interface})"
                )
        setup.vlans = requested
        self.gns3_vlan_setup = setup

    def init_topology_cleanup(self, graph: Graph, state: TopologyState, all_resources: bool = False) -> None:
        """
        Plans unused network cleanup, optionally including resources outside the topology.
        :param graph: Topology whose resources must be preserved.
        :param state: Current ESXi and GNS3 inventory.
        :param all_resources: Include non-excluded VMs, nodes and projects outside the topology.
        :raises RuntimeError: If ESXi, GNS3 or VLAN inventory cannot be inspected.
        """
        self.conflicts = list(state.conflicts)
        esxi = self.esxi_orchestrator.esxi_connection
        host = esxi.get_esxi_object(vim.HostSystem)
        if host is None or getattr(host.config, "network", None) is None:
            raise RuntimeError("ESXi network inventory is unavailable; cleanup cancelled")
        virtual_machines = esxi.get_esxi_object(vim.VirtualMachine, get_all=True) or []
        if all_resources:
            self._plan_cleanup_projects(graph, state, virtual_machines)
            self._plan_cleanup_orphans(graph, state, virtual_machines)
            current_project = self.gns3_orchestrator.gns3_connection.project_gns3_info
            if current_project is not None and (
                self.to_delete["gns3_node"] or self.to_delete["gns3_link"]
            ):
                project_id = current_project["project_id"]
                self.cleanup_project_id = project_id
                self.cleanup_project_snapshot = (
                    {node["node_id"] for node in state.gns3_project_nodes[project_id]},
                    {link["link_id"] for link in state.gns3_project_links[project_id]},
                )
        self._plan_cleanup_networks(graph, state, host, virtual_machines)
        self._plan_cleanup_vlans(graph, state, all_resources=all_resources)

    def _plan_cleanup_projects(self, graph: Graph, state: TopologyState, virtual_machines: list) -> None:
        """
        Plans removal of unprotected GNS3 projects outside the selected project.
        :param graph: Topology whose nodes must remain protected in every project.
        :param state: GNS3 project, node and link inventories.
        :param virtual_machines: ESXi VM inventory for checking excluded network usage.
        :raises RuntimeError: If a project inventory is incomplete.
        """
        excluded = set(Settings.GNS3.IGNORE_PROJECTS or ())
        protected_names = (
            set(Settings.GNS3.IGNORE_NODES or ())
            | set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ())
            | {Settings.ESXI.GNS3_VM_NAME}
        )
        selected = self.gns3_orchestrator.gns3_connection.project_gns3_info or {}
        esxi = self.esxi_orchestrator.esxi_connection
        protected_groups = set(Settings.ESXI.IGNORE_PORT_GROUPS or ())
        protected_groups.update((Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP))
        protected_switches = set(Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ())
        protected_groups.update(
            name for name, group in state.port_groups.items() if group.spec.vswitchName in protected_switches
        )
        for vm in virtual_machines:
            if ESXiConnection.compare_regular_to_esxi_name(
                set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ()) | {Settings.ESXI.GNS3_VM_NAME}, vm.name
            ):
                protected_groups.update(
                    name for nic in esxi.get_virtual_machine_nics(vm)
                    if (name := esxi.get_nic_port_group(nic)) is not None
                )
        project_ids = set(state.gns3_project_nodes)
        for project in state.gns3_projects:
            project_id = project["project_id"]
            if (
                project_id == selected.get("project_id")
                or project["name"] == Settings.GNS3.PROJECT_NAME
                or project["name"] in excluded
            ):
                continue
            nodes = state.gns3_project_nodes[project_id]
            links = state.gns3_project_links[project_id]
            matching_nodes = sorted({node.get("name") for node in nodes if node.get("name") in graph.nodes})
            if matching_nodes:
                self.conflicts.append(
                    f"Refusing to delete GNS3 project {project['name']!r} ({project_id}): "
                    f"it contains nodes from the loaded topology ({', '.join(matching_nodes)}). "
                    "Verify the topology file (-t) and gns3.project_name in settings."
                )
                continue
            if any(node.get("name") in protected_names for node in nodes):
                continue
            interfaces = self._get_cloud_interfaces(
                state, excluded_project_ids=project_ids - {project_id}, linked_only=True
            )
            if interfaces & protected_groups:
                continue
            self.to_delete["gns3_project"].append(project)
            self.gns3_project_snapshots[project_id] = (
                {node["node_id"] for node in nodes},
                {link["link_id"] for link in links},
            )

    def _plan_cleanup_orphans(self, graph: Graph, state: TopologyState, virtual_machines: list) -> None:
        """
        Plans removal of unprotected VMs and nodes outside the selected topology.
        :param graph: Expected topology.
        :param state: Current GNS3 inventory.
        :param virtual_machines: ESXi VM inventory.
        :raises RuntimeError: If a GNS3 link cannot be inspected.
        """
        from loguru import logger

        protected_vms = set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ())
        protected_vms.add(Settings.ESXI.GNS3_VM_NAME)
        excluded_nodes = set(Settings.GNS3.IGNORE_NODES or ()) | protected_vms
        removed_projects = {project["project_id"] for project in self.to_delete["gns3_project"]}
        selected = self.gns3_orchestrator.gns3_connection.project_gns3_info or {}
        retained_names = {
            node["name"]
            for project_id, nodes in state.gns3_project_nodes.items()
            if project_id not in removed_projects and project_id != selected.get("project_id")
            for node in nodes
            if isinstance(node.get("name"), str)
        }
        if Settings.GNS3.PROJECT_NAME not in (Settings.GNS3.IGNORE_PROJECTS or ()):
            excluded_ids = {node["node_id"] for node in state.gns3_all_nodes if node["name"] in excluded_nodes}
            adjacent_to_excluded = {
                end["node_id"]
                for link in state.gns3_links
                if any(end["node_id"] in excluded_ids for end in link["nodes"])
                for end in link["nodes"]
            }
            for node in state.gns3_all_nodes:
                if node["name"] in graph.nodes or node["name"] in excluded_nodes:
                    continue
                if node["node_id"] in adjacent_to_excluded:
                    logger.warning("Keeping GNS3 node {}: linked to an excluded node", node["name"])
                    continue
                self.to_delete["gns3_node"].append(node)
            self._plan_cleanup_links(graph, state, excluded_ids)
        removed_nodes = {node["node_id"] for node in self.to_delete["gns3_node"]}
        retained_names.update(
            node["name"]
            for node in state.gns3_all_nodes
            if node["node_id"] not in removed_nodes and isinstance(node.get("name"), str)
        )
        retained_interfaces = self._get_cloud_interfaces(
            state, excluded_node_ids=removed_nodes, excluded_project_ids=removed_projects, linked_only=True
        )
        esxi = self.esxi_orchestrator.esxi_connection
        for vm in virtual_machines:
            if ESXiConnection.compare_regular_to_esxi_name(protected_vms | set(graph.nodes) | retained_names, vm.name):
                continue
            if any(
                esxi.get_nic_port_group(nic) in retained_interfaces
                for nic in esxi.get_virtual_machine_nics(vm)
            ):
                continue
            self.to_delete["esxi_vm"].append(vm)

    def _plan_cleanup_networks(
        self, graph: Graph, state: TopologyState, host: vim.HostSystem, virtual_machines: list
    ) -> None:
        """
        Plans removal of unused port groups and standard virtual switches.
        :param graph: Expected topology.
        :param state: Current ESXi and GNS3 inventory.
        :param host: ESXi host containing the network inventory.
        :param virtual_machines: ESXi VM inventory.
        :raises RuntimeError: If a required network resource cannot be inspected.
        """
        esxi = self.esxi_orchestrator.esxi_connection
        network = host.config.network
        deleted_vms = {id(vm) for vm in self.to_delete["esxi_vm"]}
        used_groups = {
            name
            for vm in virtual_machines
            if id(vm) not in deleted_vms
            for nic in esxi.get_virtual_machine_nics(vm)
            if (name := esxi.get_nic_port_group(nic)) is not None
        }
        vmkernel_groups = {nic.portgroup for nic in (network.vnic or [])}
        required_groups = set(self._get_required_port_groups(graph))
        excluded_groups = set(Settings.ESXI.IGNORE_PORT_GROUPS or ())
        excluded_groups.update((Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP))
        excluded_switches = set(Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ())
        uplink_switches = {switch.name for switch in network.vswitch or [] if esxi.virtual_switch_has_uplinks(switch)}
        protected_switches = excluded_switches | uplink_switches | {Settings.ESXI.VIRTUAL_SWITCH}
        deleted_node_ids = {node["node_id"] for node in self.to_delete["gns3_node"]}
        removed_projects = {project["project_id"] for project in self.to_delete["gns3_project"]}
        cloud_interfaces = self._get_cloud_interfaces(
            state, excluded_node_ids=deleted_node_ids, excluded_project_ids=removed_projects,
            linked_only=True, connected_only=True
        ) | self._get_protected_cloud_interfaces(state)

        for name, group in sorted(state.port_groups.items()):
            if name in required_groups | excluded_groups | used_groups | vmkernel_groups | cloud_interfaces:
                continue
            if group.spec.vswitchName in excluded_switches | uplink_switches:
                continue
            self.to_delete["port_group"].append(name)

        removed_groups = set(self.to_delete["port_group"])
        for switch in network.vswitch or []:
            if switch.name in protected_switches:
                continue
            if any(
                group.spec.vswitchName == switch.name and name not in removed_groups
                for name, group in state.port_groups.items()
            ):
                continue
            self.to_delete["virtual_switch"].append(switch.name)

    def _plan_cleanup_vlans(self, graph: Graph, state: TopologyState, all_resources: bool = False) -> None:
        """
        Plans cleanup of managed GNS3 VLAN interfaces not needed by Cloud links or protected resources.
        :param graph: Topology whose GNS3-facing VLANs must be preserved.
        :param state: Inventories of ESXi and GNS3 resources across all projects.
        :param all_resources: Ignore Cloud links scheduled for full cleanup.
        :raises RuntimeError: If VLAN or GNS3 link inventories cannot be inspected.
        :raises ValueError: If a required topology VLAN is invalid.
        """
        from loguru import logger

        setup = GNS3VMInterfaceSetup(self.gns3_orchestrator.gns3_ssh_connection, Settings.GNS3.PARENT_INTERFACE)
        managed = setup.get_managed_vlan_names()
        running = setup._get_existing_subinterfaces()
        untracked = set(running) - managed
        if untracked:
            logger.debug("Keeping {} unmanaged GNS3 VLAN subinterfaces", len(untracked))

        removed_nodes = {node["node_id"] for node in self.to_delete["gns3_node"]} if all_resources else set()
        removed_projects = (
            {project["project_id"] for project in self.to_delete["gns3_project"]} if all_resources else set()
        )
        connected = self._get_cloud_interfaces(
            state,
            excluded_node_ids=removed_nodes,
            excluded_project_ids=removed_projects,
            linked_only=True,
            connected_only=True,
        )

        # ESXi NICs use port groups, not the corresponding subinterfaces on the
        # GNS3 VM. A surviving port group alone must not keep a VLAN alive.
        setup._create_subinterface_creation_commands(graph)
        required = set(setup.vlans)
        excluded_groups = set(Settings.ESXI.IGNORE_PORT_GROUPS or ())
        excluded_groups.update((Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP))
        excluded_switches = set(Settings.ESXI.IGNORE_VIRTUAL_SWITCHES or ())
        excluded_groups.update(
            name for name, group in state.port_groups.items() if group.spec.vswitchName in excluded_switches
        )
        excluded_vm_names = set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ()) | {Settings.ESXI.GNS3_VM_NAME}
        esxi = self.esxi_orchestrator.esxi_connection
        for vm in esxi.get_esxi_object(vim.VirtualMachine, get_all=True) or []:
            if ESXiConnection.compare_regular_to_esxi_name(excluded_vm_names, vm.name):
                excluded_groups.update(
                    name for nic in esxi.get_virtual_machine_nics(vm)
                    if (name := esxi.get_nic_port_group(nic)) is not None
                )

        owned_by_excluded = self._get_protected_cloud_interfaces(state) | {
            name for name in managed
            if any(name.startswith(f"{owner}_") for owner in excluded_vm_names)
        }

        protected = connected | required | excluded_groups | owned_by_excluded
        self.to_delete["vlans"] = sorted(managed - protected)
        self.gns3_vlan_setup = setup
        logger.debug(
            "GNS3 VLAN cleanup: mode={}, managed={}, running={}, linked={}, required={}, excluded={}, removable={}",
            "all" if all_resources else "unused",
            len(managed),
            len(running),
            len(managed & connected),
            len(managed & required),
            len(managed & (excluded_groups | owned_by_excluded)),
            len(self.to_delete["vlans"]),
        )

    def _plan_cleanup_links(self, graph: Graph, state: TopologyState, excluded_ids: set[str]) -> None:
        """
        Plans deletion of links attached to orphan nodes selected for removal.
        :param graph: Topology whose existing connections must be preserved.
        :param state: Current GNS3 project inventory.
        :param excluded_ids: Node IDs protected from cleanup.
        :raises RuntimeError: If a GNS3 link cannot be inspected safely.
        """
        removed_ids = {node["node_id"] for node in self.to_delete["gns3_node"]}
        if not removed_ids:
            return

        graph_ids = {node["node_id"] for node in state.gns3_all_nodes if node["name"] in graph.nodes}
        for link in state.gns3_links:
            try:
                link_id = link["link_id"]
                endpoints = link["nodes"]
                node_ids = {endpoint["node_id"] for endpoint in endpoints}
            except (KeyError, TypeError) as exc:
                raise RuntimeError("Cannot safely inspect GNS3 links; cleanup cancelled") from exc
            if not isinstance(endpoints, list) or len(endpoints) != 2 or not node_ids:
                raise RuntimeError(f"Invalid endpoints on GNS3 link {link_id}; cleanup cancelled")
            if node_ids & excluded_ids or node_ids.issubset(graph_ids):
                continue
            if node_ids & removed_ids:
                self.to_delete["gns3_link"].append(link_id)

    @staticmethod
    def _get_protected_cloud_interfaces(state: TopologyState) -> set[str]:
        """
        Returns VLAN interfaces owned by ignored GNS3 Cloud nodes or projects.
        :param state: GNS3 inventories across all projects.
        :return: Interface names reserved for excluded resources.
        """
        ignored_nodes = set(Settings.GNS3.IGNORE_NODES or ())
        ignored_projects = set(Settings.GNS3.IGNORE_PROJECTS or ())
        project_names = {project["project_id"]: project["name"] for project in state.gns3_projects}
        protected: set[str] = set()
        for project_id, nodes in state.gns3_project_nodes.items():
            for node in nodes:
                name = node.get("name")
                if (
                    node.get("node_type") != "cloud"
                    or not isinstance(name, str)
                    or (name not in ignored_nodes and project_names.get(project_id) not in ignored_projects)
                ):
                    continue
                for port in (node.get("properties") or {}).get("ports_mapping") or []:
                    if isinstance(port, dict) and isinstance(port.get("interface"), str):
                        interface = port["interface"]
                        if interface.startswith(f"{name}_"):
                            protected.add(interface)
        return protected

    @staticmethod
    def _get_cloud_interfaces(
        state: TopologyState,
        excluded_node_ids: set[str] | None = None,
        excluded_project_ids: set[str] | None = None,
        linked_only: bool = False,
        connected_only: bool = False,
    ) -> set[str]:
        """
        Returns GNS3 Cloud VLAN interfaces used by remaining projects and nodes.
        :param state: GNS3 node and link inventories.
        :param excluded_node_ids: Nodes scheduled for deletion.
        :param excluded_project_ids: Projects scheduled for deletion.
        :param linked_only: Consider only linked or node-owned ports, not discovered host ports.
        :param connected_only: Include only ports with an existing GNS3 link.
        :return: Protected interface names.
        :raises RuntimeError: If a GNS3 link or Cloud port inventory is malformed.
        """
        removed_nodes = excluded_node_ids or set()
        removed_projects = excluded_project_ids or set()
        inventories = (
            state.gns3_project_nodes
            if state.gns3_project_nodes
            else {"current": state.gns3_all_nodes}
        )
        linked_ports: dict[str, set[tuple[str, int]]] = {}
        if linked_only:
            links_by_project = (
                state.gns3_project_links
                if state.gns3_project_nodes
                else {"current": state.gns3_links}
            )
            for project_id, links in links_by_project.items():
                if project_id in removed_projects:
                    continue
                linked_ports[project_id] = set()
                for link in links:
                    endpoints = link.get("nodes")
                    if not isinstance(endpoints, list) or len(endpoints) != 2:
                        raise RuntimeError("Cannot inspect GNS3 Cloud link endpoints during cleanup")
                    for endpoint in endpoints:
                        if not isinstance(endpoint, dict) or not isinstance(endpoint.get("node_id"), str) or not isinstance(endpoint.get("port_number"), int):
                            raise TypeError("Cannot inspect GNS3 Cloud link ports during cleanup")
                        linked_ports[project_id].add((endpoint["node_id"], endpoint["port_number"]))

        interfaces: set[str] = set()
        for project_id, nodes in inventories.items():
            if project_id in removed_projects:
                continue
            for node in nodes:
                if node.get("node_type") != "cloud" or node.get("node_id") in removed_nodes:
                    continue
                mapped_ports = (node.get("properties") or {}).get("ports_mapping") or []
                if linked_only:
                    used_ports = {
                        port_number for node_id, port_number in linked_ports.get(project_id, set())
                        if node_id == node.get("node_id")
                    }
                    known_ports = {
                        port.get("port_number") for port in mapped_ports if isinstance(port, dict)
                    }
                    if not used_ports.issubset(known_ports):
                        raise RuntimeError(f"Cannot resolve linked ports for GNS3 Cloud {node.get('name')}")
                for port in mapped_ports:
                    if not isinstance(port, dict) or not isinstance(port.get("interface"), str):
                        if linked_only:
                            raise RuntimeError("Cannot inspect GNS3 Cloud port mapping during cleanup")
                        continue
                    name = port["interface"]
                    is_connected = (node.get("node_id"), port.get("port_number")) in linked_ports.get(project_id, set())
                    if connected_only:
                        if is_connected:
                            interfaces.add(name)
                    elif not linked_only or name.startswith(f"{node.get('name')}_") or is_connected:
                        interfaces.add(name)
        return interfaces

    def _compare_port_groups(self, graph: Graph, state: TopologyState, preserve_unused: bool = False) -> None:
        """
        Plans required ESXi port groups and optional cleanup.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        :param preserve_unused: Keep unused port groups during recreation.
        :raises RuntimeError: If the ESXi inventory cannot be retrieved.
        """
        from loguru import logger

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
        protected = set(Settings.ESXI.IGNORE_PORT_GROUPS or ())
        protected.update((Settings.ESXI.MANAGEMENT_PORT_GROUP, Settings.ESXI.TRUNK_PORT_GROUP))
        if Settings.ESXI.TRUNK_PORT_GROUP in (Settings.ESXI.IGNORE_PORT_GROUPS or ()):
            self.conflicts.append(f"GNS3 trunk {Settings.ESXI.TRUNK_PORT_GROUP} is excluded by settings")
            return
        for name, vlan_id in required.items():
            current = state.port_groups.get(name)
            if current is None:
                if name in protected and name != Settings.ESXI.TRUNK_PORT_GROUP:
                    self.conflicts.append(f"Protected port group {name} is missing")
                else:
                    self.to_add["port_group"].append((name, vlan_id))
            elif name == Settings.ESXI.TRUNK_PORT_GROUP:
                if current.spec.vswitchName != switch_name:
                    self._check_trunk_migration(state)
                if current.spec.vswitchName != switch_name or int(current.spec.vlanId) != 4095:
                    self.to_change["port_group"].append((name, 4095))
            elif name in protected:
                if int(current.spec.vlanId) != vlan_id:
                    self.conflicts.append(
                        f"Protected port group {name} has VLAN ID {current.spec.vlanId}, expected {vlan_id}"
                    )
            elif current.spec.vswitchName != switch_name or int(current.spec.vlanId) != vlan_id:
                self.to_change["port_group"].append((name, vlan_id))

        if preserve_unused:
            return

        candidates = {
            name
            for name, group in state.port_groups.items()
            if group.spec.vswitchName == switch_name and name not in required and name not in protected
        }
        if not candidates:
            return

        esxi = self.esxi_orchestrator.esxi_connection
        host = esxi.get_esxi_object(vim.HostSystem)
        if host is None:
            logger.warning("Keeping unused port groups: ESXi VMkernel adapters could not be inspected")
            return
        vmkernel_groups = {nic.portgroup for nic in (host.config.network.vnic or [])}
        vm_users: dict[str, set[str]] = {}
        for vm in esxi.get_esxi_object(vim.VirtualMachine, get_all=True) or []:
            for nic in esxi.get_virtual_machine_nics(vm):
                group_name = esxi.get_nic_port_group(nic)
                if group_name is not None:
                    vm_users.setdefault(group_name, set()).add(vm.name)
        cloud_interfaces = self._get_cloud_interfaces(state)

        for name in sorted(candidates):
            if name in vmkernel_groups:
                logger.info(f"Keeping port group {name}: used by an ESXi VMkernel adapter")
            elif name in vm_users:
                logger.info(f"Keeping port group {name}: used by VM(s) {', '.join(sorted(vm_users[name]))}")
            elif name in cloud_interfaces:
                logger.info(f"Keeping port group {name}: referenced by a GNS3 Cloud node")
            else:
                self.to_delete["port_group"].append(name)
                logger.info(f"Scheduling removal of unused port group {name}")

    def _check_trunk_migration(self, state: TopologyState) -> None:
        """
        Checks whether the configured GNS3 trunk can be safely relocated.
        :param state: Current ESXi inventory.
        :raises RuntimeError: If VMkernel or VM ownership cannot be inspected.
        """
        esxi = self.esxi_orchestrator.esxi_connection
        host = esxi.get_esxi_object(vim.HostSystem)
        if host is None or getattr(host.config, "network", None) is None:
            raise RuntimeError("Cannot inspect ESXi host networking before moving the GNS3 trunk")
        trunk = Settings.ESXI.TRUNK_PORT_GROUP
        if any(nic.portgroup == trunk for nic in (host.config.network.vnic or [])):
            self.conflicts.append(f"Cannot move GNS3 trunk {trunk}: used by an ESXi VMkernel adapter")
        for vm in esxi.get_esxi_object(vim.VirtualMachine, get_all=True) or []:
            if ESXiConnection.compare_regular_to_esxi_name(Settings.ESXI.GNS3_VM_NAME, vm.name):
                continue
            if any(esxi.get_nic_port_group(nic) == trunk for nic in esxi.get_virtual_machine_nics(vm)):
                self.conflicts.append(f"Cannot move GNS3 trunk {trunk}: also used by VM {vm.name}")

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

    def _compare_virtual_machines(self, graph: Graph, state: TopologyState, recreate: bool = False) -> None:
        """
        Plans ESXi VM synchronization or replacement.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        :param recreate: Replace existing graph-owned VMs.
        :raises RuntimeError: If the ESXi VM inventory cannot be retrieved.
        """
        protected = set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ())
        protected.add(Settings.ESXI.GNS3_VM_NAME)
        existing_vms = (
            self.esxi_orchestrator.esxi_connection.get_esxi_object(vim.VirtualMachine, get_all=True) or []
            if recreate
            else []
        )
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue
            if recreate:
                matches = [vm for vm in existing_vms if ESXiConnection.compare_regular_to_esxi_name(node.name, vm.name)]
                if len(matches) > 1:
                    self.conflicts.append(f"Cannot recreate {node.name}: multiple matching ESXi VMs exist")
                    continue
            vm = state.virtual_machines.get(node.name)
            if recreate and matches and vm is None:
                self.conflicts.append(f"Cannot recreate {node.name}: inconsistent ESXi VM inventory")
                continue
            if vm is None:
                self.to_add["esxi_vm"].append(node)
            elif not ESXiConnection.compare_regular_to_esxi_name(node.name, vm.name):
                self.conflicts.append(f"Ambiguous ESXi VM name {node.name}: found {vm.name}")
            elif recreate:
                if ESXiConnection.compare_regular_to_esxi_name(protected, vm.name):
                    self.conflicts.append(f"Cannot recreate protected ESXi VM {vm.name}")
                    continue
                self.to_delete["esxi_vm"].append(vm)
                self.to_add["esxi_vm"].append(node)
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

    def _compare_nodes(self, graph: Graph, state: TopologyState, recreate: bool = False) -> None:
        """
        Plans GNS3 node synchronization or replacement.
        :param graph: Desired topology.
        :param state: Current infrastructure.
        :param recreate: Replace existing graph-owned nodes.
        :raises RuntimeError: If GNS3 template information cannot be retrieved.
        :raises TimeoutError: If a GNS3 request times out.
        """
        connection = self.gns3_orchestrator.gns3_connection
        templates = {}
        protected = set(Settings.ESXI.IGNORE_VIRTUAL_MACHINES or ())
        protected.add(Settings.ESXI.GNS3_VM_NAME)
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
                elif recreate:
                    if ESXiConnection.compare_regular_to_esxi_name(protected, node.name):
                        self.conflicts.append(f"Cannot recreate GNS3 Cloud for protected ESXi VM {node.name}")
                    else:
                        self._replace_node(node)
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
            if recreate:
                self._replace_node(node)
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

    def _compare_node_positions(self, graph: Graph, state: TopologyState) -> None:
        """
        Plans position updates for existing nodes belonging to the topology.
        :param graph: Graph defining the managed nodes.
        :param state: Current GNS3 node inventory.
        """
        adding = {node.name for node in self.to_add["gns3_node"]}
        updating = {node.name: properties for node, properties in self.to_change["gns3_node"]}
        for name, (x, y) in self.gns3_positions.items():
            current = state.gns3_nodes.get(name)
            if name in adding or current is None or (current.get("x"), current.get("y")) == (x, y):
                continue
            properties = updating.get(name)
            if properties is not None:
                properties.update({"x": x, "y": y})
            else:
                self.to_change["gns3_node"].append((graph.nodes[name], {"x": x, "y": y}))

    def _compare_vlan_interfaces(self, graph: Graph) -> None:
        """
        Checks required VLANs while preserving interfaces of existing VMs.
        :param graph: Desired topology.
        :raises RuntimeError: If the running VLAN inventory cannot be read.
        :raises ValueError: If GNS3 returns invalid interface data.
        """
        from loguru import logger

        setup = GNS3VMInterfaceSetup(self.gns3_orchestrator.gns3_ssh_connection, Settings.GNS3.PARENT_INTERFACE)
        try:
            setup.initialize_yaml(graph)
            managed = setup.get_managed_vlan_names()
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

        # Normal deployments do not delete VMs, so they must also preserve their VLANs.
        preserved = managed - setup._requested_vlan_names
        if preserved:
            logger.debug("Keeping {} previously managed VLAN interfaces not required by this topology", len(preserved))

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
            # ESXi peers communicate through their matching VLAN port groups, not GNS3 Cloud links.
            if node.env == Environment.ON_ESXI and neighbour.env == Environment.ON_ESXI:
                continue
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
        Assigns one VLAN per logical ESXi connection while preserving existing IDs.
        :param graph: Desired topology.
        :param existing: Existing ESXi port groups.
        :return: Port-group names mapped to VLAN IDs.
        :raises RuntimeError: If VLAN IDs are exhausted.
        """
        requested = self._get_required_port_groups(graph)
        used = {
            int(group.spec.vlanId)
            for name, group in existing.items()
            if name not in requested and 2 <= int(group.spec.vlanId) <= 4094
        }
        paired: dict[str, Any] = {}
        for source, source_port, target, target_port in graph._edges:
            first = graph.nodes[source].interfaces[source_port].vlan
            second = graph.nodes[target].interfaces[target_port].vlan
            if first is not None and second is not None:
                paired[first.name] = second
                paired[second.name] = first

        allocated: dict[str, int] = {}
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None or vlan.name in allocated:
                    continue
                other = paired.get(vlan.name)
                vlan_names = (vlan.name, other.name) if other is not None else (vlan.name,)
                preferred = [
                    int(existing[name].spec.vlanId)
                    for name in vlan_names if name in existing
                ] + [vlan.id]
                vlan_id = next((value for value in preferred if 2 <= value <= 4094 and value not in used), None)
                if vlan_id is None:
                    vlan_id = next((value for value in range(2, 4095) if value not in used), None)
                if vlan_id is None:
                    raise RuntimeError("No VLAN IDs are available for the requested topology")
                used.add(vlan_id)
                vlan._vlan_id = vlan_id
                allocated[vlan.name] = vlan_id
                if other is not None:
                    other._vlan_id = vlan_id
                    allocated[other.name] = vlan_id
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
