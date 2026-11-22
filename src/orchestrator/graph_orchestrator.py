"""Provides ESXi and GNS3 topology inspection and provisioning."""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import requests
from loguru import logger

from src.connections import SSHConnection
from src.connections.esxi_connection import ESXiConnection
from src.connections.gns3_connection import GNS3Connection
from src.doctor.topology_state import TopologyChanges, TopologyState
from src.graph import Environment, Graph
from src.orchestrator import GNS3Orchestrator
from src.orchestrator.esxi.esxi_orchestrator import ESXiOrchestrator
from src.settings import Settings


def log_change_plan(changes: TopologyChanges, operation: str) -> None:
    """
    Records a consistent summary of planned infrastructure changes.
    :param changes: Planned resource changes and conflicts.
    :param operation: Name of the planned operation.
    """
    totals = [
        sum(len(items) for items in pool.values()) for pool in (changes.to_add, changes.to_change, changes.to_delete)
    ]
    logger.info(
        "Topology plan: operation={}, add={}, update={}, delete={}, conflicts={}",
        operation,
        *totals,
        len(changes.conflicts),
    )
    for action, pool in (("add", changes.to_add), ("update", changes.to_change), ("delete", changes.to_delete)):
        counts = {kind: len(items) for kind, items in pool.items() if items}
        if counts:
            logger.debug("Topology plan details: operation={}, action={}, counts={}", operation, action, counts)
    if changes.conflicts:
        logger.warning("Topology plan blocked: operation={}, conflicts={}", operation, len(changes.conflicts))


