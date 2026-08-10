"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__license__ = "GNU GPLv3"

import tempfile
import time
from datetime import datetime
from pathlib import Path

from src.connections_handler import SSHConnection, ESXiConnection, APIFunctions
from src.gns3_client import deploy_topology
from src.logger_adapter import get_logger
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.ova_importer import OVAImporter
from src.factories import Environment, GenericNode, compute_esxi_vlan_assignments

logger = get_logger(__name__)

_IP_WAIT_POLL_INTERVAL_SECONDS = 5
_DEFAULT_GNS3_VM_NAME = "GNS3"


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

    def _resolve_gns3_vm_name(self, vm_name: str | None, require_existing: bool) -> str:
        """
        Resolves the GNS3 VM's name: returns it as-is if given, otherwise
        auto-detects it by searching for the one VM on the host that looks
        like a typical GNS3 VM (see ESXiConnection.find_gns3_vm), so common
        setups don't need to know/pass the exact name.
        :param vm_name: explicit GNS3 VM name, or None to auto-detect
        :param require_existing: if True, raise when no matching VM is found
            (used when resolving an already-running GNS3 VM); if False, fall
            back to _DEFAULT_GNS3_VM_NAME when none is found (used when a VM
            may not exist yet, e.g. deploy_fresh_gns3_vm on a fresh host)
        :return: the resolved GNS3 VM name
        """
        if vm_name is not None:
            return vm_name

        vm = self.esxi_connection.find_gns3_vm()
        if vm is not None:
            logger.info(f"Auto-detected GNS3 VM '{vm.name}'")
            return vm.name

        if require_existing:
            raise logger.alert(
                ValueError,
                "Could not find a GNS3 VM automatically (no VM name "
                "contains 'gns3'). Specify --gns3-vm-name.",
            )
        return _DEFAULT_GNS3_VM_NAME

    def deploy_fresh_gns3_vm(
        self,
        ova_path: str,
        datastore_name: str,
        mgmt_network_name: str,
        trunk_network_name: str,
        vm_name: str | None = None,
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
        :param vm_name: name the new (and previous) GNS3 VM should have, or
            None to auto-detect an existing one (falls back to 'GNS3' if
            none exists yet)
        :param ip_wait_timeout_seconds: how long to wait for the new VM to report an IP
        :return: IP address of the new GNS3 VM
        @TODO create pytest
        """
        vm_name = self._resolve_gns3_vm_name(vm_name, require_existing=False)
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

    def _get_gns3_vm_ip(self, vm_name: str | None = None) -> str:
        """
        Looks up the GNS3 VM's current IP address.
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :return: its IP address
        """
        vm_name = self._resolve_gns3_vm_name(vm_name, require_existing=True)
        logger.debug(f"Looking up IP address of '{vm_name}' VM")
        gns3_ip_address = self.esxi_connection.get_vm_ip_address(vm_name)
        if gns3_ip_address is None:
            raise logger.alert(
                ConnectionError,
                f"Cannot connect to '{vm_name}' VM. No IP address or VM was found.",
            )
        logger.info(f"'{vm_name}' VM found at {gns3_ip_address}")
        return gns3_ip_address

    def delete_stale_esxi_resources(self, nodes: dict[str, GenericNode]) -> None:
        """
        Deletes VMs and port groups left over from an earlier deploy of the
        current topology's ESXi-hosted nodes, so redeploying doesn't
        accumulate duplicate/renamed VMs (ESXi silently imports a colliding
        name as e.g. 'PC4_1' rather than overwriting 'PC4') or leave a port
        group behind under the same name but a stale VLAN ID from a
        previous topology layout. Call this before
        create_gns3_configuration_file, so each node's port group is
        already free (no VM using it) by the time it's recreated.
        :param nodes: built topology of the nodes
        :return:
        """
        for node in nodes.values():
            if node.env != Environment.ON_ESXI:
                continue

            for vm in self.esxi_connection.find_vms_matching(node.name):
                logger.info(f"Deleting stale ESXi VM '{vm.name}'")
                self.esxi_connection.delete_vm(vm)

            for interface in node.interfaces.values():
                self.esxi_connection.delete_port_group(interface.esxi_vlan)

    def create_gns3_configuration_file(
        self,
        nodes: dict[str, GenericNode],
        vm_name: str | None = None,
        trunk_network_name: str | None = None,
        trunk_interface: str = "eth1",
    ) -> None:
        """
        Ensures the ESXi vSwitch has a port group for every ESXi-hosted
        interface's VLAN, then applies the matching subinterface configuration
        to the GNS3 VM so the two sides of the bridge agree on VLAN numbering.
        :param nodes: built topology of the nodes
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :param trunk_network_name: name of the ESXi port group carrying the
            GNS3 VM's VLAN trunk NIC (e.g. PG-GNS3-TRUNK). If given, ensures
            it accepts promiscuous mode/MAC changes/forged transmits, which
            GNS3's Cloud nodes need to bridge in each topology device's own
            MAC through that one NIC - ESXi's default security policy
            silently drops that traffic otherwise. Skipped if not given.
        :param trunk_interface: name of the GNS3 VM's own guest-OS network
            interface for that same trunk NIC (e.g. 'eth1'). Not the same
            as trunk_network_name above - this is the interface name
            inside the GNS3 VM's guest OS, which isn't guaranteed to match
            across different GNS3 VM builds (see GNS3VMInterfaceSetup).
        :return:
        """
        vlan_assignments = compute_esxi_vlan_assignments(nodes)
        for esxi_vlan_name, vlan_id in vlan_assignments.items():
            self.esxi_connection.ensure_port_group(esxi_vlan_name, vlan_id)
        logger.info(f"Ensured {len(vlan_assignments)} ESXi port group(s)")

        if trunk_network_name is not None:
            self.esxi_connection.ensure_bridging_security_policy(trunk_network_name)

        gns3_ip_address = self._get_gns3_vm_ip(vm_name)

        gns3_connection = SSHConnection(gns3_ip_address, "gns3", "gns3")
        gns3_settings_setter = GNS3VMInterfaceSetup(gns3_connection)
        gns3_settings_setter.write_config_file(nodes, trunk_interface=trunk_interface)
        logger.info(f"Wrote GNS3 configuration for {len(nodes)} node(s)")

    def deploy_gns3_topology(
        self,
        nodes: dict[str, GenericNode],
        project_name: str,
        vm_name: str | None = None,
    ) -> None:
        """
        Builds the topology's actual nodes and links inside a GNS3 project,
        via the GNS3 v2 controller API. ESXi-hosted nodes get bridged in via
        Cloud nodes bound to the VLAN subinterfaces create_gns3_configuration_file
        sets up - call that first so the subinterfaces already exist.
        :param nodes: built topology of the nodes
        :param project_name: name of the GNS3 project to create or reuse
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :return:
        @TODO create pytest
        """
        gns3_ip_address = self._get_gns3_vm_ip(vm_name)
        deploy_topology(f"http://{gns3_ip_address}", project_name, nodes)

    def deploy_esxi_nodes(
        self,
        nodes: dict[str, GenericNode],
        datastore_name: str,
        download_dir: str | None = None,
    ) -> None:
        """
        Provisions the real ESXi VM behind every ESXi-hosted node in the
        topology: downloads the OVA matching the node's image from the NFS
        template API (the image source for role: VM nodes - see
        technische_dokumentation_APIs.docx section 2.3), imports it as a new
        VM named after the node with its network adapters wired to the VLAN
        port groups create_gns3_configuration_file set up - call that first,
        so those port groups already exist - and powers it on. An image is
        only downloaded once even if several nodes share it, since these
        OVAs can run into multiple gigabytes.
        :param nodes: built topology of the nodes
        :param datastore_name: ESXi datastore to place the new VMs on
        :param download_dir: directory to stage downloaded OVAs in before
            import. Defaults to the system temp dir, which may not have
            room for multi-gigabyte OVAs - point this at a larger volume
            if needed. Created automatically if it doesn't exist yet.
        :return:
        """
        if download_dir is not None:
            Path(download_dir).mkdir(parents=True, exist_ok=True)

        importer = OVAImporter(self.esxi_connection)
        with tempfile.TemporaryDirectory(
            prefix="topologybuilder-ova-", dir=download_dir
        ) as tmp_dir:
            ova_paths: dict[str, str] = {}
            for node in nodes.values():
                if node.env != Environment.ON_ESXI:
                    continue

                if node.image not in ova_paths:
                    ova_path = str(Path(tmp_dir) / f"{len(ova_paths)}.ova")
                    APIFunctions.download_esxi_template(node.image, ova_path)
                    ova_paths[node.image] = ova_path

                network_names = [
                    interface.esxi_vlan for interface in node.interfaces.values()
                ]
                vm = importer.import_ova(
                    ova_paths[node.image], node.name, datastore_name, network_names
                )
                self.esxi_connection.power_on_vm(vm)
                logger.info(f"Provisioned ESXi VM '{node.name}'")
