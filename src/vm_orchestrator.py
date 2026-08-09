"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__license__ = "GNU GPLv3"

import time
from datetime import datetime

from src.connections_handler import SSHConnection, ESXiConnection
from src.logger_adapter import get_logger
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.ova_importer import OVAImporter
from src.factories import GenericNode, compute_esxi_vlan_assignments

logger = get_logger(__name__)

_IP_WAIT_POLL_INTERVAL_SECONDS = 5


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

    def deploy_fresh_gns3_vm(
        self,
        ova_path: str,
        datastore_name: str,
        mgmt_network_name: str,
        trunk_network_name: str,
        vm_name: str = "GNS3",
        ip_wait_timeout_seconds: int = 300,
    ) -> str:
        """
        Replaces the existing GNS3 VM with a freshly imported one from the
        given OVA. The old VM (if any) is powered off and renamed as a
        timestamped backup rather than deleted. The new VM's management NIC
        gets the old VM's MAC address, so a DHCP server that hands out
        addresses by MAC (reservation, or a not-yet-expired lease) gives the
        new VM the same IP as the old one. This does NOT work if the GNS3
        VM's IP is a static address configured inside the guest OS.
        :param ova_path: local filesystem path to the GNS3 OVA
        :param datastore_name: ESXi datastore to place the new VM on
        :param mgmt_network_name: ESXi port group for the new VM's management NIC.
            Must be the OVA's FIRST-added network adapter.
        :param trunk_network_name: ESXi port group for the new VM's VLAN trunk
            NIC. Must be the OVA's SECOND-added network adapter.
        :param vm_name: name the new (and previous) GNS3 VM should have
        :param ip_wait_timeout_seconds: how long to wait for the new VM to report an IP
        :return: IP address of the new GNS3 VM
        @TODO create pytest
        """
        old_vm = self.esxi_connection.get_vm(vm_name)
        old_mac_address = None
        if old_vm is not None:
            old_mac_address = self.esxi_connection.get_vm_mac_address(old_vm)
            logger.info(f"Powering off existing '{vm_name}' VM")
            self.esxi_connection.power_off_vm(old_vm)
            backup_name = f"{vm_name}-backup-{datetime.now():%Y%m%d%H%M%S}"
            self.esxi_connection.rename_vm(old_vm, backup_name)
            logger.info(f"Renamed existing '{vm_name}' VM to '{backup_name}'")

        importer = OVAImporter(self.esxi_connection)
        new_vm = importer.import_ova(
            ova_path,
            vm_name,
            datastore_name,
            [mgmt_network_name, trunk_network_name],
        )

        if old_mac_address is not None:
            self.esxi_connection.set_vm_mac_address(new_vm, old_mac_address)
            logger.info(f"Set new '{vm_name}' VM's MAC to {old_mac_address}")

        logger.info(f"Powering on '{vm_name}' VM")
        self.esxi_connection.power_on_vm(new_vm)

        logger.debug(f"Waiting for '{vm_name}' VM to report an IP address")
        deadline = time.monotonic() + ip_wait_timeout_seconds
        while time.monotonic() < deadline:
            ip_address = self.esxi_connection.get_vm_ip_address(vm_name)
            if ip_address is not None:
                logger.info(f"'{vm_name}' VM is up at {ip_address}")
                return ip_address
            time.sleep(_IP_WAIT_POLL_INTERVAL_SECONDS)

        raise logger.alert(
            TimeoutError,
            f"'{vm_name}' VM did not report an IP address within {ip_wait_timeout_seconds}s",
        )

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
