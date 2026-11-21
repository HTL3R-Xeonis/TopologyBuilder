"""Provides ESXi and GNS3 topology inspection and provisioning."""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from loguru import logger

from src.connections import SSHConnection
from src.connections.esxi_connection import ESXiConnection
from src.connections.gns3_connection import GNS3Connection
from src.doctor.topology_state import TopologyChanges, TopologyState
from src.graph import Environment, Graph
from src.orchestrator import GNS3Orchestrator
from src.orchestrator.esxi.esxi_orchestrator import ESXiOrchestrator
from src.settings import Settings


# @TODO ExceptionHandling
# @TODO Complete and recursive Exception Documentation.
# @TODO upgrade Logging
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
        Deploys a graph completely or synchronizes an existing topology.
        :param graph: Desired topology.
        """
        state = TopologyState()
        state.get_topology_state(graph, self.esxi_orchestrator.esxi_connection, self.gns3_orchestrator.gns3_connection)

        changes = TopologyChanges(self.esxi_orchestrator, self.gns3_orchestrator)
        changes.init_topology_changes(graph, state)

        self.apply_topology_changes(changes)

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
        return changes

    def apply_topology_destruction(self, changes: TopologyChanges) -> None:
        """
        Deletes the graph-owned resources selected by a destruction plan.
        :param changes: Validated topology destruction plan.
        :raises RuntimeError: If the plan is unsafe or infrastructure deletion fails.
        :raises requests.RequestException: If GNS3 deletion fails.
        :raises vim.fault.VimFault: If an ESXi deletion task fails.
        """
        if changes.conflicts:
            raise RuntimeError("Cannot destroy topology:\n- " + "\n- ".join(changes.conflicts))
        if Settings.IS_DRY_RUN or not changes.has_changes:
            return

        connection = self.gns3_orchestrator.gns3_connection
        if changes.to_delete["gns3_link"] or changes.to_delete["gns3_node"]:
            project = connection.project_gns3_info
            if project is None:
                raise RuntimeError("GNS3 project is missing; cannot delete its resources.")
            if project.get("status") == "closed":
                connection.post(f"{connection.get_project_url()}/open", json={})
            base = connection.get_project_url()
            for link_id in changes.to_delete["gns3_link"]:
                connection.delete(f"{base}/links/{link_id}")
            for node in changes.to_delete["gns3_node"]:
                connection.delete(f"{base}/nodes/{node.node_gns3_info['node_id']}")

        self.esxi_orchestrator.destroy_virtual_machines(changes.to_delete["esxi_vm"])
        if changes.to_delete["port_group"]:
            self.esxi_orchestrator.remove_port_groups(set(changes.to_delete["port_group"]))
        if changes.to_delete["vlans"]:
            changes.gns3_vlan_setup.remove_managed_vlans(set(changes.to_delete["vlans"]))

    def apply_topology_changes(self, changes: TopologyChanges) -> None:
        """
        Applies validated topology changes using existing provisioning methods.
        :param changes: Additions, modifications and deletions to apply.
        :raises RuntimeError: If the plan contains conflicts or a GNS3 Cloud cannot be configured.
        :raises ValueError: If an ESXi Cloud has an invalid interface configuration.
        :raises requests.RequestException: If a GNS3 API request fails.
        """
        if changes.conflicts:
            raise RuntimeError("Cannot synchronize topology:\n- " + "\n- ".join(changes.conflicts))
        if not changes.has_changes:
            return

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

        for node in changes.to_add["esxi_vm"]:
            self.esxi_orchestrator.deploy_virtual_machine(node, Settings.ESXI.DATASTORE)
        for vm, nic, group in changes.to_change["esxi_nic"]:
            self.esxi_orchestrator._configure_network_adapter(vm, nic, group)
        for vm, port_groups in changes.to_add["esxi_nic"]:
            self.esxi_orchestrator._add_virtual_machine_adapters(vm, port_groups)

        connection = self.gns3_orchestrator.gns3_connection
        base = connection.get_project_url()
        # Remove links before their nodes to avoid stale link IDs.
        for link_id in changes.to_delete["gns3_link"]:
            connection.delete(f"{base}/links/{link_id}")
        for node in changes.to_delete["gns3_node"]:
            connection.delete(f"{base}/nodes/{node.node_gns3_info['node_id']}")
        for node in changes.to_add["gns3_node"]:
            result = self.gns3_orchestrator.create_node(node)
            if result is not None:
                node.node_gns3_info = result
                if node.env == Environment.ON_ESXI:
                    required = connection._create_ports_mapping(node, connected_only=True)
                    if len(required) > 1:
                        connection.ensure_cloud_ports(node, required)
        for node, properties in changes.to_change["gns3_node"]:
            connection.update_node(node, properties)
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
