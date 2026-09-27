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
from datetime import datetime
from typing import Callable

from loguru import logger

from src.connections.esxi_connection import ESXiConnection
from src.ova_importer import OVAImporter

_IP_WAIT_POLL_INTERVAL_SECONDS = 5


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
        Must be the OVA's FIRST-added network adapter.
    :param trunk_network_name: ESXi port group for the new VM's VLAN trunk
        NIC. Must be the OVA's SECOND-added network adapter.
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
    :return: IP address of the new GNS3 VM
    :raises TimeoutError: if the new VM never reports an IP within
        ip_wait_timeout_seconds - the old VM (if any) is left as its
        renamed backup, never deleted, regardless of delete_old_vm.
    """

    def stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    old_vm = esxi_connection.get_vm(vm_name)
    old_mac_address = None
    if old_vm is not None:
        old_mac_address = esxi_connection.get_vm_mac_address(old_vm)
        stage("powering off existing VM")
        logger.info(f"Powering off existing '{vm_name}' VM")
        esxi_connection.power_off_vm(old_vm)
        backup_name = f"{vm_name}-backup-{datetime.now():%Y%m%d%H%M%S}"
        esxi_connection.rename_vm(old_vm, backup_name)
        logger.info(f"Renamed existing '{vm_name}' VM to '{backup_name}'")

    stage("importing OVA")
    importer = OVAImporter(esxi_connection)
    new_vm = importer.import_ova(
        ova_path,
        vm_name,
        datastore_name,
        [mgmt_network_name, trunk_network_name],
    )

    if old_mac_address is not None:
        esxi_connection.set_vm_mac_address(new_vm, old_mac_address)
        logger.info(f"Set new '{vm_name}' VM's MAC to {old_mac_address}")

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
                logger.info(f"Deleting old '{vm_name}' VM (backed up as '{backup_name}')")
                esxi_connection.delete_vm(old_vm)
            return ip_address
        time.sleep(_IP_WAIT_POLL_INTERVAL_SECONDS)

    logger.error(
        msg := f"'{vm_name}' VM did not report an IP address within {ip_wait_timeout_seconds}s"
    )
    raise TimeoutError(msg)
