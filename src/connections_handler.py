"""
Provides classes for connection types like SSH or the API connections to GNS3 and ESXi.
These classes have methods which can be used to operate these APIs.
"""

__license__ = "GNU GPLv3"

import atexit
import ipaddress
import re
import tarfile
import time
from abc import ABC, abstractmethod
from typing import Optional, Any

import paramiko
import ssl
import requests
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from pyVmomi.VmomiSupport import ManagedObject
from src.logger_adapter import get_logger
from src.settings import Settings

logger = get_logger(__name__)

# Proxy APIs in front of the two device catalogs (see technische_dokumentation_APIs):
# port 8000 fronts the NFS share of VM OVA images (the image source for role: VM
# nodes), port 8001 fronts a GNS3 server's own /v2/templates (the image source for
# every other role). Both are unauthenticated. These are only defaults - override
# via set_esxi_template_api_url/set_gns3_template_api_url (wired to CLI flags in
# cli.py) for a network where these services live somewhere else.
_ESXI_TEMPLATE_API_BASE_URL = "http://10.20.20.171:8000"
_GNS3_TEMPLATE_API_BASE_URL = "http://10.20.20.171:8001"
_OVA_DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_OVA_DOWNLOAD_MAX_ATTEMPTS = 3


def set_esxi_template_api_url(base_url: str) -> None:
    """
    Overrides the ESXi/NFS template-listing and OVA-download service's base
    URL for the rest of the process - the module-level default assumes a
    specific internal network. Every APIFunctions method that talks to this
    service reads the module-level global at call time, so calling this
    before any of them run (e.g. from the CLI's main() callback) is enough;
    no need to thread the URL through every call site.
    :param base_url: the new base URL, e.g. "http://10.20.20.171:8000"
    :return:
    """
    global _ESXI_TEMPLATE_API_BASE_URL
    _ESXI_TEMPLATE_API_BASE_URL = base_url


def set_gns3_template_api_url(base_url: str) -> None:
    """
    Overrides the GNS3 template-listing service's base URL for the rest of
    the process - see set_esxi_template_api_url for why this is a simple
    module-level override rather than a parameter threaded through every
    caller.
    :param base_url: the new base URL, e.g. "http://10.20.20.171:8001"
    :return:
    """
    global _GNS3_TEMPLATE_API_BASE_URL
    _GNS3_TEMPLATE_API_BASE_URL = base_url


class APIFunctions:
    """
    Provides various methods for API calls.
    """

    @staticmethod
    def _send_get_request(url: str) -> dict[str, Any] | str:
        """
        General method to make an API GET request
        :param url: API url
        :return:
        """
        logger.debug(f"GET {url}")
        response = requests.get(url)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def get_esxi_template_names():
        """
        Returns a set of available template names for ESXi
        :return:
        """
        if Settings.Testing.GithubWorkflow.LITERAL_API_VALUES:
            return Settings.Testing.GithubWorkflow.LITERAL_ESXI_TEMPLATES
        json = APIFunctions._send_get_request(
            f"{_ESXI_TEMPLATE_API_BASE_URL}/api/templates"
        )
        return {template["name"] for template in json["templates"]}

    @staticmethod
    def get_gns3_template_names():
        """
        Returns a set of available template names for GNS3
        :return:
        """
        if Settings.Testing.GithubWorkflow.LITERAL_API_VALUES:
            return Settings.Testing.GithubWorkflow.LITERAL_GNS3_TEMPLATES
        json = APIFunctions._send_get_request(
            f"{_GNS3_TEMPLATE_API_BASE_URL}/api/templates"
        )
        return {template["name"] for template in json["templates"]}

    @staticmethod
    def download_esxi_template(name: str, dest_path: str) -> None:
        """
        Downloads the OVA file for the NFS-share template whose name/tags
        best match `name` (server-side fuzzy match against templates.yml,
        proxied from the Filebrowser-backed NFS share - see
        technische_dokumentation_APIs section 2.3) to dest_path. Streamed in
        chunks, since these OVAs run into multiple gigabytes.

        The proxy's upstream connection to Filebrowser/NFS has been observed
        to drop mid-transfer without that surfacing as an HTTP-level error -
        the response still looks like a normal 200 completion, just with a
        truncated body. Since a truncated .ova otherwise only fails much
        later with a confusing error deep inside the OVF import, every
        download is verified to be a structurally complete tar archive
        before being accepted, with a few retries since this has been
        observed to be intermittent.
        :param name: template name to search for, e.g. a topology node's image
        :param dest_path: local filesystem path to write the OVA to
        :return:
        """
        last_error: Exception | None = None
        for attempt in range(1, _OVA_DOWNLOAD_MAX_ATTEMPTS + 1):
            logger.debug(
                f"Downloading ESXi template '{name}' to {dest_path} "
                f"(attempt {attempt}/{_OVA_DOWNLOAD_MAX_ATTEMPTS})"
            )
            response = requests.get(
                f"{_ESXI_TEMPLATE_API_BASE_URL}/api/download",
                params={"name": name},
                stream=True,
            )
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=_OVA_DOWNLOAD_CHUNK_SIZE):
                    f.write(chunk)

            try:
                with tarfile.open(dest_path) as archive:
                    archive.getmembers()
            except tarfile.TarError as error:
                last_error = error
                logger.warning(
                    f"Downloaded OVA for '{name}' is incomplete or corrupt "
                    f"({error}); retrying ({attempt}/{_OVA_DOWNLOAD_MAX_ATTEMPTS})"
                )
                continue

            logger.info(f"Downloaded ESXi template '{name}' to {dest_path}")
            return

        raise logger.alert(
            RuntimeError,
            f"Failed to download a complete OVA for '{name}' after "
            f"{_OVA_DOWNLOAD_MAX_ATTEMPTS} attempts: {last_error}",
        )


