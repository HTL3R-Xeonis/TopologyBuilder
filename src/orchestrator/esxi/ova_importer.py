from __future__ import annotations

import io
import tarfile
import time

import requests
from loguru import logger
from pyVmomi import vim

from src.connections import APIHandler, ESXiConnection
from src.graph.blocks import GenericNode


class HTTPRangeFile(io.RawIOBase):
    """
    Wrapper class to make the remote-file easier to read and jump around.
    """

    def __init__(self, url: str, headers: dict | None = None, timeout: int = 30):
        """
        :param url: URL to the file to be read.
        :param headers: Header to create with the session to the url
        :param timeout: Seconds until timeout
        """
        super().__init__()

        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.session = requests.Session()
        self.pos = 0

        with self.session.head(
            self.url, headers=self.headers, timeout=self.timeout, allow_redirects=True
        ) as r:
            r.raise_for_status()

            content_length = r.headers.get("Content-Length")

            if content_length is None:
                raise RuntimeError(
                    "HTTP-server does not return a content-length header."
                )
            self.size = int(content_length)

    def readable(self) -> bool:
        """
        Determines if this object is readable.
        :return: Returns always True.
        """
        return True

    def seekable(self) -> bool:
        """
        Determines whether jumping backwards and forwards is possible in this IO-Object.
        :return: Returns always True.
        """
        return True

    def tell(self) -> int:
        """
        Determines the current position of the file-pointer in the IO-Object.
        :return:
        """
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET) -> int:
        """
        Move the file-pointer in the IO-Object.
        :param offset: absolut or relativ position depending on ``whence``.
        :param whence: Specify what to do with the offset.
        :return:
        """
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self.pos + offset
        elif whence == io.SEEK_END:
            new_pos = self.size + offset
        else:
            raise ValueError("Invalid whence-value")

        if new_pos < 0:
            raise ValueError("Negativ position")

        self.pos = new_pos
        return self.pos

    def read(self, size: int | None = -1) -> bytes:
        """
        Read ``size``-many bytes from the IO-Object.
        :param size: How much to read from the IO-Object.
        :return:
        """
        if self.pos >= self.size:
            return b""

        if size is None or size < 0:
            size: int = self.size - self.pos

        size = min(size, self.size - self.pos)

        if size == 0:
            return b""

        start = self.pos
        end = start + size - 1

        headers = dict(self.headers)
        headers["Range"] = f"bytes={start}-{end}"

        with self.session.get(
            self.url,
            headers=headers,
            stream=True,
            timeout=self.timeout,
            allow_redirects=True,
        ) as r:
            if r.status_code != 206:
                raise RuntimeError(
                    f"Range Request {start}-{end}. Status code: {r.status_code}"
                )

            data = r.raw.read(size)

        self.pos += len(data)
        return data

    def close(self) -> None:
        """
        Closes the session of the remote IO-Object.
        :return:
        """
        if not self.closed:
            self.session.close()
        super().close()


