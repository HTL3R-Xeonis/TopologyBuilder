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
import urllib3
from pyVmomi import vim
from requests.adapters import HTTPAdapter

from src.connections_handler import ESXiConnection
from src.logger_adapter import get_logger

logger = get_logger(__name__)

_LEASE_POLL_INTERVAL_SECONDS = 1

# ESXi hosts use self-signed certs, so VMDK uploads deliberately skip cert
# verification (verify=False in _upload_disks) - same choice the pyVmomi
# connection in connections_handler.py already makes via its own SSLContext.
# Without this, urllib3 warns on every single upload request about a choice
# that was made on purpose, not overlooked.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        :param network_names: ESXi port group for each network adapter the
            new VM should end up with, in the same order the source VM's
            adapters were added (e.g. the first-added adapter's network
            first). Must have at least as many entries as the OVF declares
            networks - the first len(parse_result.network) are mapped
            positionally during import; any extra entries are added as new
            network adapters afterward (e.g. a single-NIC OVA that still
            needs a second, trunk NIC added on top).
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
            if len(parse_result.network) > len(network_names):
                raise logger.alert(
                    ValueError,
                    f"OVF declares {len(parse_result.network)} network(s) "
                    f"({[net.name for net in parse_result.network]}) but only "
                    f"{len(network_names)} ESXi network(s) were given: {network_names}",
                )
            declared_network_names = network_names[: len(parse_result.network)]
            extra_network_names = network_names[len(parse_result.network) :]

            network_mappings = [
                vim.OvfManager.NetworkMapping(
                    name=declared_network.name,
                    network=self.esxi_connection.find_network(network_name),
                )
                for declared_network, network_name in zip(
                    parse_result.network, declared_network_names
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

        if extra_network_names:
            self.esxi_connection.add_vm_network_adapters(vm, extra_network_names)

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

                # Pass the file-like object itself as the body, rather than
                # our own chunking generator - requests CANNOT determine a
                # generator's length, so passing one alongside an explicit
                # Content-Length header (previously done here) makes it ALSO
                # add 'Transfer-Encoding: chunked' on top of that
                # Content-Length, producing a self-contradictory request.
                # ESXi's streamVmdk endpoint doesn't dechunk it and instead
                # reads the chunk-framing bytes as VMDK data, failing
                # immediately. A seekable file-like object lets requests
                # determine the real length itself (via seek/tell) and send a
                # plain, non-chunked body - still streamed internally, never
                # buffered fully in memory.
                headers = {"Content-Type": "application/x-vnd.vmware-streamVmdk"}
                method = session.put if file_item.create else session.post
                logger.debug(f"Uploading {file_item.path} ({member.size} bytes)")
                response = method(
                    upload_url,
                    data=disk_stream,
                    headers=headers,
                    verify=False,
                )
                response.raise_for_status()

                uploaded_bytes += member.size
                lease.HttpNfcLeaseProgress(int(uploaded_bytes / total_bytes * 100))