class GenericConnection(ABC):
    def __init__(self, ip_address: str, username: str, password: str | None) -> None:
        """
        :param ip_address: IP address of the instance
        :param username: Hosts username
        :param password: corresponding password for user
        """
        ipaddress.ip_address(ip_address)

        self._ip_address = ip_address
        self._username = username
        self._password = password

        self._connection = self.connect()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    @property
    def ip_address(self) -> str:
        return self._ip_address

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str | None:
        return self._password

    @property
    def connection(self):
        return self._connection

    @abstractmethod
    def connect(self) -> None:
        pass


class SSHConnection(GenericConnection, paramiko.SSHClient):
    def connect(self) -> paramiko.SSHClient:
        """
        Connect to an SSH server.
        :return: Returns the client
        """
        logger.debug(f"Opening SSH connection to {self.ip_address} as {self.username}")
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=self.ip_address,
            port=22,
            username=self.username,
            password=self.password,
            timeout=10,
        )
        logger.debug(f"SSH connection to {self.ip_address} established")

        return client


class GNS3Connection(GenericConnection):
    def connect(self):
        pass


# Matches the backup-name suffix VMOrchestrator.deploy_fresh_gns3_vm gives a
# replaced VM (f"{vm_name}-backup-{datetime.now():%Y%m%d%H%M%S}") - used to
# keep find_gns3_vm() from mistaking a backup for the live GNS3 VM, since a
# backup's name still contains the original name (and so still matches
# "gns3") but must never be auto-detected as the VM to use/replace.
_BACKUP_VM_NAME_PATTERN = re.compile(r"-backup-\d{14}")


