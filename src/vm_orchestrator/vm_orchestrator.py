"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.connection_handler.topology_builder_services import TopologyBuilderServices
from src.connection_handler.esxi_connection import ESXiConnection
from src.connection_handler.ssh_connection import SSHConnection
from src.connection_handler.gns3_connection import GNS3Connection
from src.graph_builder.factories import GenericNode, Environment
from src.logger_adapter import get_logger
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.settings import Settings

logger = get_logger()


class VMOrchestrator:
    """
    Provides methods for the whole process of provisioning the VMs on GNS3 and ESXi.
    As well as for creating certain parts of needed components and for setting the settings of the GNS3 VM.
    @TODO create pytest
    """

    def __init__(self, esxi_host: str, username: str, password: str) -> None:
        """
        Initializes the VMOrchestrator class and creates a connection to the ESXi host.
        :param esxi_host: IPv4 address of the ESXi host
        :param username: username of the ESXi host
        :param password: corresponding password for user
        @TODO create pytest
        """
        self.esxi_connection = ESXiConnection(esxi_host, username, password)

    def deploy_graph(self, nodes: dict[str, GenericNode]) -> None:
        interface_to_vlan = self._configure_gns3_interfaces(nodes)
        self.esxi_connection.reset()
        self.esxi_connection.initialize_vswitch(interface_to_vlan)

        gns3_ip = self.esxi_connection.get_vm_ip_address("GNS3")
        if gns3_ip is None:
            raise logger.alert(
                RuntimeError,
                f"No VM found on ESXi Host: {self.esxi_connection.ip_address} with the name: GNS3",
            )

        gns3_conn = GNS3Connection(gns3_ip, 80)

        for node in nodes.values():
            if node.env == Environment.ON_ESXI:
                ports_mapping = []
                for port_number, interface in enumerate(node.interfaces.values()):
                    ports_mapping.append(
                        {
                            "interface": f"{interface.esxi_vlan}",
                            "name": interface.name,
                            "port_number": port_number,
                            "type": "ethernet",
                        }
                    )

                print(gns3_conn.create_builtin_nodes(node, "Cloud", ports_mapping))
                print("CREATED CLOUD NODE")
                self.esxi_connection.deploy_vm(
                    vm_name=node.name,
                    datastore=Settings.Esxi.DATASTORE,
                    ova_filename=TopologyBuilderServices.get_ova(node.image),
                    mapped_network={
                        interface.name: interface.esxi_vlan
                        for interface in node.interfaces.values()
                    },
                )

            if node.env == Environment.ON_GNS3:
                print(gns3_conn.create_node(node))

            for interface in node.interfaces:
                neigh = node.get_neighbour(interface)
                if neigh.gns3_node_info is None:
                    continue

                gns3_conn.connect_nodes(node, neigh)

    # def _configure_needed_portgroups(self, nodes: dict[str, GenericNode]) -> dict[str, int]:
    #   return self._configure_gns3_interfaces(nodes)

    def _configure_gns3_interfaces(
        self, nodes: dict[str, GenericNode]
    ) -> dict[str, int]:
        """
        Writes the config file for the GNS3 VM to delete and create the needed subinterfaces.
        :param nodes: built topology of the nodes
        :return: Returns a dictionary where each Interface is mapped to
        @TODO create pytest
        """
        gns3_ip_address = self.esxi_connection.get_vm_ip_address("GNS3")
        if gns3_ip_address is None:
            raise logger.alert(
                ConnectionError,
                "Cannot connect to GNS3 VM. No IP address or VM was found.",
            )

        gns3_connection = SSHConnection(gns3_ip_address, 22, "gns3", "gns3")

        gns3_settings_setter = GNS3VMInterfaceSetup(gns3_connection)
        gns3_settings_setter.write_config_file(nodes)

        gns3_connection.upload_file(
            gns3_settings_setter.configuration_file_path,
            "/tmp/gns3_if_vlan_settings.txt",
        )
        gns3_connection.exec_command("sudo bash /tmp/gns3_if_vlan_settings.txt")
        return gns3_settings_setter.interface_map
