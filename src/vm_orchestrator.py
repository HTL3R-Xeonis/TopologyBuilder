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
from src.gns3_client import GNS3Client, deploy_topology, is_console_port_collision_error
from src.inventory_generator import generate_ansible_inventory
from src.logger_adapter import get_logger
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.ova_importer import OVAImporter
from src.factories import Environment, GenericNode, compute_esxi_vlan_assignments

logger = get_logger(__name__)

_IP_WAIT_POLL_INTERVAL_SECONDS = 5
_DEFAULT_GNS3_VM_NAME = "GNS3"


def _count_edges_by_kind(nodes: dict[str, GenericNode]) -> tuple[int, int, int]:
    """
    Classifies every edge in a built topology the same way deploy_topology
    (gns3_client.py) does when deciding whether to create a direct GNS3
    link, a Cloud-node bridge, or nothing at all - used by plan_deploy to
    summarize what deploying would create without duplicating that
    function's actual node/link-creation calls.
    :param nodes: built topology of the nodes
    :return: (gns3_internal_link_count, esxi_gns3_bridge_count, direct_esxi_link_count)
    """
    seen_edges = set()
    gns3_link_count = bridge_count = direct_count = 0
    for node in nodes.values():
        for interface in node.interfaces.values():
            edge = interface.edge
            if edge is None or id(edge) in seen_edges:
                continue
            seen_edges.add(id(edge))

            gns3_1 = edge.incidence_1.node.env == Environment.ON_GNS3
            gns3_2 = edge.incidence_2.node.env == Environment.ON_GNS3
            if gns3_1 and gns3_2:
                gns3_link_count += 1
            elif gns3_1 or gns3_2:
                bridge_count += 1
            else:
                direct_count += 1

    return gns3_link_count, bridge_count, direct_count