class ESXiConnection(GenericConnection):
    def __init__(self, ip_address: str, username: str, password: str | None):
        super().__init__(ip_address, username, password)

        self.content: vim.ServiceInstanceContent = self.connection.RetrieveContent()

    def connect(self) -> vim.ServiceInstance:
        """
        Connect to the ESXi API.
        :return: Returns the client
        """
        logger.debug(
            f"Opening ESXi API connection to {self.ip_address} as {self.username}"
        )
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        try:
            instance = SmartConnect(
                host=self.ip_address,
                user=self.username,
                pwd=self.password,
                port=443,
                sslContext=ssl_context,
            )
        except vim.fault.VimFault as fault:
            # Re-raised as a plain exception rather than left as the raw
            # pyVmomi fault object: Typer's pretty-traceback renderer
            # crashes trying to attach its own debug attribute to it
            # (pyVmomi's DataObject.__setattr__ rejects unknown attributes),
            # turning a simple "wrong password" into a confusing wall of
            # unrelated errors instead of a clean, actionable message.
            raise logger.alert(
                ConnectionError,
                f"Failed to connect to ESXi host {self.ip_address} as "
                f"'{self.username}': {fault.msg}",
            ) from None
        logger.debug(f"ESXi API connection to {self.ip_address} established")

        atexit.register(Disconnect, instance)
        return instance

    def get_vm(self, vm_name: str) -> Optional[ManagedObject]:
        """
        Searches for a VM with given name.
        :param vm_name: Name of VM to look for
        :return: Returns Virtual Machine if found, else None
        """
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )

        try:
            for vm in container_view.view:
                if vm.name == vm_name:
                    return vm
        finally:
            container_view.Destroy()

        return None

    def find_gns3_vm(self) -> Optional[ManagedObject]:
        """
        Searches for a VM that looks like a typical GNS3 VM, i.e. one whose
        name contains 'gns3' (case-insensitive) - used to resolve the GNS3
        VM automatically when no explicit name is given, since real-world
        GNS3 VM names vary (e.g. 'GNS3', 'GNS3-VM'). Backup VMs (renamed by
        deploy_fresh_gns3_vm before replacing the original) are excluded,
        even though their name still contains the original name - a backup
        must never be auto-detected as the live VM to use or replace.
        :return: the matching VM if exactly one was found, else None
        """
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            matches = [
                vm
                for vm in container_view.view
                if "gns3" in vm.name.lower()
                and not _BACKUP_VM_NAME_PATTERN.search(vm.name)
            ]
        finally:
            container_view.Destroy()

        if len(matches) > 1:
            names = [vm.name for vm in matches]
            raise logger.alert(
                ValueError,
                f"Multiple VMs look like a GNS3 VM: {names}. Specify "
                f"--gns3-vm-name to disambiguate.",
            )
        return matches[0] if matches else None

    def find_vms_matching(self, name: str) -> list[ManagedObject]:
        """
        Finds every VM whose name exactly matches `name`, or looks like an
        auto-renamed duplicate of it (ESXi appends e.g. '_1' or ' (1)' when
        an import collides with an existing VM's name). Used to clean up
        VMs left over from an earlier deploy of a topology node before
        redeploying it, so redeploys don't accumulate duplicates.
        :param name: the node name to match against
        :return: list of matching VMs
        """
        pattern = re.compile(rf"^{re.escape(name)}([ _]\(?\d+\)?)?$")
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            return [vm for vm in container_view.view if pattern.match(vm.name)]
        finally:
            container_view.Destroy()

    def get_vm_ip_address(self, vm_name: str) -> Optional[str]:
        """
        Returns the first IPv4 Address it finds on the VM with given name.
        Ignores loopback, link locals and multicast addresses.
        :param vm_name: Name of VM to look on
        :return: IPv4 Address if found, else None.
        """
        vm = self.get_vm(vm_name)
        for nic in [] if vm is None else vm.guest.net:
            for address in nic.ipAddress or []:
                try:
                    parsed = ipaddress.ip_address(address)
                except ValueError:
                    continue

                if parsed.version != 4:
                    continue

                if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast:
                    continue
                return address
        return None

    def get_host_system(self) -> vim.HostSystem:
        """
        Returns the ESXi host system. Assumes a standalone host connection
        (one datacenter, one compute resource, one host), which is what
        SmartConnect gives us when connecting directly to an ESXi host rather
        than through vCenter.
        :return: the ESXi HostSystem
        """
        datacenter = self.content.rootFolder.childEntity[0]
        compute_resource = datacenter.hostFolder.childEntity[0]
        return compute_resource.host[0]

    def ensure_port_group(
        self, name: str, vlan_id: int, vswitch_name: str = "vSwitch0"
    ) -> None:
        """
        Ensures a port group with the given name and VLAN ID exists on the
        ESXi host's vSwitch, creating it if it's missing. Used to keep the
        ESXi vSwitch in sync with the GNS3 VM's VLAN subinterfaces, so ESXi
        VMs' vNICs on this port group reach the matching GNS3 topology link.
        :param name: name of the port group, also used as its identifying label
        :param vlan_id: VLAN ID to tag the port group with
        :param vswitch_name: name of the vSwitch to attach the port group to
        :return:
        """
        network_system = self.get_host_system().configManager.networkSystem
        existing_names = {
            portgroup.spec.name for portgroup in network_system.networkInfo.portgroup
        }
        if name in existing_names:
            return

        port_group_spec = vim.host.PortGroup.Specification()
        port_group_spec.name = name
        port_group_spec.vlanId = vlan_id
        port_group_spec.vswitchName = vswitch_name
        port_group_spec.policy = vim.host.NetworkPolicy()

        network_system.AddPortGroup(portgrp=port_group_spec)
        logger.info(
            f"Created ESXi port group '{name}' (VLAN {vlan_id}) on {vswitch_name}"
        )

    def ensure_bridging_security_policy(self, name: str) -> None:
        """
        Ensures an existing port group accepts promiscuous mode, MAC address
        changes, and forged transmits - required for a port group whose VM
        relays traffic for MAC addresses other than its own vNIC's, e.g. the
        GNS3 VM's trunk NIC, which GNS3's Cloud nodes use to bridge in
        arbitrary topology devices' own MACs. ESXi's default security policy
        rejects promiscuous mode and forged transmits, which silently drops
        all such relayed traffic without any visible error on either side.
        :param name: name of an existing port group to update
        :return:
        """
        network_system = self.get_host_system().configManager.networkSystem
        port_group = next(
            (pg for pg in network_system.networkInfo.portgroup if pg.spec.name == name),
            None,
        )
        if port_group is None:
            raise logger.alert(ValueError, f"Port group '{name}' not found")

        spec = port_group.spec
        spec.policy = spec.policy or vim.host.NetworkPolicy()
        security = spec.policy.security or vim.host.NetworkPolicy.SecurityPolicy()
        if (
            security.allowPromiscuous
            and security.macChanges
            and security.forgedTransmits
        ):
            return

        security.allowPromiscuous = True
        security.macChanges = True
        security.forgedTransmits = True
        spec.policy.security = security

        network_system.UpdatePortGroup(pgName=name, portgrp=spec)
        logger.info(
            f"Enabled promiscuous mode, MAC changes, and forged transmits on "
            f"port group '{name}'"
        )

    def delete_port_group(self, name: str) -> None:
        """
        Deletes the named port group if it exists. Used to clear out a port
        group left over from an earlier deploy before recreating it, so a
        stale VLAN ID from a previous topology layout can't linger under
        the same name - AddPortGroup/ensure_port_group only skips creation
        if a port group with that name already exists, without checking
        whether its VLAN ID is still correct. Requires no VM to still be
        using the port group.
        :param name: name of the port group to delete
        :return:
        """
        network_system = self.get_host_system().configManager.networkSystem
        existing_names = {
            portgroup.spec.name for portgroup in network_system.networkInfo.portgroup
        }
        if name not in existing_names:
            return

        network_system.RemovePortGroup(pgName=name)
        logger.info(f"Deleted stale ESXi port group '{name}'")

    def list_port_groups(self) -> list[dict[str, str | int]]:
        """
        Lists the port groups configured on the ESXi host's vSwitches.
        :return: list of {"name", "vlan_id", "vswitch"} dicts
        """
        network_system = self.get_host_system().configManager.networkSystem
        return [
            {
                "name": portgroup.spec.name,
                "vlan_id": portgroup.spec.vlanId,
                "vswitch": portgroup.spec.vswitchName,
            }
            for portgroup in network_system.networkInfo.portgroup
        ]

    def find_datastore(self, name: str) -> vim.Datastore:
        """
        Finds a datastore by name.
        :param name: name of the datastore
        :return: the matching Datastore
        """
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Datastore], True
        )
        try:
            for datastore in container_view.view:
                if datastore.name == name:
                    return datastore
        finally:
            container_view.Destroy()
        raise logger.alert(ValueError, f"Datastore '{name}' not found")

    def find_network(self, name: str) -> vim.Network:
        """
        Finds a network (port group) by name.
        :param name: name of the port group
        :return: the matching Network
        """
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Network], True
        )
        try:
            for network in container_view.view:
                if network.name == name:
                    return network
        finally:
            container_view.Destroy()
        raise logger.alert(ValueError, f"Network/port group '{name}' not found")

    @staticmethod
    def _wait_for_task(task: vim.Task) -> None:
        """
        Blocks until the given vSphere task finishes, raising if it errors out.
        :param task: the task to wait for
        :return:
        """
        while task.info.state not in (
            vim.TaskInfo.State.success,
            vim.TaskInfo.State.error,
        ):
            time.sleep(0.5)
        if task.info.state == vim.TaskInfo.State.error:
            raise logger.alert(RuntimeError, f"vSphere task failed: {task.info.error}")

    def get_vm_mac_address(self, vm: vim.VirtualMachine) -> Optional[str]:
        """
        Returns the MAC address of the VM's first Ethernet network adapter.
        :param vm: the VM to inspect
        :return: MAC address string, or None if it has no network adapter
        """
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                return device.macAddress
        return None

    def get_vm_network_names(self, vm: vim.VirtualMachine) -> list[str]:
        """
        Returns the ESXi port group name each of the VM's Ethernet network
        adapters is currently connected to, in device order. Used to verify
        a NIC is actually wired to an expected port group before trusting
        traffic sent to it - ESXi gives no error or warning for a NIC left
        connected to the wrong port group (e.g. after a manual edit, or a
        botched --fresh-gns3-vm import), it just silently doesn't carry the
        traffic anyone expects it to.
        :param vm: the VM to inspect
        :return: list of port group names, one per Ethernet adapter
        """
        names = []
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                names.append(getattr(device.backing, "deviceName", None))
        return names

    def set_vm_mac_address(self, vm: vim.VirtualMachine, mac_address: str) -> None:
        """
        Sets the MAC address of the VM's first Ethernet network adapter to a
        fixed, manually-assigned value.
        :param vm: the VM to reconfigure
        :param mac_address: MAC address to assign
        :return:
        """
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                device.macAddress = mac_address
                device.addressType = "manual"
                device_spec = vim.vm.device.VirtualDeviceSpec(
                    operation=vim.vm.device.VirtualDeviceSpec.Operation.edit,
                    device=device,
                )
                config_spec = vim.vm.ConfigSpec(deviceChange=[device_spec])
                self._wait_for_task(vm.ReconfigVM_Task(spec=config_spec))
                return
        raise logger.alert(
            ValueError, f"VM '{vm.name}' has no network adapter to set a MAC on"
        )

    def add_vm_network_adapters(
        self, vm: vim.VirtualMachine, network_names: list[str]
    ) -> None:
        """
        Adds a new network adapter to the VM for each given port group, in
        order. Used when an OVA declares fewer networks than the VM
        ultimately needs, e.g. a single-NIC GNS3 OVA that still needs a
        second, trunk NIC added on top after import.
        :param vm: the VM to add adapters to
        :param network_names: ESXi port group name for each adapter to add, in order
        :return:
        """
        device_changes = []
        for network_name in network_names:
            device = vim.vm.device.VirtualVmxnet3()
            device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
                network=self.find_network(network_name), deviceName=network_name
            )
            device.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
                startConnected=True, connected=True, allowGuestControl=True
            )
            device_changes.append(
                vim.vm.device.VirtualDeviceSpec(
                    operation=vim.vm.device.VirtualDeviceSpec.Operation.add,
                    device=device,
                )
            )

        config_spec = vim.vm.ConfigSpec(deviceChange=device_changes)
        self._wait_for_task(vm.ReconfigVM_Task(spec=config_spec))
        logger.info(f"Added network adapter(s) to VM '{vm.name}' for: {network_names}")

    def power_off_vm(self, vm: vim.VirtualMachine) -> None:
        """
        Powers off the given VM, if it isn't already.
        :param vm: the VM to power off
        :return:
        """
        if vm.runtime.powerState != vim.VirtualMachine.PowerState.poweredOff:
            self._wait_for_task(vm.PowerOffVM_Task())

    def delete_vm(self, vm: vim.VirtualMachine) -> None:
        """
        Powers off (if needed) and permanently deletes the given VM. Used
        to clean up a VM left over from an earlier deploy before
        redeploying it, so redeploys don't accumulate duplicate/renamed VMs.
        :param vm: the VM to delete
        :return:
        """
        self.power_off_vm(vm)
        self._wait_for_task(vm.Destroy_Task())

    def power_on_vm(self, vm: vim.VirtualMachine) -> None:
        """
        Powers on the given VM, if it isn't already.
        :param vm: the VM to power on
        :return:
        """
        if vm.runtime.powerState != vim.VirtualMachine.PowerState.poweredOn:
            self._wait_for_task(vm.PowerOnVM_Task())

    def rename_vm(self, vm: vim.VirtualMachine, new_name: str) -> None:
        """
        Renames the given VM.
        :param vm: the VM to rename
        :param new_name: new name for the VM
        :return:
        """
        self._wait_for_task(vm.Rename_Task(newName=new_name))