# @TODO ExceptionHandling
# @TODO Complete and recursive Exception Documentation.
class GraphOrchestrator:
    """Inspects and synchronizes graph resources on ESXi and GNS3."""

    def __init__(
        self,
        esxi_host: str,
        esxi_port: int,
        esxi_username: str,
        esxi_password: str | None,
        gns3_username: str,
        gns3_password: str | None,
        gns3_ssh_port: int = 22,
        existing_project_only: bool = False,
    ) -> None:
        """
        Initializes the ESXi and GNS3 topology connections.
        :param esxi_host: ESXi server IP address.
        :param esxi_port: ESXi API port.
        :param esxi_username: ESXi username.
        :param esxi_password: ESXi password.
        :param gns3_username: GNS3 SSH username.
        :param gns3_password: GNS3 SSH password.
        :param gns3_ssh_port: GNS3 SSH port.
        :param existing_project_only: Inspect without creating or opening a GNS3 project.
        :raises RuntimeError: If the GNS3 host VM cannot be located.
        :raises ConnectionError: If an infrastructure connection fails.
        """
        esxi_connection = ESXiConnection(esxi_host, esxi_port, esxi_username, esxi_password)
        self.esxi_orchestrator = ESXiOrchestrator(esxi_connection)

        gns3_ip = self._get_gns3_ip(Settings.ESXI.GNS3_VM_NAME)
        if gns3_ip is None:
            raise RuntimeError("GNS3 VM not found.")
        gns3_connection = GNS3Connection(
            gns3_ip, Settings.GNS3.PORT, Settings.GNS3.PROJECT_NAME, existing_only=existing_project_only
        )
        gns3_ssh_connection = SSHConnection(gns3_connection.ip, gns3_ssh_port, gns3_username, gns3_password)
        self.gns3_orchestrator = GNS3Orchestrator(gns3_connection, gns3_ssh_connection)

    def execute_graph_deployment(self, graph: Graph) -> None:
        """
        Synchronizes or recreates graph-owned infrastructure.
        :param graph: Desired topology.
        :raises RuntimeError: If the topology contains conflicts or cannot be synchronized.
        """
        self.apply_topology_changes(self.plan_topology_deployment(graph))

    def plan_topology_deployment(self, graph: Graph) -> TopologyChanges:
        """
        Plans a topology synchronization or fresh deployment.
        :param graph: Desired topology.
        :return: Planned additions, updates, deletions and conflicts.
        :raises RuntimeError: If ESXi or GNS3 inspection fails.
        """
        state = TopologyState()
        state.get_topology_state(graph, self.esxi_orchestrator.esxi_connection, self.gns3_orchestrator.gns3_connection)
        changes = TopologyChanges(self.esxi_orchestrator, self.gns3_orchestrator)
        changes.init_topology_changes(graph, state)
        log_change_plan(changes, "deployment")
        return changes

    def plan_topology_cleanup(self, graph: Graph, all_resources: bool = False) -> TopologyChanges:
        """
        Builds a read-only cleanup plan for unused and orphan resources.
        :param graph: Topology whose resources must be preserved.
        :param all_resources: Include resources absent from the graph.
        :return: Planned cleanup operations and conflicts.
        :raises RuntimeError: If infrastructure inventory cannot be read.
        """
        state = TopologyState()
        state.get_topology_state(graph, self.esxi_orchestrator.esxi_connection, self.gns3_orchestrator.gns3_connection)
        state.get_gns3_projects_state(self.gns3_orchestrator.gns3_connection)
        changes = TopologyChanges(self.esxi_orchestrator, self.gns3_orchestrator)
        changes.init_topology_cleanup(graph, state, all_resources=all_resources)
        log_change_plan(changes, "cleanup-all" if all_resources else "cleanup-networks")
        return changes

    def apply_topology_cleanup(self, changes: TopologyChanges) -> None:
        """
        Deletes resources from a validated cleanup plan.
        :param changes: Planned deletions and conflicts.
        :raises RuntimeError: If cleanup is unsafe or a resource cannot be deleted.
        :raises vim.fault.VimFault: If an ESXi VM task fails.
        :raises requests.RequestException: If a GNS3 operation fails.
        """
        if changes.conflicts:
            raise RuntimeError("Cannot clean infrastructure:\n- " + "\n- ".join(changes.conflicts))
        if not changes.has_changes:
            return
        connection = self.gns3_orchestrator.gns3_connection
        if changes.to_delete["gns3_node"] or changes.to_delete["gns3_link"]:
            self._verify_cleanup_project(changes)
        logger.info("Topology Cleanup started")
        # Delete individual nodes and links before deleting other projects. GNS3
        # can change project state while removing a different project.
        self._remove_graph_instances(changes, remove_esxi=False)
        for project in changes.to_delete["gns3_project"]:
            nodes, links = changes.gns3_project_snapshots[project["project_id"]]
            connection._remove_project(
                project["project_id"], expected_node_ids=nodes, expected_link_ids=links
            )
        if changes.to_delete["esxi_vm"]:
            self.esxi_orchestrator.destroy_virtual_machines(changes.to_delete["esxi_vm"])

        if changes.to_delete["port_group"]:
            self.esxi_orchestrator.remove_port_groups(set(changes.to_delete["port_group"]), managed_only=False)
        for switch_name in changes.to_delete["virtual_switch"]:
            self.esxi_orchestrator.esxi_connection.remove_virtual_switch(switch_name)
        # An ESXi port group can remain in use without its corresponding VLAN
        # subinterface being needed by GNS3. Verify only live GNS3 Cloud links.
        if changes.to_delete["vlans"]:
            connected = self._get_linked_gns3_vlan_interfaces()
            newly_used = sorted(set(changes.to_delete["vlans"]) & connected)
            if newly_used:
                raise RuntimeError(
                    "Cannot remove GNS3 VLAN interfaces linked after cleanup planning: "
                    + ", ".join(newly_used)
                )

        if changes.to_delete["vlans"]:
            changes.gns3_vlan_setup.remove_managed_vlans(set(changes.to_delete["vlans"]))
        logger.info("Topology Cleanup completed")

    def _verify_cleanup_project(self, changes: TopologyChanges) -> None:
        """
        Confirms that cleanup targets the planned GNS3 project and inventory.
        :param changes: Cleanup plan containing the expected project snapshot.
        :raises RuntimeError: If the selected project changed or inventory differs.
        :raises requests.RequestException: If the project inventory cannot be read.
        """
        connection = self.gns3_orchestrator.gns3_connection
        project_id = changes.cleanup_project_id
        snapshot = changes.cleanup_project_snapshot
        if not project_id or snapshot is None:
            raise RuntimeError("GNS3 cleanup has no verified project snapshot; refusing deletion")
        selected = connection.project_gns3_info
        if selected is None or selected.get("project_id") != project_id:
            raise RuntimeError("Configured GNS3 project differs from the cleanup plan; refusing deletion")
        project = next((p for p in connection.get_projects() if p.get("project_id") == project_id), None)
        if project is None or project.get("name") != Settings.GNS3.PROJECT_NAME:
            raise RuntimeError("GNS3 project was removed or renamed after planning; refusing deletion")
        nodes = {node["node_id"] for node in connection.get_project_nodes(project_id)}
        links = {link["link_id"] for link in connection.get_project_links(project_id)}
        if (nodes, links) != snapshot:
            raise RuntimeError("GNS3 project contents changed after planning; rerun cleanup")
        if project.get("status") == "closed":
            connection.post(f"{connection.url}/v2/projects/{project_id}/open", json={})
            logger.info("GNS3 project opened for cleanup: name={}, id={}", project["name"], project_id)
        elif project.get("status") != "opened":
            raise RuntimeError(f"Cannot delete from GNS3 project {project_id}: unknown status")

    def _get_linked_gns3_vlan_interfaces(self) -> set[str]:
        """
        Returns VLAN interfaces connected to live GNS3 Cloud links across all projects.
        :return: Names of GNS3 VLAN interfaces currently used by links.
        :raises RuntimeError: If a Cloud mapping or link inventory is invalid.
        :raises requests.RequestException: If GNS3 inventory retrieval fails.
        """
        connection = self.gns3_orchestrator.gns3_connection
        state = TopologyState()
        for project in connection.get_projects():
            project_id = project["project_id"]
            state.gns3_project_nodes[project_id] = connection.get_project_nodes(project_id)
            state.gns3_project_links[project_id] = connection.get_project_links(project_id)
        return TopologyChanges._get_cloud_interfaces(state, linked_only=True, connected_only=True)

    def plan_topology_destruction(self, graph: Graph) -> TopologyChanges:
        """
        Builds a read-only destruction plan for the graph.
        :param graph: Topology to remove.
        :return: Planned deletions and conflicts.
        :raises RuntimeError: If infrastructure inspection fails.
        """
        state = TopologyState()
        state.get_topology_state(graph, self.esxi_orchestrator.esxi_connection, self.gns3_orchestrator.gns3_connection)
        changes = TopologyChanges(self.esxi_orchestrator, self.gns3_orchestrator)
        changes.init_topology_destruction(graph, state)
        log_change_plan(changes, "destruction")
        return changes

    def apply_topology_destruction(self, changes: TopologyChanges) -> None:
        """
        Deletes graph-owned resources selected by a destruction plan.
        :param changes: Validated topology destruction plan.
        :raises RuntimeError: If the plan is unsafe or resource deletion fails.
        :raises requests.RequestException: If GNS3 deletion fails.
        :raises vim.fault.VimFault: If an ESXi deletion task fails.
        """
        if changes.conflicts:
            raise RuntimeError("Cannot destroy topology:\n- " + "\n- ".join(changes.conflicts))
        if not changes.has_changes:
            return
        logger.info("Topology Destruction started")
        self._remove_graph_instances(changes)
        if changes.to_delete["port_group"]:
            self.esxi_orchestrator.remove_port_groups(set(changes.to_delete["port_group"]))
        if changes.to_delete["vlans"]:
            changes.gns3_vlan_setup.remove_managed_vlans(set(changes.to_delete["vlans"]))
        logger.info("Topology Destruction completed")

    def _remove_graph_instances(self, changes: TopologyChanges, remove_esxi: bool = True) -> None:
        """
        Deletes selected GNS3 links and nodes and ESXi virtual machines.
        :param changes: Validated resource deletion plan.
        :param remove_esxi: Whether to delete selected ESXi VMs after GNS3 resources.
        :raises RuntimeError: If the GNS3 project is missing or a VM is protected.
        :raises requests.RequestException: If a GNS3 request fails.
        :raises vim.fault.VimFault: If an ESXi deletion task fails.
        """
        connection = self.gns3_orchestrator.gns3_connection
        if changes.to_delete["gns3_link"] or changes.to_delete["gns3_node"]:
            project = connection.project_gns3_info
            if project is None:
                raise RuntimeError("GNS3 project is missing; cannot delete its resources.")
            if project.get("status") == "closed":
                connection.post(f"{connection.get_project_url()}/open", json={})
            base = connection.get_project_url()
            for link_id in changes.to_delete["gns3_link"]:
                try:
                    connection.delete(f"{base}/links/{link_id}")
                except requests.HTTPError as exc:
                    detail = (exc.response.text or "").strip()[:240] if exc.response is not None else ""
                    raise RuntimeError(
                        f"Cannot delete GNS3 link {link_id} from project "
                        f"{project['name']} ({project['project_id']}): "
                        f"HTTP {exc.response.status_code if exc.response is not None else '?'}"
                        + (f": {detail}" if detail else "")
                    ) from exc
            for node in changes.to_delete["gns3_node"]:
                node_id = node["node_id"] if isinstance(node, dict) else node.node_gns3_info["node_id"]
                logger.info("Deleting GNS3 node: id={}", node_id)
                connection.delete(f"{base}/nodes/{node_id}")
        if remove_esxi and changes.to_delete["esxi_vm"]:
            self.esxi_orchestrator.destroy_virtual_machines(changes.to_delete["esxi_vm"])

    def apply_topology_changes(self, changes: TopologyChanges) -> None:
        """
        Applies validated topology changes in dependency order.
        :param changes: Additions, modifications and deletions to apply.
        :raises RuntimeError: If the plan is unsafe or an infrastructure operation fails.
        :raises ValueError: If an ESXi Cloud has an invalid interface configuration.
        :raises requests.RequestException: If a GNS3 API request fails.
        :raises vim.fault.VimFault: If an ESXi task fails.
        """
        if changes.conflicts:
            raise RuntimeError("Cannot synchronize topology:\n- " + "\n- ".join(changes.conflicts))
        if not changes.has_changes:
            return
        logger.info("Topology Deployment started")

        if changes.to_add["virtual_switch"] or changes.to_change["virtual_switch"]:
            self.esxi_orchestrator.ensure_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
        self.esxi_orchestrator.create_port_groups(dict(changes.to_add["port_group"]))
        self.esxi_orchestrator.create_port_groups(dict(changes.to_change["port_group"]), update=True)
        for vm, nic, group in changes.to_change["gns3_vm_adapter"]:
            self.esxi_orchestrator._configure_network_adapter(vm, nic, group)
        # New Cloud nodes must see their VLAN interfaces before GNS3 creates their ports.
        cloud_nodes = [node for node in changes.to_add["gns3_node"] if node.env == Environment.ON_ESXI]
        if changes.to_change["vlans"] or cloud_nodes or changes.to_add["esxi_vm"]:
            if changes.gns3_vlan_setup is None:
                raise RuntimeError("GNS3 VLAN configuration was not initialized")
            changes.gns3_vlan_setup.apply_yaml()

        # Replacement requires removal before redeploying VMs with the same names.
        self._remove_graph_instances(changes)
        for node in changes.to_add["esxi_vm"]:
            self.esxi_orchestrator.deploy_virtual_machine(node, Settings.ESXI.DATASTORE)
        for vm, nic, group in changes.to_change["esxi_nic"]:
            self.esxi_orchestrator._configure_network_adapter(vm, nic, group)
        for vm, port_groups in changes.to_add["esxi_nic"]:
            self.esxi_orchestrator._add_virtual_machine_adapters(vm, port_groups)

        connection = self.gns3_orchestrator.gns3_connection
        for node in changes.to_add["gns3_node"]:
            result = self.gns3_orchestrator.create_node(node, position=changes.gns3_positions.get(node.name))
            if result is not None:
                node.node_gns3_info = result
                if node.env == Environment.ON_ESXI:
                    required = connection._create_ports_mapping(node, connected_only=True)
                    if len(required) > 1:
                        connection.ensure_cloud_ports(node, required)
        moved_nodes = 0
        for node, properties in changes.to_change["gns3_node"]:
            connection.update_node(node, properties)
            if "x" in properties and "y" in properties:
                moved_nodes += 1
        if moved_nodes:
            logger.info("GNS3 node positions synchronized: count={}", moved_nodes)
        for first, second in changes.to_add["gns3_link"]:
            connection.connect_nodes(first, second)

        if changes.to_delete["port_group"]:
            self.esxi_orchestrator.remove_port_groups(set(changes.to_delete["port_group"]))
        if changes.to_delete["vlans"]:
            remaining_groups = set(self.esxi_orchestrator.esxi_connection.get_all_port_groups())
            for name in sorted(set(changes.to_delete["vlans"]) & remaining_groups):
                logger.warning(f"Keeping VLAN interface {name}: ESXi port group still exists")
            unused_vlans = set(changes.to_delete["vlans"]) - remaining_groups
            if unused_vlans:
                changes.gns3_vlan_setup.remove_managed_vlans(unused_vlans)
        logger.info("Topology Deployment completed")

    def _get_gns3_ip(self, gns3_name: str) -> str:
        """
        Returns the primary IPv4 address of a GNS3 VM.
        :param gns3_name: ESXi virtual machine name.
        :return: GNS3 VM IPv4 address.
        """
        address = self.esxi_orchestrator.esxi_connection.get_vm_ip_address(gns3_name)
        if address is None:
            message = (
                f"No VM found on ESXi Host: {self.esxi_orchestrator.esxi_connection.ip} with the name: {gns3_name}"
            )
            logger.error(message)
            raise RuntimeError(message)
        return address
