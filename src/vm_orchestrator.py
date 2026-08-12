"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.connections_handler import SSHConnection, ESXiConnection
from src.logger_adapter import get_logger
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.factories import GenericNode
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

    def create_gns3_configuration_file(
        self, nodes: dict[str, GenericNode]
    ) -> dict[str, int]:
        """
        Writes the config file for the GNS3 VM to delete and create the needed subinterfaces.
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """
        gns3_ip_address = self.esxi_connection.get_vm_ip_address("GNS3")
        if gns3_ip_address is None:
            raise logger.alert(
                ConnectionError,
                "Cannot connect to GNS3 VM. No IP address or VM was found.",
            )

        gns3_connection = SSHConnection(gns3_ip_address, "gns3", "gns3")
        gns3_settings_setter = GNS3VMInterfaceSetup(gns3_connection)
        gns3_settings_setter.write_config_file(nodes)
        return gns3_settings_setter.interface_map

    def reset_esxi_host(self) -> None:
        """
        Resets the ESXi host, so that the VM orchestration has no problems with setting the vSwitch and the other VMs up.
        :return:
        @TODO create pytest
        """
        self._remove_port_groups()

    def _remove_port_groups(self) -> None:
        """
        Removes all the port groups from the vSwitch, specified in Settings.Esxi.VIRTUAL_SWITCH,
        except for the port groups which are specified in Settings.Esxi.IGNORE_PORT_GROUPS.
        :return:
        @TODO create pytest
        """
        port_groups = self.esxi_connection.get_port_groups()
        for pg in port_groups:
            if pg.spec.name in Settings.Esxi.IGNORE_PORT_GROUPS | {"PG_GNS3_TRUNK"}:
                continue
            self.esxi_connection.remove_port_group(pg.spec.name)

    def add_port_groups(self, map: dict[str, int]) -> None:
        """
        Adds all the needed ports, for the corresponding GNS3 connection, to the vSwitch specified in Settings.Esxi.VIRTUAL_SWITCH.
        :param map: Interface-name mapped to the VLAN ID.
        :return:
        @TODO create pytest
        """
        for name, vlan_id in map.items():
            self.esxi_connection.add_port_group(name, vlan_id)
