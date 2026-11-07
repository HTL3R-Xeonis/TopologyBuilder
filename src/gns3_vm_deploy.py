"""
Deploys a fresh GNS3 VM from an OVA - the one-time (or disaster-recovery)
provisioning step neither `deploy` nor TopologyOperator's own live
operations otherwise perform: both treat the GNS3 VM as a prerequisite
that must already exist, and just error out if it doesn't (see
VMOrchestrator.__init__). Kept as a standalone function taking an
already-connected ESXiConnection, deliberately outside VMOrchestrator,
since VMOrchestrator's own constructor requires the GNS3 VM to already
exist - exactly the situation this function exists to fix.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from loguru import logger
from pyVmomi import vmodl

from src.connections.api_handler import APIHandler
from src.connections.esxi_connection import ESXiConnection
from src.mac_range import mac_in_range, pick_mac_in_range
from src.ova_importer import OVAImporter
from src.settings import Settings

_IP_WAIT_POLL_INTERVAL_SECONDS = 5

# What a freshly deployed GNS3 VM gets, whatever the OVA itself declares (the stock
# GNS3 VM OVA comes with 1 vCPU / 2 GB, far too little for a handful of IOSv nodes).
DEFAULT_GNS3_VM_CPUS = 4
DEFAULT_GNS3_VM_MEMORY_MB = 8192


def _set_autostart(
    esxi_connection: ESXiConnection, vm: object, vm_name: str, enabled: bool
) -> None:
    """Starts the VM with its ESXi host (or stops doing so). Never fails the deploy: it is a convenience on top of it."""
    try:
        esxi_connection.set_vm_autostart(vm, enabled)
        logger.info(
            f"'{vm_name}' VM {'starts' if enabled else 'no longer starts'} with the ESXi host"
        )
    except (RuntimeError, ConnectionError, vmodl.MethodFault) as exc:
        logger.warning(f"Could not change the autostart of '{vm_name}' VM: {exc}")


def deploy_fresh_gns3_vm(
    esxi_connection: ESXiConnection,
    vm_name: str,
    ova_path: str,
    datastore_name: str,
    mgmt_network_name: str,
    trunk_network_name: str,
    ip_wait_timeout_seconds: int = 300,
    on_stage: Callable[[str], None] | None = None,
    delete_old_vm: bool = False,
    mac_range: tuple[str, str] | None = None,
    ova_filename: str | None = None,
    cpus: int = DEFAULT_GNS3_VM_CPUS,
    memory_mb: int = DEFAULT_GNS3_VM_MEMORY_MB,
) -> str:
    """
    Replaces the GNS3 VM named ``vm_name`` with a freshly imported one from
    the given OVA. An existing VM by that name (if any) is powered off and
    renamed as a timestamped backup rather than deleted immediately. The
    new VM's management NIC gets the old VM's MAC address, so a DHCP
    server that hands out addresses by MAC (reservation, or a not-yet-
    expired lease) gives the new VM the same IP as the old one. This does
    NOT work if the GNS3 VM's IP is a static address configured inside
    the guest OS.
    :param esxi_connection: an already-connected ESXi session
    :param vm_name: name the new (and previous, if any) GNS3 VM should have
    :param ova_path: local filesystem path to the GNS3 OVA (an NFS share
        mounted locally works fine here, it's just a path)
    :param datastore_name: ESXi datastore to place the new VM on
    :param mgmt_network_name: ESXi port group for the new VM's management NIC.
        Must be the OVA's FIRST-added network adapter. Not auto-created if
        missing - unlike trunk_network_name below, this is an externally-
        managed network with no safe default to create it with, so a
        missing one still fails loudly (ValueError from find_network).
    :param trunk_network_name: ESXi port group for the new VM's VLAN trunk
        NIC. Must be the OVA's SECOND-added network adapter. Auto-created
        (with its vSwitch, if that's missing too) if it doesn't exist yet
        - the same bootstrapping VMOrchestrator's own deploy path already
        does, needed here too since this can run before any topology has
        ever been deployed to this host.
    :param ip_wait_timeout_seconds: how long to wait for the new VM to report an IP
    :param on_stage: optional callback invoked with a short human-readable
        stage name at each major step (e.g. for a caller to surface
        coarse progress - there's no real percentage available, the OVA
        upload's own byte-level progress isn't threaded back out here)
    :param delete_old_vm: when True and an existing same-named VM was
        found, permanently deletes it (see ESXiConnection.delete_vm)
        once - and only once - the new VM has confirmed itself alive by
        reporting an IP address. Deliberately never attempted before
        that point: if the new VM never comes up (ip_wait_timeout_seconds
        elapses, TimeoutError below), the old VM is left exactly as its
        powered-off, renamed backup - the whole point of that safety net
        is a path back to a known-working VM, which permanently deleting
        it before the replacement is proven working would defeat.
    :param ova_filename: when given, the OVA is NOT read from ``ova_path`` but
        imported by the OVA deploy service (``Settings.API.OVA_DEPLOY_URL``)
        straight from its NFS share onto the ESXi host - no multi-GB download
        or upload hop on this machine, thin provisioned. This is the exact
        filename on that share (the template catalog's ``file`` field). The
        service builds the VM's NICs itself from an ordered mapping, so the
        first one is the management NIC and the second the trunk NIC, same
        as the local importer's order.
    :param mac_range: (start_mac, end_mac) - if given, the new VM's
        management NIC gets a MAC address from this inclusive range
        instead of the old VM's own MAC (e.g. so a DHCP server can be
        configured to only hand out addresses to MACs in this range).
        If the old VM's own MAC already falls within the range, it's
        kept as-is (preserves the same DHCP-leased IP across a
        redeploy, same as when mac_range isn't given at all) - a fresh
        MAC is only picked when there's no old VM, or its MAC falls
        outside the range. The picked MAC avoids every other VM
        currently on the host, but does NOT check anything outside
        this ESXi host (e.g. a real device out in the lab already using
        a MAC in this range) - keep the range dedicated to VMs this
        tool manages.
    :param cpus: number of virtual CPUs the new VM gets (default 4), set after
        the import and before the VM is powered on
    :param memory_mb: memory the new VM gets in MB (default 8192 = 8 GB)
    :return: IP address of the new GNS3 VM
    :raises TimeoutError: if the new VM never reports an IP within
        ip_wait_timeout_seconds - the old VM (if any) is left as its
        renamed backup, never deleted, regardless of delete_old_vm.
    """

    def stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    # A real, self-correctable failure mode: on a genuinely fresh ESXi
    # host (nothing deployed yet, or after a vSwitch reset), the trunk
    # network this VM needs doesn't exist yet, and OVAImporter.import_ova
    # would otherwise fail with a plain ValueError from find_network -
    # this project already owns and knows how to (re)create both the
    # vSwitch and the trunk port group (see VMOrchestrator's own
    # bootstrapping), so do that here too rather than requiring it to
    # already exist. Both are no-ops if already present. Deliberately
    # NOT done for mgmt_network_name: that's an externally-managed
    # network (e.g. the lab's real management VLAN) this project has no
    # business creating or guessing settings for - a missing mgmt
    # network still fails loudly via find_network, as it should.
    stage("ensuring trunk network exists")
    esxi_connection.ensure_virtual_switch_exists()
    esxi_connection.ensure_trunk_port_group_exists()

    old_vm = esxi_connection.get_vm(vm_name)
    old_mac_address = None
    if old_vm is not None:
        old_mac_address = esxi_connection.get_vm_mac_address(old_vm)
        stage("powering off existing VM")
        logger.info(f"Powering off existing '{vm_name}' VM")
        esxi_connection.power_off_vm(old_vm)
        backup_name = f"{vm_name}-backup-{datetime.now().astimezone():%Y%m%d%H%M%S}"
        esxi_connection.rename_vm(old_vm, backup_name)
        logger.info(f"Renamed existing '{vm_name}' VM to '{backup_name}'")
        # The backup keeps the old VM's autostart entry (it belongs to the VM, not to the name): without this the host
        # would start it next to the new VM after a restart, with the same MAC address.
        _set_autostart(esxi_connection, old_vm, backup_name, enabled=False)

    stage("importing OVA")
    if ova_filename is not None:
        # Order matters: dict order = NIC order (management first, then trunk).
        APIHandler.deploy_ova(
            Settings.ESXI.IP,
            Settings.ESXI.PORT,
            vm_name,
            ova_filename,
            datastore_name,
            {"management": mgmt_network_name, "trunk": trunk_network_name},
        )
        new_vm = esxi_connection.get_vm(vm_name)
        if new_vm is None:
            raise RuntimeError(
                f"The OVA deploy service reported success, but no VM '{vm_name}' "
                f"exists on the ESXi host"
            )
    else:
        importer = OVAImporter(esxi_connection)
        new_vm = importer.import_ova(
            ova_path,
            vm_name,
            datastore_name,
            [mgmt_network_name, trunk_network_name],
        )

    final_mac_address = old_mac_address
    if mac_range is not None:
        range_start, range_end = mac_range
        if old_mac_address is None or not mac_in_range(
            old_mac_address, range_start, range_end
        ):
            stage("assigning a MAC address from the configured range")
            excluded = {
                mac
                for mac in (
                    esxi_connection.get_vm_mac_address(vm)
                    for vm in esxi_connection.get_all_vms()
                )
                if mac is not None
            }
            final_mac_address = pick_mac_in_range(range_start, range_end, excluded)
            logger.info(
                f"Assigning '{vm_name}' VM a MAC from the configured range: {final_mac_address}"
            )

    if final_mac_address is not None:
        esxi_connection.set_vm_mac_address(new_vm, final_mac_address)
        logger.info(f"Set new '{vm_name}' VM's MAC to {final_mac_address}")

    stage("setting CPU and memory")
    logger.info(f"Setting '{vm_name}' VM to {cpus} vCPU(s) and {memory_mb} MB memory")
    esxi_connection.set_vm_resources(new_vm, cpus, memory_mb)

    # After a host restart nothing comes back by itself, so the new GNS3 VM starts with the host.
    _set_autostart(esxi_connection, new_vm, vm_name, enabled=True)

    stage("powering on")
    logger.info(f"Powering on '{vm_name}' VM")
    esxi_connection.power_on_vm(new_vm)

    stage("waiting for an IP address")
    logger.debug(f"Waiting for '{vm_name}' VM to report an IP address")
    deadline = time.monotonic() + ip_wait_timeout_seconds
    while time.monotonic() < deadline:
        ip_address = esxi_connection.get_vm_ip_address(vm_name)
        if ip_address is not None:
            logger.info(f"'{vm_name}' VM is up at {ip_address}")
            if delete_old_vm and old_vm is not None:
                stage("deleting old VM")
                logger.info(
                    f"Deleting old '{vm_name}' VM (backed up as '{backup_name}')"
                )
                esxi_connection.delete_vm(old_vm)
            return ip_address
        time.sleep(_IP_WAIT_POLL_INTERVAL_SECONDS)

    logger.error(
        msg
        := f"'{vm_name}' VM did not report an IP address within {ip_wait_timeout_seconds}s"
    )
    raise TimeoutError(msg)
