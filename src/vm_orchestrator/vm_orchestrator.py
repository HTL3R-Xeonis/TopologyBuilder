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
from src.graph.blocks import GenericNode
from src.graph import Environment, Graph
from src.logger_adapter import get_logger
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup

logger = get_logger()


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
        esxi_username: str,
        esxi_password: str | None,
        gns3_vm_name: str,
    ) -> None:
        """
        :param esxi_host: IPv4 address of the ESXi host.
        :param esxi_username: username of the ESXi host.
        :param esxi_password: corresponding password for user.
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host.
        :raises RuntimeError: Is thrown when the GNS3 VM is not found on the ESXi host.
        """
        self.esxi_connection = ESXiConnection(esxi_host, esxi_username, esxi_password)

        gns3_vm_ip = self.esxi_connection.get_vm_ip_address(gns3_vm_name)
        if gns3_vm_ip is None:
            raise logger.alert(
                RuntimeError,
                f"No VM found on ESXi Host: {self.esxi_connection.ip} with the name: {gns3_vm_name}",
            )
        self.gns3_vm_ip = gns3_vm_ip

    def deploy_graph(
        self, graph: Graph, gns3_username: str, gns3_password: str | None = None
    ) -> None:
        """
        Deploys the graph on the ESXi host and GNS3 VM. The connection between the nodes runs solely between GNS3.
        This is established with multiple port groups with unique vlans on the vSwitch in ESXi.
        :param graph: Graph to deploy
        :param gns3_username: Username for the GNS3 VM
        :param gns3_password: Password for the GNS3 VM. Set to  None if no password is set.
        :return:
        :raises RuntimeError: Is thrown when VLANs which should exist, do not exist in the graph.
        """
        self._configure_gns3_interfaces(graph, gns3_username, gns3_password)
        self.esxi_connection.reset_virtual_switch()
        self.esxi_connection.initialize_virtual_switch(graph)

        gns3_conn = GNS3Connection(self.gns3_vm_ip, 80)

        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                """
                self.esxi_connection.deploy_virtual_machine(
                    vm_name=node.name,
                    datastore=Settings.Esxi.DATASTORE,
                    ova_filename=APIHandler.get_ova(node.image),
                    mapped_network=self._create_mapped_network(node)
                )"""

            gns3_conn.create_node(node)
            self._partially_link_gns3_nodes(gns3_conn, node)

    @staticmethod
    def _partially_link_gns3_nodes(gns3_connection: GNS3Connection, node) -> None:
        """
        Links only those nodes to this node who already exist on GNS3.
        :param gns3_connection: GNS3 API connection
        :param node: Node to connect to the other existing nodes.
        :return:
        """
        for interface in node.interfaces:
            neighbour = node.get_neighbour(interface)
            if neighbour is None or neighbour.gns3_node_info is None:
                continue
            gns3_connection.connect_nodes(node, neighbour)

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
                raise logger.alert(
                    RuntimeError,
                    f"Something went wrong with the graph initialization. Needed VLAN does not exist on {node.name}.{interface.name}",
                )
            mapped_network[interface.name] = vlan.name
        return mapped_network

    # TODO Parent Interface Settings
    def _configure_gns3_interfaces(
        self, graph: Graph, gns3_username: str, gns3_password: str | None
    ) -> None:
        """
        Configures the interfaces of the GNS3 VM to fit the graph. This is done to have an interface for each VLAN on the vSwitch.
        :param graph: Create the interfaces based on given graph
        :param gns3_username: Username to connect to the GNS3 VM via ssh
        :param gns3_password: Password to connect to the GNS3 VM via ssh
        :return:
        """
        gns3_connection = SSHConnection(
            self.gns3_vm_ip, 22, gns3_username, gns3_password
        )

        gns3_interface_setup = GNS3VMInterfaceSetup(gns3_connection, "eth1")
        gns3_interface_setup.initialize_commands(graph)
        gns3_interface_setup.execute_script()