class VMOrchestrator:
    """
    Provides methods for the whole process of provisioning the VMs on GNS3 and ESXi.
    As well as for creating certain parts of needed components and for setting the settings of the GNS3 VM.
    """

    def __init__(self, esxi_host: str, username: str, password: str) -> None:
        """
        Initializes the VMOrchestrator class and creates a connection to the ESXi host.
        :param esxi_host: IPv4 address of the ESXi host
        :param username: username of the ESXi host
        :param password: corresponding password for user
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
        trunk_interface: str | None = None,
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
            interface for that same trunk NIC (e.g. 'eth1'), or None to
            auto-detect it. Not the same as trunk_network_name above - this
            is the interface name inside the GNS3 VM's guest OS, which
            isn't guaranteed to match across different GNS3 VM builds (see
            GNS3VMInterfaceSetup).
        :return:
        """
        vlan_assignments = compute_esxi_vlan_assignments(nodes)
        for esxi_vlan_name, vlan_id in vlan_assignments.items():
            self.esxi_connection.ensure_port_group(esxi_vlan_name, vlan_id)
        logger.info(f"Ensured {len(vlan_assignments)} ESXi port group(s)")

        resolved_vm_name = self._resolve_gns3_vm_name(vm_name, require_existing=True)

        if trunk_network_name is not None:
            self.esxi_connection.ensure_bridging_security_policy(trunk_network_name)
            self._verify_trunk_network_wiring(resolved_vm_name, trunk_network_name)

        gns3_ip_address = self._get_gns3_vm_ip(resolved_vm_name)

        gns3_connection = SSHConnection(gns3_ip_address, "gns3", "gns3")
        gns3_settings_setter = GNS3VMInterfaceSetup(gns3_connection)
        gns3_settings_setter.write_config_file(nodes, trunk_interface=trunk_interface)
        logger.info(f"Wrote GNS3 configuration for {len(nodes)} node(s)")

    def _trunk_network_wiring_status(
        self, vm, trunk_network_name: str
    ) -> tuple[bool, str]:
        """
        Checks whether an already-resolved GNS3 VM object has a network
        adapter actually connected to the given trunk port group, without
        raising - the shared core of _verify_trunk_network_wiring (which
        raises on failure, used during deploy to fail fast) and
        verify_topology (which reports the result as one line of a health
        check instead of aborting).
        :param vm: the already-resolved GNS3 VM object
        :param trunk_network_name: expected ESXi port group name for its trunk NIC
        :return: (True, description) if wired correctly, (False, description) otherwise
        """
        network_names = self.esxi_connection.get_vm_network_names(vm)
        if trunk_network_name not in network_names:
            return False, (
                f"no network adapter connected to port group "
                f"'{trunk_network_name}' (connected to: {network_names})"
            )
        return True, f"network adapter connected to '{trunk_network_name}'"

    def _verify_trunk_network_wiring(
        self, vm_name: str, trunk_network_name: str
    ) -> None:
        """
        Confirms the GNS3 VM has a network adapter actually connected to the
        given trunk port group, before trusting that VLAN subinterfaces built
        on its guest-OS trunk interface will reach it. ESXi gives no error or
        warning if a NIC is wired to the wrong port group (e.g. left on
        PG-MGMT after a manual edit, or a botched --fresh-gns3-vm import) -
        the ESXi<->GNS3 Cloud-node bridge just silently doesn't work. The
        same class of invisible failure ensure_bridging_security_policy
        already guards against on the security-policy side; this exact
        drift has been observed on real infra.
        :param vm_name: name of the GNS3 VM
        :param trunk_network_name: expected ESXi port group name for its trunk NIC
        :return:
        """
        vm = self.esxi_connection.get_vm(vm_name)
        if vm is None:
            return

        ok, description = self._trunk_network_wiring_status(vm, trunk_network_name)
        if not ok:
            raise logger.alert(
                ValueError,
                f"'{vm_name}' VM has {description}. The ESXi<->GNS3 bridge "
                f"will not work until a NIC is rewired to that port group "
                f"in vSphere.",
            )

    def deploy_gns3_topology(
        self,
        nodes: dict[str, GenericNode],
        project_name: str,
        vm_name: str | None = None,
        incremental: bool = False,
    ) -> None:
        """
        Builds the topology's actual nodes and links inside a GNS3 project,
        via the GNS3 v2 controller API. ESXi-hosted nodes get bridged in via
        Cloud nodes bound to the VLAN subinterfaces create_gns3_configuration_file
        sets up - call that first so the subinterfaces already exist.

        If node starting fails with the console-port-collision signature
        even after gns3_client.start_all_nodes' own single retry, captures
        SSH diagnostics from the GNS3 VM before re-raising - see
        _log_console_port_collision_diagnostics.
        :param nodes: built topology of the nodes
        :param project_name: name of the GNS3 project to create or reuse
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :param incremental: see deploy_topology's own docstring
        :return:
        """
        gns3_ip_address = self._get_gns3_vm_ip(vm_name)
        try:
            deploy_topology(
                f"http://{gns3_ip_address}",
                project_name,
                nodes,
                incremental=incremental,
            )
        except RuntimeError as error:
            if is_console_port_collision_error(error):
                self._log_console_port_collision_diagnostics(gns3_ip_address)
            raise

    def _log_console_port_collision_diagnostics(self, gns3_ip_address: str) -> None:
        """
        Best-effort diagnostic capture for a console-port-collision failure
        that survived gns3_client.start_all_nodes' own retry - SSHes into
        the GNS3 VM to record which process is actually holding the
        console port, so the next occurrence leaves real evidence in
        logs/log.txt instead of only a presumed cause (this has been
        observed twice, "fixed" both times by restarting the whole
        topology, without ever confirming what actually held the port).
        Never raises - a failed diagnostic attempt must not mask the real
        deploy error it was trying to help explain.
        :param gns3_ip_address: IP address of the GNS3 VM
        :return:
        """
        try:
            gns3_connection = SSHConnection(gns3_ip_address, "gns3", "gns3")
            for command in ("ss -tlnp", "ps aux | grep qemu"):
                _, stdout, _ = gns3_connection.exec_command(command)
                output = stdout.read().decode().strip()
                logger.error(
                    f"Console port collision diagnostics - '{command}':\n{output}"
                )
        except Exception as diagnostic_error:
            logger.warning(
                f"Could not capture console port collision diagnostics: "
                f"{diagnostic_error}"
            )

    def destroy_gns3_topology(
        self, project_name: str, vm_name: str | None = None
    ) -> None:
        """
        Deletes every node (and, as a consequence, every link between them)
        in the given GNS3 project, e.g. as part of tearing down a previously
        deployed topology. Mirrors deploy_gns3_topology's own project
        resolution - if no project by that name exists yet,
        get_or_create_project creates an empty one, which is harmless here
        since there's nothing to delete from it either way.
        :param project_name: name of the GNS3 project to clear
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :return:
        """
        gns3_ip_address = self._get_gns3_vm_ip(vm_name)
        client = GNS3Client(f"http://{gns3_ip_address}")
        project = client.get_or_create_project(project_name)
        client.delete_all_nodes(project["project_id"])

    def deploy_esxi_nodes(
        self,
        nodes: dict[str, GenericNode],
        datastore_name: str,
        download_dir: str | None = None,
        incremental: bool = False,
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
        :param incremental: if True, skips provisioning a node whose VM
            already exists (matched by name) instead of leaving that to
            delete_stale_esxi_resources - callers doing an incremental
            deploy skip calling that entirely, so an already-existing VM
            would otherwise collide on import. Doesn't detect an existing
            VM's image having changed, same caveat as deploy_topology's own
            incremental mode.
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

                if incremental and self.esxi_connection.find_vms_matching(node.name):
                    logger.info(
                        f"ESXi VM '{node.name}' already exists, skipping (incremental)"
                    )
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

    def plan_destroy(
        self,
        nodes: dict[str, GenericNode],
        project_name: str,
        vm_name: str | None = None,
    ) -> list[str]:
        """
        Reports what `destroy` would do, without deleting anything - the
        read-only counterpart to delete_stale_esxi_resources +
        destroy_gns3_topology. Never calls a mutating ESXi or GNS3 API.
        :param nodes: built topology of the nodes
        :param project_name: name of the GNS3 project that would be cleared
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :return: human-readable lines describing what would happen
        """
        lines: list[str] = []
        for node in nodes.values():
            if node.env != Environment.ON_ESXI:
                continue
            for vm in self.esxi_connection.find_vms_matching(node.name):
                lines.append(f"Would delete ESXi VM '{vm.name}'")
            for interface in node.interfaces.values():
                lines.append(
                    f"Would delete ESXi port group '{interface.esxi_vlan}' (if present)"
                )

        try:
            gns3_ip_address = self._get_gns3_vm_ip(vm_name)
        except (ConnectionError, ValueError) as error:
            lines.append(f"Could not resolve the GNS3 VM to plan its project: {error}")
            return lines

        client = GNS3Client(f"http://{gns3_ip_address}")
        project = next(
            (p for p in client.list_projects() if p.get("name") == project_name), None
        )
        if project is None:
            lines.append(
                f"GNS3 project '{project_name}' does not exist - nothing to delete there"
            )
            return lines

        existing_nodes = client.list_nodes(project["project_id"])
        if not existing_nodes:
            lines.append(f"GNS3 project '{project_name}' has no nodes")
        for gns3_node in existing_nodes:
            lines.append(
                f"Would delete GNS3 node '{gns3_node.get('name')}' in project '{project_name}'"
            )

        return lines

    def plan_deploy(
        self,
        nodes: dict[str, GenericNode],
        project_name: str,
        vm_name: str | None = None,
        fresh_gns3_vm: bool = False,
    ) -> list[str]:
        """
        Reports what `deploy` would do, without changing anything - the
        read-only counterpart to the full deploy sequence
        (delete_stale_esxi_resources, create_gns3_configuration_file,
        deploy_esxi_nodes, deploy_gns3_topology). Never calls a mutating
        ESXi or GNS3 API - only list_port_groups/find_vms_matching/
        list_projects/list_nodes.
        :param nodes: built topology of the nodes
        :param project_name: name of the GNS3 project that would be used
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :param fresh_gns3_vm: whether --fresh-gns3-vm would run first
        :return: human-readable lines describing what would happen
        """
        lines: list[str] = []
        if fresh_gns3_vm:
            lines.append(
                "Would replace the GNS3 VM with a freshly imported OVA (--fresh-gns3-vm)"
            )

        vlan_assignments = compute_esxi_vlan_assignments(nodes)
        existing_port_groups = {
            pg["name"] for pg in self.esxi_connection.list_port_groups()
        }
        for esxi_vlan_name, vlan_id in vlan_assignments.items():
            if esxi_vlan_name in existing_port_groups:
                lines.append(
                    f"ESXi port group '{esxi_vlan_name}' already exists (VLAN {vlan_id})"
                )
            else:
                lines.append(
                    f"Would create ESXi port group '{esxi_vlan_name}' (VLAN {vlan_id})"
                )

        for node in nodes.values():
            if node.env != Environment.ON_ESXI:
                continue
            for vm in self.esxi_connection.find_vms_matching(node.name):
                lines.append(f"Would delete existing ESXi VM '{vm.name}'")
            lines.append(
                f"Would import ESXi VM '{node.name}' from image '{node.image}'"
            )

        if fresh_gns3_vm:
            lines.append(
                "GNS3-side plan skipped - the GNS3 VM would be replaced by "
                "--fresh-gns3-vm before any of that could be checked"
            )
            return lines

        try:
            gns3_ip_address = self._get_gns3_vm_ip(vm_name)
        except (ConnectionError, ValueError) as error:
            lines.append(f"Could not resolve the GNS3 VM to plan its project: {error}")
            return lines

        client = GNS3Client(f"http://{gns3_ip_address}")
        project = next(
            (p for p in client.list_projects() if p.get("name") == project_name), None
        )
        if project is None:
            lines.append(
                f"GNS3 project '{project_name}' does not exist yet - would be created"
            )
        else:
            for gns3_node in client.list_nodes(project["project_id"]):
                lines.append(
                    f"Would delete existing GNS3 node '{gns3_node.get('name')}'"
                )

        for name, node in nodes.items():
            if node.env == Environment.ON_GNS3:
                lines.append(
                    f"Would create GNS3 node '{name}' from image '{node.image}'"
                )

        gns3_link_count, bridge_count, direct_count = _count_edges_by_kind(nodes)
        lines.append(f"Would create {gns3_link_count} GNS3-internal link(s)")
        lines.append(f"Would create {bridge_count} ESXi<->GNS3 Cloud-node bridge(s)")
        lines.append(
            f"{direct_count} direct ESXi-ESXi link(s) need no GNS3-side wiring"
        )

        return lines

    def verify_topology(
        self,
        nodes: dict[str, GenericNode],
        project_name: str,
        vm_name: str | None = None,
        trunk_network_name: str | None = None,
    ) -> list[tuple[bool, str]]:
        """
        Runs a structural health check against real infrastructure. This is
        NOT a connectivity/ping test - topologybuilder never assigns an IP
        address to any node (VMs get one via DHCP/manual guest-OS config,
        GNS3 devices via console config), so there is no address to ping
        for either side of an edge. What it does check: every GNS3 node is
        'started', every ESXi VM is powered on and reports an IP via
        VMware Tools, the GNS3 VM's trunk NIC is wired to the expected
        port group (if given), both sides of a direct ESXi-ESXi link agree
        on VLAN ID, and an ESXi<->GNS3 bridge's port group and Cloud node
        both exist.
        :param nodes: built topology of the nodes
        :param project_name: name of the GNS3 project to check
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :param trunk_network_name: expected ESXi port group for the GNS3
            VM's trunk NIC, or None to skip that one check
        :return: list of (passed, description) tuples, one per check
        """
        results: list[tuple[bool, str]] = []
        port_groups = {
            pg["name"]: pg["vlan_id"] for pg in self.esxi_connection.list_port_groups()
        }

        gns3_client = None
        gns3_nodes_by_name: dict[str, dict] = {}
        gns3_links: list[dict] = []
        try:
            gns3_ip_address = self._get_gns3_vm_ip(vm_name)
            resolved_vm_name = self._resolve_gns3_vm_name(
                vm_name, require_existing=True
            )
            results.append(
                (True, f"GNS3 VM '{resolved_vm_name}': reachable at {gns3_ip_address}")
            )
        except (ConnectionError, ValueError) as error:
            results.append((False, f"GNS3 VM: {error}"))
            resolved_vm_name = None
            gns3_ip_address = None

        if gns3_ip_address is not None:
            gns3_client = GNS3Client(f"http://{gns3_ip_address}")
            project = next(
                (
                    p
                    for p in gns3_client.list_projects()
                    if p.get("name") == project_name
                ),
                None,
            )
            if project is None:
                results.append((False, f"GNS3 project '{project_name}': not found"))
            else:
                gns3_nodes_by_name = {
                    node.get("name"): node
                    for node in gns3_client.list_nodes(project["project_id"])
                }
                gns3_links = gns3_client.list_links(project["project_id"])

        if trunk_network_name is not None and resolved_vm_name is not None:
            vm = self.esxi_connection.get_vm(resolved_vm_name)
            if vm is None:
                results.append(
                    (False, f"Trunk NIC wiring: '{resolved_vm_name}' VM not found")
                )
            else:
                ok, description = self._trunk_network_wiring_status(
                    vm, trunk_network_name
                )
                results.append((ok, f"Trunk NIC wiring: {description}"))

        for name, node in nodes.items():
            if node.env == Environment.ON_GNS3:
                gns3_node = gns3_nodes_by_name.get(name)
                if gns3_node is None:
                    results.append((False, f"GNS3 node '{name}': not found in project"))
                elif gns3_node.get("status") == "started":
                    results.append((True, f"GNS3 node '{name}': started"))
                else:
                    results.append(
                        (
                            False,
                            f"GNS3 node '{name}': status is '{gns3_node.get('status')}'",
                        )
                    )
            elif node.env == Environment.ON_ESXI:
                vm = self.esxi_connection.get_vm(name)
                if vm is None:
                    results.append((False, f"ESXi VM '{name}': not found"))
                elif not self.esxi_connection.is_vm_powered_on(vm):
                    results.append((False, f"ESXi VM '{name}': not powered on"))
                else:
                    ip_address = self.esxi_connection.get_vm_ip_address(name)
                    if ip_address is None:
                        results.append(
                            (
                                False,
                                f"ESXi VM '{name}': powered on, but no IP reported yet",
                            )
                        )
                    else:
                        results.append(
                            (True, f"ESXi VM '{name}': powered on, IP {ip_address}")
                        )

        seen_edges = set()
        for node in nodes.values():
            for interface in node.interfaces.values():
                edge = interface.edge
                if edge is None or id(edge) in seen_edges:
                    continue
                seen_edges.add(id(edge))

                node_1, if_1 = edge.incidence_1.node, edge.incidence_1.name
                node_2, if_2 = edge.incidence_2.node, edge.incidence_2.name
                label = f"{node_1.name}:{if_1} <-> {node_2.name}:{if_2}"
                esxi_1 = node_1.env == Environment.ON_ESXI
                esxi_2 = node_2.env == Environment.ON_ESXI

                if esxi_1 and esxi_2:
                    vlan_1 = port_groups.get(edge.incidence_1.esxi_vlan)
                    vlan_2 = port_groups.get(edge.incidence_2.esxi_vlan)
                    if vlan_1 is None or vlan_2 is None:
                        results.append((False, f"{label}: a port group is missing"))
                    elif vlan_1 == vlan_2:
                        results.append((True, f"{label}: VLAN {vlan_1} on both sides"))
                    else:
                        results.append(
                            (False, f"{label}: VLAN mismatch ({vlan_1} vs {vlan_2})")
                        )
                elif esxi_1 or esxi_2:
                    esxi_interface = edge.incidence_1 if esxi_1 else edge.incidence_2
                    port_group_name = esxi_interface.esxi_vlan
                    if port_group_name not in port_groups:
                        results.append(
                            (
                                False,
                                f"{label}: ESXi port group '{port_group_name}' missing",
                            )
                        )
                    elif gns3_client is None:
                        results.append(
                            (
                                False,
                                f"{label}: cannot check Cloud node, GNS3 VM unreachable",
                            )
                        )
                    elif f"cloud-{port_group_name}" not in gns3_nodes_by_name:
                        results.append(
                            (
                                False,
                                f"{label}: Cloud node 'cloud-{port_group_name}' not found",
                            )
                        )
                    else:
                        results.append(
                            (True, f"{label}: bridged via '{port_group_name}'")
                        )
                else:
                    node_1_gns3 = gns3_nodes_by_name.get(node_1.name)
                    node_2_gns3 = gns3_nodes_by_name.get(node_2.name)
                    if node_1_gns3 is None or node_2_gns3 is None:
                        results.append(
                            (False, f"{label}: one or both GNS3 nodes not found")
                        )
                        continue
                    ids = {node_1_gns3.get("node_id"), node_2_gns3.get("node_id")}
                    linked = any(
                        {endpoint["node_id"] for endpoint in link["nodes"]} == ids
                        for link in gns3_links
                    )
                    results.append(
                        (
                            linked,
                            f"{label}: {'linked' if linked else 'no matching GNS3 link found'}",
                        )
                    )

        return results

    def generate_inventory(
        self,
        nodes: dict[str, GenericNode],
        project_name: str,
        vm_name: str | None = None,
    ) -> dict:
        """
        Generates an Ansible inventory from this topology's live state (see
        HANDOFF.md's Ansible expansion scoping for the design this
        implements). Requires the topology to already be deployed - this
        only reads live GNS3/ESXi state, it never deploys anything itself.
        Gathers exactly the same live state verify_topology does (GNS3 VM
        IP, project's nodes) plus each ESXi-hosted node's vSphere instance
        UUID, then delegates the actual inventory shape to
        inventory_generator.generate_ansible_inventory.
        :param nodes: built topology of the nodes
        :param project_name: name of the GNS3 project to read node state from
        :param vm_name: name of the GNS3 VM, or None to auto-detect
        :return: an ansible-inventory-compatible dict
        """
        gns3_ip_address = None
        gns3_nodes_by_name: dict[str, dict] = {}
        try:
            gns3_ip_address = self._get_gns3_vm_ip(vm_name)
        except (ConnectionError, ValueError) as error:
            logger.warning(f"Could not resolve the GNS3 VM: {error}")

        if gns3_ip_address is not None:
            client = GNS3Client(f"http://{gns3_ip_address}")
            project = next(
                (p for p in client.list_projects() if p.get("name") == project_name),
                None,
            )
            if project is None:
                logger.warning(f"GNS3 project '{project_name}' not found")
            else:
                gns3_nodes_by_name = {
                    node.get("name"): node
                    for node in client.list_nodes(project["project_id"])
                }

        vm_uuids_by_name: dict[str, str] = {}
        for name, node in nodes.items():
            if node.env != Environment.ON_ESXI:
                continue
            vm = self.esxi_connection.get_vm(name)
            if vm is not None:
                vm_uuids_by_name[name] = self.esxi_connection.get_vm_uuid(vm)

        return generate_ansible_inventory(
            nodes,
            gns3_ip_address,
            gns3_nodes_by_name,
            self.esxi_connection.ip_address,
            self.esxi_connection.username,
            vm_uuids_by_name,
        )
