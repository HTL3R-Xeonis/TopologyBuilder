from typing import Any

from src.connections import SSHConnection
from src.connections.gns3_connection import GNS3Connection
from src.graph import Graph
from src.graph.blocks import GenericNode
from src.orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.settings import Settings


class GNS3Orchestrator:
    """
    Orchestration object for GNS3.
    """

    def __init__(self, gns3_connection: GNS3Connection):
        """
        :param gns3_connection: API connection to the GNS3 host.
        """
        self.gns3_connection = gns3_connection

    def create_node(self, node: GenericNode) -> dict[str, Any] | None:
        """
        Creates a new GNS3 node on the GNS3 project.
        :param node: Node to be generated.
        :return: Returns the newly generated GNS3 node information. ``None`` is returned, if the ``Settings.IS_DRY_RUN`` value is True.
        :raises ValueError: Is thrown when the image of the node does not exist on the GNS3 instance.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node.
        """
        return self.gns3_connection.create_node(node)

    def partially_link_gns3_nodes(self, node: GenericNode) -> None:
        """
        Links only those nodes to this node who already exist on GNS3.
        :param node: Node to connect to the other existing nodes.
        :return:
        :raises ValueError: Is thrown when no adapter can be associated with the given interface. This may happen because the names are not the same.
        :raises RuntimeError: Is thrown when both nodes have no connection in the graph to each other. May also be thrown when one of the nodes does not exist in GNS3.
        """
        for interface in node.interfaces:
            neighbour = node.get_neighbour(interface)
            if neighbour is None or neighbour.gns3_node_info is None:
                continue
            self.gns3_connection.connect_nodes(node, neighbour)

    def configure_gns3_vm_interfaces(
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
        port = 22

        gns3_connection = SSHConnection(
            self.gns3_connection.ip, port, gns3_username, gns3_password
        )
        gns3_interface_setup = GNS3VMInterfaceSetup(
            gns3_connection, Settings.GNS3.PARENT_INTERFACE
        )

        gns3_interface_setup.initialize_commands(graph)
        gns3_interface_setup.execute_script()
