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
    ) -> None:
        """
        Initializes the ESXi connection for topology management.
        :param esxi_host: ESXi server IP address.
        :param esxi_port: ESXi API port.
        :param esxi_username: ESXi username.
        :param esxi_password: ESXi password.
        """
        esxi_connection = ESXiConnection(esxi_host, esxi_port, esxi_username, esxi_password)
        self.esxi_orchestrator = ESXiOrchestrator(esxi_connection)

        gns3_ip = self._get_gns3_ip(Settings.ESXI.GNS3_VM_NAME)
        if gns3_ip is None:
            raise RuntimeError("GNS3 VM not found.")
        gns3_connection = GNS3Connection(gns3_ip, Settings.GNS3.PORT, Settings.GNS3.PROJECT_NAME)
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

    def deploy_vm(self, graph: Graph) -> None:
        """
        Deploys graph devices to ESXi and GNS3.
        :param graph: Graph to deploy.
        """
        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                self.esxi_orchestrator.deploy_virtual_machine(node=node, datastore=Settings.ESXI.DATASTORE)
                self.gns3_orchestrator.create_node(node)
            if node.env == Environment.ON_GNS3:
                self.gns3_orchestrator.create_node(node)
            self.gns3_orchestrator.partially_link_gns3_nodes(node)

    def apply_topology_changes(self, changes: TopologyChanges) -> None:
        """
        Applies validated topology changes using existing provisioning methods.
        :param changes: Additions, modifications and deletions to apply.
        :raises RuntimeError: If the plan contains conflicts.
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
        if changes.to_change["vlans"]:
            changes.gns3_vlan_setup.apply_yaml()

        for node in changes.to_add["esxi_vm"]:
            self.esxi_orchestrator.deploy_virtual_machine(node, Settings.ESXI.DATASTORE)
        for vm, nic, group in changes.to_change["esxi_nic"]:
            self.esxi_orchestrator._configure_network_adapter(vm, nic, group)
        for vm, port_groups in changes.to_add["esxi_nic"]:
            self.esxi_orchestrator._add_virtual_machine_adapters(vm, port_groups)
        if changes.to_delete["port_group"]:
            self.esxi_orchestrator.remove_port_groups(set(changes.to_delete["port_group"]))

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
        for node, properties in changes.to_change["gns3_node"]:
            url = f"{self.gns3_orchestrator.gns3_connection.get_project_url()}/nodes/{node.node_gns3_info['node_id']}"
            response = requests.put(url, json=properties, timeout=30)
            response.raise_for_status()
        for first, second in changes.to_add["gns3_link"]:
            connection.connect_nodes(first, second)

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