class OvaImporter:
    """
    Handles the OVA import to the ESXi host.
    """

    def __init__(
        self,
        esxi_connection: ESXiConnection,
        node: GenericNode,
        datastore: vim.Datastore,
        network_mapping: dict[str, str],
        disk_provisioning: str = "thin",
    ):
        """
        :param esxi_connection: API connection to the ESXi host.
        :param node: Node to deploy on the ESXi host.
        :param datastore: Datastore where the virtual machine is stored.
        :param network_mapping: A mapping of the interface names, from the vm, to the portgroups names.
        :param disk_provisioning: Method of disk provisioning.
        """
        self.esxi_connection = esxi_connection
        self._node = node
        self._datastore = datastore
        self._network_mapping = network_mapping
        self._disk_provisioning = disk_provisioning
        self._ova_url = self._get_ova_url(self._node.image)

    @staticmethod
    def _get_ova_url(image_name: str) -> str:
        """
        Determines the URL to the OVA file.
        :param image_name: Name of the image to search for.
        :return: The URL to the OVA file.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        return "http://10.20.20.181:80/" + APIHandler.get_ova(image_name)

    @staticmethod
    def _get_ovf_member(members: list[tarfile.TarInfo]) -> tarfile.TarInfo:
        """
        Finds the OVF member within in OVA file and returns it.
        :param members: All members of the OVA file.
        :return: Returns the OVF member.
        :raises RuntimeError: Is thrown when no ovf member was wound
        """
        ovf_member = next(
            (m for m in members if m.isfile() and m.name.lower().endswith(".ovf")), None
        )
        if ovf_member is None:
            raise RuntimeError("No ovf member found.")
        return ovf_member

    def _read_ova_metadata(self, url, headers=None) -> dict[str, str | set[str]]:
        """
        Determines the ovf descriptor and all members of the ova-file.
        :param url: URL to the remote OVA file.
        :param headers: Headers to open with the remote OVA file.
        :return: Returns a dictionary containing the descriptor, ovf member name and all the other member names.
        :raises RuntimeError: Is thrown when the ovf could not be opened.
        """
        with (
            HTTPRangeFile(url, headers=headers) as remote,
            tarfile.open(
                fileobj=remote,
                mode="r:",  # r: = TAR with Seek-Support
            ) as tf,
        ):
            members = tf.getmembers()
            ovf_member = self._get_ovf_member(members)

            f = tf.extractfile(ovf_member)

            if f is None:
                raise RuntimeError("Could not open the OVF descriptor.")
            ovf_bytes = f.read()
            ovf_descriptor = ovf_bytes.decode("utf-8-sig")

            member_names = {m.name for m in members if m.isfile()}

        return {
            "descriptor": ovf_descriptor,
            "ovf_member": ovf_member.name,
            "members": member_names,
        }

    def _raise_if_not_supports_pull_mode(self, lease: vim.HttpNfcLease) -> None:
        """
        Checks whether the ESXi host supports the pull mode for ova deployment.
        :param lease: Running lease to the ESXi host.
        :return:
        """
        if not lease.capabilities.pullModeSupported:
            logger.error(
                msg
                := f"This ESXi host ({self.esxi_connection.ip}) does not support pull mode."
            )
            raise RuntimeError(msg)

    def _get_nfc_lease_source_files(
        self,
        lease: vim.HttpNfcLease,
        import_spec_result: vim.HttpNfcLease.CreateImportSpecResult,
    ) -> list[vim.HttpNfcLease.SourceFile]:
        """
        Determines the needed members the ESXi host needs to pull.
        :param lease: Running lease to the ESXi host.
        :param import_spec_result: Import spec result from the ovf descriptor.
        :return: Returns a list of Sourcefiles which the ESXi host needs to pull.
        :raises RuntimeError: Is thrown when no device url was found for a requested member.
        """
        device_urls_by_import_key = {
            d.importKey: d
            for d in lease.info.deviceUrl
            if getattr(d, "importKey", None)
        }

        source_files = []

        for file_item in import_spec_result.fileItem:
            device_url = device_urls_by_import_key.get(file_item.deviceId)

            if device_url is None:
                raise RuntimeError(f"No device url found for: {file_item.path}")

            source = vim.HttpNfcLease.SourceFile(
                url=self._ova_url,
                create=file_item.create,
                targetDeviceId=device_url.importKey,
                memberName=file_item.path,
            )
            source_files.append(source)

        return source_files

    def _edit_nics(
        self,
        import_spec_result: vim.HttpNfcLease.CreateImportSpecResult,
        networkMapping: dict[str, str],
    ) -> None:
        """
        Alters the Import Specs device changes list to fit the networkMapping.
        May only remove existing changes regarding VirtualEthernetCards.
        Does not ensure, that the mapping of interface name to network is correct on the hostsystem.
        This is an in-Place operation.
        :param import_spec_result: ImportSpec object generated from the ovf descriptor. DeviceChanges may be altered.
        :param networkMapping: Maps interface names to the port groups.
        :return:
        """
        # collects nics
        new_changes = []
        # key value should be a negativ number, unique on the vm to create, since the server uses positiv keys to
        # identify stuff. Server is going to change the key of the device in future, will be positiv.
        # No specific reason for the number -151, other than to be negative.
        key = -151
        vm_config_spec: vim.vm.ConfigSpec = import_spec_result.importSpec.configSpec
        for change in vm_config_spec.deviceChange:
            device = change.device
            if not isinstance(device, vim.vm.device.VirtualEthernetCard):
                new_changes.append(change)

        for port_group_name in networkMapping.values():
            network = self.esxi_connection.get_esxi_object(vim.Network, port_group_name)
            if not isinstance(network, vim.Network):
                raise TypeError(
                    f"None or too many networks found for portgroup. VarType: {type(network)}"
                )
            new_changes.append(self._create_new_nic(network, key))
            key -= 1
        vm_config_spec.deviceChange = new_changes

    @staticmethod
    def _create_new_nic(
        network: vim.Network, key: int
    ) -> vim.vm.device.VirtualDeviceSpec:
        """
        Returns a new change to generate a vim.vm.device.VirtualVmxnet3() NIC,
        which is connected to the given network.
        :param network: The Port group on the virtual switch
        :param key: Identifies the device. Should be a negativ number which is unique on the deploying VM.
        This key may be altered in the future by the ESXi-host, in which case it will be a positiv integer.
        :return: The new NIC Object.
        """
        nic = vim.vm.device.VirtualVmxnet3()
        nic.key = key
        nic.addressType = "generated"

        nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
            startConnected=True, allowGuestControl=True, connected=False
        )

        nic.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
            deviceName=network.name, network=network, useAutoDetect=False
        )
        return vim.vm.device.VirtualDeviceSpec(
            operation=vim.vm.device.VirtualDeviceSpec.Operation.add, device=nic
        )

    def deploy_ova(self) -> None:
        """
        Deploys the ova on the ESXi host.
        :return:
        :raises Exception: Is thrown when an error occurs.
        """
        metadata = self._read_ova_metadata(url=self._ova_url, headers={})
        ovf_descriptor: str = metadata["descriptor"]
        lease = None
        try:
            host = self.esxi_connection.get_esxi_object(vim.HostSystem)
            dc = self.esxi_connection.get_esxi_object(vim.Datacenter)
            resource_pool = host.parent.resourcePool

            params = vim.OvfManager.CreateImportSpecParams(
                entityName=self._node.name,
                diskProvisioning=self._disk_provisioning,
                hostSystem=host,
            )

            import_spec_result = (
                self.esxi_connection.content.ovfManager.CreateImportSpec(
                    ovfDescriptor=ovf_descriptor,
                    resourcePool=resource_pool,
                    datastore=self._datastore,
                    cisp=params,
                )
            )

            self._edit_nics(import_spec_result, self._network_mapping)

            lease: vim.HttpNfcLease = resource_pool.ImportVApp(
                spec=import_spec_result.importSpec, folder=dc.vmFolder, host=host
            )

            logger.info("Initializing HttpNFCLease")
            self.wait_for_lease_ready(lease)
            logger.info("Created HttpNFCLease")

            self._raise_if_not_supports_pull_mode(lease)

            source_files = self._get_nfc_lease_source_files(lease, import_spec_result)
            pull_task = lease.HttpNfcLeasePullFromUrls_Task(source_files)

            logger.info(f"Starting pull task: {self._ova_url}")
            self.wait_for_pull_task(pull_task, lease)

            lease.HttpNfcLeaseComplete()
            lease: None = None
        except Exception:
            if not lease is None:
                try:
                    lease.HttpNfcLeaseAbort()
                except Exception:  # noqa: BLE001
                    logger.error("Aborting HttpNFCLease failed.")
            raise

    @staticmethod
    def wait_for_lease_ready(lease: vim.HttpNfcLease, timeout=120):
        """
        Waits until the lease has finished initializing or ran into the timeout.
        :param lease: Running lease to the ESXi host.
        :param timeout: Time until the initialization process runs into a timeout.
        :return:
        :raises TimeoutError: Is thrown when the ``timeout`` has been reached.
        :raises RuntimeError: Is thrown when the lease ran into an error.
        """
        deadline = time.time() + timeout

        while True:
            lease_state = lease.state

            if lease_state == vim.HttpNfcLease.State.ready:
                progress = getattr(lease, "initializeProgress", None)
                print(f"\rLease initialisieren: {progress}%", flush=True)
                return

            if lease_state == vim.HttpNfcLease.State.error:
                error = getattr(lease, "error", None)
                msg = getattr(error, "msg", str(error))
                raise RuntimeError(f"HttpNfcLease Error: {msg}")

            if time.time() > deadline:
                raise TimeoutError(
                    "Ran into a timeout while initializing the HttpNfcLease."
                )

            progress = getattr(lease, "initializeProgress", None)
            if not progress is None:
                print(f"\rLease initialisieren: {progress}%", end="", flush=True)
            time.sleep(1)

    @staticmethod
    def _print_pull_task_progress(
        task: vim.Task, task_progress: int | None, task_start_time: float
    ) -> int | None:
        """
        Prints the progress of the task which gets pulled.
        :param task: Task to track the progress from.
        :param task_progress: Progress of the task.
        :param task_start_time: Start time of the pull task.
        :return: Returns the progress of the pull task.
        """
        print(
            "\r"
            f"Pull Task: "
            f"{task_progress if task_progress is not None else '-'}% | "
            f"State: {task.info.state} | "
            f"{int(time.time() - task_start_time)}s",
            end="",
            flush=True,
        )
        return task_progress

    @staticmethod
    def _update_nfc_lease_progress(lease: vim.HttpNfcLease, task_progress: int) -> None:
        """
        Updates the lease progress to keep the lease running.
        :param lease: Running lease to the ESXi host.
        :param task_progress: Progress of the task to update to.
        :return:
        """
        try:
            lease.HttpNfcLeaseProgress(task_progress)
        except Exception as e:  # noqa: BLE001
            print(f"\nLease keepalive error: {e}")

    def wait_for_pull_task(self, task: vim.Task, lease: vim.HttpNfcLease) -> None:
        """
        Waits until the pull task has finished.
        :param task: Task to track.
        :param lease: Running lease to the ESXi host.
        :return:
        """
        task_start_time = time.time()
        last_keepalive = 0

        while True:
            state = task.info.state
            task_progress = getattr(task.info, "progress", None)

            if state == vim.TaskInfo.State.success:
                self._print_pull_task_progress(task, task_progress, task_start_time)
                print()  # get into new line
                return

            if state == vim.TaskInfo.State.error:
                error = task.info.error
                msg = getattr(error, "msg", str(error))
                raise RuntimeError(
                    f"PullFromUrls failed. Check if HttpClient service is enabled on the ESXi host. Error Message: {msg}"
                )

            current_time = time.time()
            if current_time - last_keepalive >= 2:
                self._print_pull_task_progress(task, task_progress, task_start_time)
            if current_time - last_keepalive >= 30:
                if task_progress is None:
                    task_progress = 0
                self._update_nfc_lease_progress(lease, task_progress)
                last_keepalive = current_time

            time.sleep(2)


"""
# If ova importting does not work, follow these steps.
# connect to esxi shell and execute following command:
esxcli network firewall ruleset set -r httpClient -e true

# To check if successfull next command should output True: 
esxcli network firewall ruleset list | grep httpClient

#Test connection. should return: '403 Forbidden'. If it runs into a timeout then firewall is still wrong or the TrueNAS service is not existing:
wget -S -O /dev/null http://10.20.20.181:80/
"""
