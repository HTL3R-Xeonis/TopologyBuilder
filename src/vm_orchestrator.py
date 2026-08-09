"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__license__ = "GNU GPLv3"

from src.connections_handler import SSHConnection, ESXiConnection
from src.logger_adapter import get_logger
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.factories import GenericNode, compute_esxi_vlan_assignments

logger = get_logger(__name__)


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
        logger.info(f"Connecting to ESXi host {esxi_host} as {username}")
        self.esxi_connection = ESXiConnection(esxi_host, username, password)
        logger.info(f"Connected to ESXi host {esxi_host}")

    def create_gns3_configuration_file(self, nodes: dict[str, GenericNode]) -> None:
        """
        Ensures the ESXi vSwitch has a port group for every ESXi-hosted
        interface's VLAN, then applies the matching subinterface configuration
        to the GNS3 VM so the two sides of the bridge agree on VLAN numbering.
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """
        vlan_assignments = compute_esxi_vlan_assignments(nodes)
        for esxi_vlan_name, vlan_id in vlan_assignments.items():
            self.esxi_connection.ensure_port_group(esxi_vlan_name, vlan_id)
        logger.info(f"Ensured {len(vlan_assignments)} ESXi port group(s)")

        logger.debug("Looking up IP address of GNS3 VM")
        gns3_ip_address = self.esxi_connection.get_vm_ip_address("GNS3")
        if gns3_ip_address is None:
            raise logger.alert(
                ConnectionError,
                "Cannot connect to GNS3 VM. No IP address or VM was found.",
            )
        logger.info(f"GNS3 VM found at {gns3_ip_address}")

        gns3_connection = SSHConnection(gns3_ip_address, "gns3", "gns3")
        gns3_settings_setter = GNS3VMInterfaceSetup(gns3_connection)
        gns3_settings_setter.write_config_file(nodes)
        logger.info(f"Wrote GNS3 configuration for {len(nodes)} node(s)")
