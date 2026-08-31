"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.connections.esxi_connection import ESXiConnection
from src.connections.ssh_connection import SSHConnection
from src.connections.gns3_connection import GNS3Connection
from src.settings import Settings
from src.graph import Environment, Graph
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from loguru import logger


# @TODO ExceptionHandling
# @TODO Complete and recursive Exception Documentation.
# @TODO upgrade Logging
class VMOrchestrator:
    """
    Object which controls the process of the VMs provisioning.
    """

    def __init__(
        self,
        esxi_host: str,
        esxi_port: int,
        esxi_username: str,
        esxi_password: str | None,
        gns3_vm_name: str,
    ) -> None:
        """
        :param esxi_host: IPv4 address of the ESXi host.
        :param esxi_port: Port number of the ESXi host, where the API requests are expected.
        :param esxi_username: username of the ESXi host.
        :param esxi_password: corresponding password for user.
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host.
        :raises RuntimeError: Is thrown when the GNS3 VM is not found on the ESXi host.
        :raises ValueError: Is thrown when invalid credentials are provided or the IPv4 address is not a public, private or loopback address.
        :raises TimeoutError: Is thrown when timeout occurs.
        :raises ConnectionError: Is thrown when the connection buildup fails.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        """
        if (
            not isinstance(esxi_host, str)
            or not isinstance(esxi_port, int)
            or not isinstance(esxi_username, str)
            or not (isinstance(esxi_password, str) or esxi_password is None)
        ):
            raise TypeError

        self.esxi_connection = ESXiConnection(
            esxi_host, esxi_port, esxi_username, esxi_password
        )

        gns3_vm_ip = self.esxi_connection.get_vm_ip_address(gns3_vm_name)
        if gns3_vm_ip is None:
            logger.error(
                msg
                := f"No VM found on ESXi Host: {self.esxi_connection.ip} with the name: {gns3_vm_name}"
            )
            raise RuntimeError(msg)
        self.gns3_vm_ip = gns3_vm_ip

    def deploy_graph(
        self, graph: Graph, gns3_username: str, gns3_password: str | None = None
    ) -> None:
        """
        Deploys the graph on the ESXi host and GNS3 VM. The connection between the nodes runs solely between GNS3.
        This is established with multiple port groups with unique vlans on the vSwitch in ESXi.
        Starts every created GNS3 node once linking is complete - GNS3 does
        not start a node automatically when it's created via the API.
        :param graph: Graph to deploy
        :param gns3_username: Username for the GNS3 VM
        :param gns3_password: Password for the GNS3 VM. Set to  None if no password is set.
        :return:

        :raises TimeoutError: Is thrown when it took too long to receive a response.
        :raises ConnectionError: Is thrown when something on the connection buildup fails.
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address.
            Is also thrown when the credentials are not valid.
            May also be thrown when no virtual Switch was found.
            May also be thrown when the image of the node does not exist on the GNS3 instance.
            May also be thrown when no adapter can be associated with the given interface.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node.
            May also be thrown when an error occurs while trying to get subinterface information or when the execution of the script fails.
            May also be thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
            May also be thrown when a portgroup already exists on the ESXi host. May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        self._configure_gns3_interfaces(graph, gns3_username, gns3_password)
        self.esxi_connection.reset_virtual_switch()
        self.esxi_connection.initialize_virtual_switch(graph)

        gns3_conn = GNS3Connection(
            self.gns3_vm_ip, Settings.GNS3.PORT, Settings.GNS3.PROJECT_NAME
        )

        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                self.esxi_connection.deploy_virtual_machine(
                    node=node, datastore=Settings.ESXI.DATASTORE
                )
                gns3_conn.create_node(node)

            if node.env == Environment.ON_GNS3:
                gns3_conn.create_node(node)

            self._partially_link_gns3_nodes(gns3_conn, node)

        gns3_conn.start_all_nodes()

    def delete_stale_esxi_resources(self, graph: Graph) -> None:
        """
        Deletes VMs and port groups left over from an earlier deploy of the
        graph's ESXi-hosted nodes, so redeploying doesn't accumulate
        duplicate/renamed VMs or leave a port group behind under the same
        name but a stale VLAN ID from a previous topology layout.
        :param graph: Graph whose ESXi-hosted nodes' stale resources to delete
        :return:
        """
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue

            for vm in self.esxi_connection.find_vms_matching(node.name):
                self.esxi_connection.delete_vm(vm)

            for interface in node.interfaces.values():
                if interface.vlan is not None:
                    self.esxi_connection.delete_port_group(interface.vlan.name)

    def destroy_graph(self, graph: Graph, project_name: str) -> None:
        """
        Tears down a previously deployed topology: deletes its ESXi-hosted
        VMs/port groups, and its GNS3 project's nodes (GNS3Connection's own
        constructor already deletes and recreates an existing project by
        name, which is exactly what's needed here too).
        :param graph: Graph whose deployed resources to tear down
        :param project_name: name of the GNS3 project to clear
        :return:
        """
        self.delete_stale_esxi_resources(graph)
        GNS3Connection(self.gns3_vm_ip, Settings.GNS3.PORT, project_name)

    @staticmethod
    def _partially_link_gns3_nodes(gns3_connection: GNS3Connection, node) -> None:
        """
        Links only those nodes to this node who already exist on GNS3.
        :param gns3_connection: GNS3 API connection
        :param node: Node to connect to the other existing nodes.
        :return:
        :raises ValueError: Is thrown when no adapter can be associated with the given interface. This may happen because the names are not the same.
        :raises RuntimeError: Is thrown when both nodes have no connection in the graph to each other. May also be thrown when one of the nodes does not exist in GNS3.
        """
        for interface in node.interfaces:
            neighbour = node.get_neighbour(interface)
            if neighbour is None or neighbour.gns3_node_info is None:
                continue
            gns3_connection.connect_nodes(node, neighbour)

    def _configure_gns3_interfaces(
        self, graph: Graph, gns3_username: str, gns3_password: str | None
    ) -> None:
        """
        Configures the interfaces of the GNS3 VM to fit the graph. This is done to have an interface for each VLAN on the vSwitch.
        :param graph: Create the interfaces based on given graph.
        :param gns3_username: Username to connect to the GNS3 VM via ssh.
        :param gns3_password: Password to connect to the GNS3 VM via ssh.
        :return:
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address. Is also thrown when the credentials are not valid.
        :raises TimeoutError: Is thrown when the connection buildup takes too long.
        :raises ConnectionError: Is thrown when the connection fails.
        :raises RuntimeError: Is thrown when an error occurs while trying to get subinterface information or when the execution of the script fails.
        """
        if Settings.ONLY_ON_ESXI:
            return

        port = 22

        gns3_connection = SSHConnection(
            self.gns3_vm_ip, port, gns3_username, gns3_password
        )
        gns3_interface_setup = GNS3VMInterfaceSetup(
            gns3_connection, Settings.GNS3.PARENT_INTERFACE
        )

        gns3_interface_setup.initialize_commands(graph)
        gns3_interface_setup.execute_script()
