"""
Imports an OVA file as a new VM on an ESXi host, following VMware's documented
HttpNfcLease flow: parse the OVF descriptor, create an import spec, open a
lease, then stream each referenced disk to the URL the lease hands back.
"""

__license__ = "GNU GPLv3"

import ssl
import tarfile
import time

import requests
from pyVmomi import vim
from requests.adapters import HTTPAdapter

from src.connections_handler import ESXiConnection
from src.logger_adapter import get_logger

logger = get_logger(__name__)

_LEASE_POLL_INTERVAL_SECONDS = 1
_UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024


class _EsxiUploadAdapter(HTTPAdapter):
    """
    HTTPAdapter whose SSL context tolerates a connection closed without a
    proper TLS close_notify, instead of raising SSLError. ESXi's embedded
    HTTP server (rhttpproxy) does this on VMDK upload responses; OpenSSL 1.1
    silently accepted it, but OpenSSL 3.x's stricter default behavior turns
    it into '[SSL: UNEXPECTED_EOF_WHILE_READING]'.
    """

    def init_poolmanager(self, *args, **kwargs) -> None:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        kwargs["ssl_context"] = context
        super().init_poolmanager(*args, **kwargs)


class OVAImporter:
    """
    Imports an OVA file as a new VM on a given ESXi connection.
    """

    def __init__(self, esxi_connection: ESXiConnection) -> None:
        """
        :param esxi_connection: connection of the ESXi host to import the OVA onto
        """
        self.esxi_connection = esxi_connection

    def import_ova(
        self,
        ova_path: str,
        vm_name: str,
        datastore_name: str,
        network_names: list[str],
    ) -> vim.VirtualMachine:
        """
        Imports the given OVA file as a new VM.
        :param ova_path: local filesystem path to the .ova file (an NFS share
            mounted locally works fine here, it's just a path)
        :param vm_name: name to give the new VM
        :param datastore_name: datastore to place the VM's files on
        :param network_names: ESXi port group for each network the OVF declares,
            in the same order the source VM's adapters were added (e.g. the
            first-added adapter's network first). Must have exactly as many
            entries as the OVF declares networks.
        :return: the created VM
        """
        content = self.esxi_connection.content
        host_system = self.esxi_connection.get_host_system()
        resource_pool = host_system.parent.resourcePool
        datacenter = content.rootFolder.childEntity[0]
        datastore = self.esxi_connection.find_datastore(datastore_name)

        with tarfile.open(ova_path) as ova:
            ovf_member = next(m for m in ova.getmembers() if m.name.endswith(".ovf"))
            ovf_descriptor = ova.extractfile(ovf_member).read().decode("utf-8")

            parse_result = content.ovfManager.ParseDescriptor(
                ovf_descriptor, vim.OvfManager.ParseDescriptorParams()
            )
            if len(parse_result.network) != len(network_names):
                raise logger.alert(
                    ValueError,
                    f"OVF declares {len(parse_result.network)} network(s) "
                    f"({[net.name for net in parse_result.network]}) but "
                    f"{len(network_names)} ESXi network(s) were given: {network_names}",
                )
            network_mappings = [
                vim.OvfManager.NetworkMapping(
                    name=declared_network.name,
                    network=self.esxi_connection.find_network(network_name),
                )
                for declared_network, network_name in zip(
                    parse_result.network, network_names
                )
            ]

            import_spec_result = content.ovfManager.CreateImportSpec(
                ovf_descriptor,
                resource_pool,
                datastore,
                vim.OvfManager.CreateImportSpecParams(
                    entityName=vm_name, networkMapping=network_mappings
                ),
            )
            if import_spec_result.error:
                raise logger.alert(
                    RuntimeError,
                    f"Failed to create import spec for {ova_path}: "
                    f"{[str(e.msg) for e in import_spec_result.error]}",
                )
            for warning in import_spec_result.warning:
                logger.warning(f"OVF import warning: {warning.msg}")

            logger.info(f"Importing {ova_path} as VM '{vm_name}'")
            lease = resource_pool.ImportVApp(
                spec=import_spec_result.importSpec,
                folder=datacenter.vmFolder,
                host=host_system,
            )
            self._wait_for_lease_ready(lease)

            vm = lease.info.entity
            self._upload_disks(ova, import_spec_result.fileItem, lease)
            lease.HttpNfcLeaseComplete()

        logger.info(f"Imported VM '{vm_name}'")
        return vm

    @staticmethod
    def _wait_for_lease_ready(lease: vim.HttpNfcLease) -> None:
        """
        Blocks until the given HTTP NFC lease is ready to accept uploads.
        :param lease: the lease to wait for
        :return:
        """
        while lease.state == vim.HttpNfcLease.State.initializing:
            time.sleep(_LEASE_POLL_INTERVAL_SECONDS)
        if lease.state != vim.HttpNfcLease.State.ready:
            raise logger.alert(
                RuntimeError, f"HTTP NFC lease failed to become ready: {lease.state}"
            )

    def _upload_disks(
        self,
        ova: tarfile.TarFile,
        file_items: list[vim.OvfManager.FileItem],
        lease: vim.HttpNfcLease,
    ) -> None:
        """
        Uploads each disk referenced by the import spec to the matching device
        URL the lease provided, keeping the lease alive with progress updates.
        :param ova: the open OVA tar archive to read disk contents from
        :param file_items: files the import spec expects, from CreateImportSpec
        :param lease: the open HTTP NFC lease to upload to and report progress on
        :return:
        """
        device_urls = {device.importKey: device for device in lease.info.deviceUrl}
        total_bytes = sum(item.size for item in file_items) or 1
        uploaded_bytes = 0

        with requests.Session() as session:
            session.mount("https://", _EsxiUploadAdapter())

            for file_item in file_items:
                device_url = device_urls[file_item.deviceId]
                upload_url = device_url.url.replace(
                    "*", self.esxi_connection.ip_address
                )
                member = ova.getmember(file_item.path)
                disk_stream = ova.extractfile(member)

                headers = {
                    "Content-Type": "application/x-vnd.vmware-streamVmdk",
                    "Content-Length": str(member.size),
                }
                method = session.put if file_item.create else session.post
                logger.debug(f"Uploading {file_item.path} ({member.size} bytes)")
                response = method(
                    upload_url,
                    data=self._read_in_chunks(disk_stream),
                    headers=headers,
                    verify=False,
                )
                response.raise_for_status()

                uploaded_bytes += member.size
                lease.HttpNfcLeaseProgress(int(uploaded_bytes / total_bytes * 100))

    @staticmethod
    def _read_in_chunks(file_obj, chunk_size: int = _UPLOAD_CHUNK_SIZE):
        """
        Generator yielding a file-like object's contents in fixed-size chunks,
        so uploads don't need to buffer the whole disk image in memory.
        """
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                return
            yield chunk
