"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from loguru import logger

from src.connections.esxi_connection import ESXiConnection
from src.connections.gns3_connection import GNS3Connection
from src.graph import Environment, Graph
from src.settings import Settings

from .esxi_orchestrator import ESXiOrchestrator
from .gns3_orchestrator import GNS3Orchestrator


# @TODO ExceptionHandling
# @TODO Complete and recursive Exception Documentation.
# @TODO upgrade Logging
class GraphOrchestrator:
    """
    Object which controls the process of the VMs provisioning.
    """

    def __init__(
        self,
        esxi_host: str,
        esxi_port: int,
        esxi_username: str,
        esxi_password: str | None,
    ) -> None:
        """
        :param esxi_host: IPv4 address of the ESXi host.
        :param esxi_port: Port number of the ESXi host, where the API requests are expected.
        :param esxi_username: username of the ESXi host.
        :param esxi_password: corresponding password for user.
        :raises RuntimeError: Is thrown when the GNS3 VM is not found on the ESXi host.
        :raises ValueError: Is thrown when invalid credentials are provided or the IPv4 address is not a public, private or loopback address.
        :raises TimeoutError: Is thrown when timeout occurs.
        :raises ConnectionError: Is thrown when the connection buildup fails.
        """
        esxi_connection = ESXiConnection(
            esxi_host, esxi_port, esxi_username, esxi_password
        )

        self.esxi_orchestrator = ESXiOrchestrator(esxi_connection)
        self.gns3_orchestrator = None

    def execute_graph_deployment(
        self, graph: Graph, gns3_username: str, gns3_password: str | None = None
    ) -> None:
        """
        Deploys the graph on the ESXi host and GNS3 VM. The connection between the nodes runs solely between GNS3.
        This is established with multiple port groups with unique vlans on the vSwitch in ESXi.
        :param graph: Graph to deploy.
        :param gns3_username: Username for the GNS3 VM
        :param gns3_password: Password for the GNS3 VM. Set to  ``None`` if no password is set.
        :return:
        """
        # Get needed Portgroups
        needed_port_groups = self._get_needed_port_group_names(graph)
        # Disconnect adapters from ignored VMs from needed portgroups
        self.esxi_orchestrator.ensure_adapter_connection(
            vm_names=Settings.ESXI.IGNORE_VIRTUAL_MACHINES,
            port_group_names=needed_port_groups,
            should_connect=False,
        )
        # Destroy VMs in Portgroups and disconnect ignored VMs.
        self.esxi_orchestrator.destroy_old_vms(needed_port_groups)
        # Destroy Portgroups and Trunk_Port_group
        self.esxi_orchestrator.remove_port_groups(needed_port_groups)
        # Create vSwitch if necessary
        self.esxi_orchestrator.ensure_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
        # Create Portgroups and Trunk_Port_group
        self.esxi_orchestrator.create_port_groups(needed_port_groups)
        # Deploy GNS3 VM if necessary
        # @TODO
        # Alter GNS3 Adapter portgroups
        self.esxi_orchestrator.ensure_gns3_vm_adapter(
            gns3_vm_name=Settings.ESXI.GNS3_VM_NAME,
            mgmt_port_group=Settings.ESXI.MANAGEMENT_PORT_GROUP,
            trunk_port_group=Settings.ESXI.TRUNK_PORT_GROUP,
        )
        # Connect adapter from ignored VMs to needed portgroups
        self.esxi_orchestrator.ensure_adapter_connection(
            vm_names=Settings.ESXI.IGNORE_VIRTUAL_MACHINES,
            port_group_names=needed_port_groups,
            should_connect=True,
        )

        gns3_connection = GNS3Connection(
            ip=self._get_gns3_ip(Settings.ESXI.GNS3_VM_NAME),
            port=Settings.GNS3.PORT,
            project_name=Settings.GNS3.PROJECT_NAME,
        )
        self.gns3_orchestrator = GNS3Orchestrator(gns3_connection)

        # Configure GNS3 Interfaces
        self.gns3_orchestrator.configure_gns3_vm_interfaces(
            graph, gns3_username, gns3_password
        )
        # Deploy VMs
        self.deploy_vm(graph)

    def deploy_vm(self, graph: Graph) -> None:
        """
        Deploys the nodes in the graph on GNS3 and if necessary also on ESXi.
        :param graph: Graph to deploy
        :return:
        :raises TimeoutError: Is thrown when it took too long to receive a response.
        :raises ConnectionError: Is thrown when something on the connection buildup fails.
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address.
            Is also thrown when the credentials are not valid.
            May also be thrown when the image of the node does not exist on the GNS3 instance.
            May also be thrown when no adapter can be associated with the given interface.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node.
            May also be thrown when an error occurs while trying to get subinterface information or when the execution of the script fails.
            May also be thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
            May also be thrown when a portgroup already exists on the ESXi host. May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                self.esxi_orchestrator.deploy_virtual_machine(
                    node=node, datastore=Settings.ESXI.DATASTORE
                )
                self.gns3_orchestrator.create_node(node)

            if node.env == Environment.ON_GNS3:
                self.gns3_orchestrator.create_node(node)

            self.gns3_orchestrator.partially_link_gns3_nodes(node)

    @staticmethod
    def _get_needed_port_group_names(graph: Graph) -> dict[str, int]:
        """
        Determines which portgroups will be needed on the ESXi host for given graph.
        :param graph: Graph which represents the network.
        :return: Returns a mapping of portgroup-name to vlan-id
        """
        port_groups = {}
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None:
                    continue

                port_groups[vlan.name] = vlan.id
        port_groups[Settings.ESXI.TRUNK_PORT_GROUP] = 4095
        port_groups[Settings.ESXI.MANAGEMENT_PORT_GROUP] = 0
        return port_groups

    def _get_gns3_ip(self, gns3_name: str) -> str:
        """
        Determines the IP address of the GNS3 VM.
        :param gns3_name: Name of the GNS3 VM.
        :return: Returns the first IPv4 address found on the VM. The reachability to the VM is not insured.
        :raises RuntimeError: Is thrown when no GNS3 VM is found on the ESXi host.
        """
        gns3_ip = self.esxi_orchestrator.esxi_connection.get_vm_ip_address(gns3_name)
        if gns3_ip is None:
            logger.error(
                msg
                := f"No VM found on ESXi Host: {self.esxi_orchestrator.esxi_connection.ip} with the name: {gns3_name}"
            )
            raise RuntimeError(msg)
        return gns3_ip
