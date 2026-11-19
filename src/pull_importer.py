"""
Imports an OVA as a new VM on an ESXi host in *pull mode*: this process only reads the OVF descriptor out of the OVA
over HTTP range requests, builds the import specification and opens an HttpNfcLease. The ESXi host then downloads the
disks itself (``HttpNfcLease.HttpNfcLeasePullFromUrls_Task``), so no disk data runs through this machine and no
separate upload service is needed.

The host needs its ``httpClient`` firewall ruleset enabled to fetch from an HTTP server; ``ensure_http_client_enabled``
does that through the host API with the login the connection already has.
"""

from __future__ import annotations

import io
import tarfile
import time
from collections.abc import Callable
from urllib.parse import quote

import requests
from loguru import logger
from pyVmomi import vim

from src.connections.esxi_connection import _PYVMOMI_LOCK, ESXiConnection
from src.settings import Settings

_LEASE_POLL_INTERVAL_SECONDS = 1
_PULL_POLL_INTERVAL_SECONDS = 2
_KEEPALIVE_INTERVAL_SECONDS = 30
_HTTP_CLIENT_RULESET = "httpClient"
_FIREWALL_COMMAND = "esxcli network firewall ruleset set -r httpClient -e true"


def ova_url(base_url: str, source_dir: str, file_name: str) -> str:
    """
    The URL an ESXi host fetches a template OVA from: ``<base>/<source dir>/<file>``. Both parts come from the ESXi
    template API (``_source_dir`` and ``file`` of a template).
    :param base_url: ``Settings.API.OVA_BASE_URL``, the HTTP server that serves the OVA files.
    :param source_dir: directory of the template below the server's root, may be empty.
    :param file_name: exact OVA file name.
    :return: the URL, with every path part percent-encoded.
    """
    parts = [
        quote(part, safe="") for part in (*source_dir.split("/"), file_name) if part
    ]
    return f"{base_url.rstrip('/')}/{'/'.join(parts)}"


class HTTPRangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file that fetches only the byte ranges that are read."""

    def __init__(self, url: str, timeout: float = 30) -> None:
        """
        :param url: URL of the file.
        :param timeout: seconds one request may take.
        :raises RuntimeError: Is thrown when the server does not answer, has no Content-Length or no range support.
        """
        super().__init__()
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()
        self.pos = 0
        try:
            with self.session.head(url, timeout=timeout, allow_redirects=True) as head:
                head.raise_for_status()
                length = head.headers.get("Content-Length")
                ranges = head.headers.get("Accept-Ranges", "")
        except requests.exceptions.RequestException as error:
            self.session.close()
            raise RuntimeError(
                f"The OVA server can not be reached for {url}: {error}"
            ) from error
        if length is None:
            self.session.close()
            raise RuntimeError(f"The OVA server sends no Content-Length for {url}.")
        if ranges.lower() == "none":
            self.session.close()
            raise RuntimeError(
                f"The OVA server does not support range requests for {url}."
            )
        self.size = int(length)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self.pos + offset
        elif whence == io.SEEK_END:
            new_pos = self.size + offset
        else:
            raise ValueError("Invalid whence value")
        if new_pos < 0:
            raise ValueError("Negative position")
        self.pos = new_pos
        return self.pos

    def read(self, size: int | None = -1) -> bytes:
        if self.pos >= self.size:
            return b""
        if size is None or size < 0:
            size = self.size - self.pos
        size = min(size, self.size - self.pos)
        if size == 0:
            return b""
        start, end = self.pos, self.pos + size - 1
        with self.session.get(
            self.url,
            headers={"Range": f"bytes={start}-{end}"},
            stream=True,
            timeout=self.timeout,
        ) as response:
            if response.status_code != 206:
                raise RuntimeError(
                    f"Range request {start}-{end} of {self.url} answered {response.status_code}."
                )
            data = response.raw.read(size)
        self.pos += len(data)
        return data

    def close(self) -> None:
        if not self.closed:
            self.session.close()
        super().close()


def check_ova_readable(url: str) -> None:
    """
    Checks that an OVA can be fetched over HTTP right now - size known, ranges supported and the first bytes readable -
    before a deploy removes anything, because a file that cannot be read would only fail the deploy afterwards.
    :param url: URL of the OVA.
    :return:
    :raises RuntimeError: Is thrown when the file cannot be read.
    """
    with HTTPRangeFile(url, timeout=Settings.API.OVA_CHECK_TIMEOUT_SECONDS) as remote:
        if remote.size < 512 or len(remote.read(512)) != 512:
            raise RuntimeError(f"The OVA at {url} is empty or cannot be read.")


def _ovf_descriptor(url: str) -> str:
    with (
        HTTPRangeFile(url) as remote,
        tarfile.open(fileobj=remote, mode="r:") as archive,
    ):
        member = next(
            (
                m
                for m in archive.getmembers()
                if m.isfile() and m.name.lower().endswith(".ovf")
            ),
            None,
        )
        if member is None:
            raise RuntimeError(f"No OVF descriptor found in the OVA at {url}.")
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError(
                f"The OVF descriptor in the OVA at {url} cannot be opened."
            )
        return stream.read().decode("utf-8-sig")


def ensure_http_client_enabled(esxi_connection: ESXiConnection) -> None:
    """
    Makes sure the host may download over HTTP: enables the ``httpClient`` firewall ruleset if it is off. Needs no
    shell access, only the login the connection already uses.
    :param esxi_connection: connection of the host.
    :return:
    :raises RuntimeError: Is thrown when the ruleset cannot be found or enabled; the text names the manual command.
    """
    with _PYVMOMI_LOCK:
        host = esxi_connection.get_host_system()
        firewall = host.configManager.firewallSystem
        if firewall is None:
            raise RuntimeError(
                f"ESXi host {esxi_connection.ip} has no firewall system. Run on it: {_FIREWALL_COMMAND}"
            )
        ruleset = next(
            (r for r in firewall.firewallInfo.ruleset if r.key == _HTTP_CLIENT_RULESET),
            None,
        )
        if ruleset is None:
            raise RuntimeError(
                f"ESXi host {esxi_connection.ip} has no '{_HTTP_CLIENT_RULESET}' firewall ruleset. "
                f"It is needed for the host to download OVA files."
            )
        if ruleset.enabled:
            return
        try:
            firewall.EnableRuleset(id=_HTTP_CLIENT_RULESET)
        except Exception as error:  # noqa: BLE001 - any API fault means the manual path
            raise RuntimeError(
                f"Could not enable the '{_HTTP_CLIENT_RULESET}' firewall ruleset on {esxi_connection.ip}: {error}. "
                f"Run on the host: {_FIREWALL_COMMAND}"
            ) from error
    logger.info(
        f"Enabled the '{_HTTP_CLIENT_RULESET}' firewall ruleset on ESXi host {esxi_connection.ip}"
    )


class PullImporter:
    """Imports an OVA served over HTTP as a new VM, the ESXi host downloading it itself."""

    def __init__(self, esxi_connection: ESXiConnection) -> None:
        """
        :param esxi_connection: connection of the ESXi host to import onto.
        """
        self.esxi_connection = esxi_connection

    def import_ova(
        self,
        url: str,
        vm_name: str,
        datastore_name: str,
        network_names: list[str],
        timeout: float | None = None,
    ) -> vim.VirtualMachine:
        """
        Imports the OVA at ``url`` as a thin provisioned VM whose network adapters (vmxnet3, in this order) are wired
        to ``network_names``; adapters of the OVA itself are not kept.
        :param url: URL of the OVA the host fetches.
        :param vm_name: name of the new VM.
        :param datastore_name: datastore for the VM's files.
        :param network_names: port group of every adapter, in order.
        :param timeout: seconds the whole pull may take, defaults to ``Settings.API.OVA_DEPLOY_TIMEOUT_SECONDS``.
        :return: the new VM.
        :raises RuntimeError: Is thrown when the host cannot pull (older than 6.7, firewall, server unreachable).
        :raises TimeoutError: Is thrown when the pull does not finish in time.
        """
        limit = Settings.API.OVA_DEPLOY_TIMEOUT_SECONDS if timeout is None else timeout
        descriptor = _ovf_descriptor(url)
        ensure_http_client_enabled(self.esxi_connection)
        lease = None
        try:
            with _PYVMOMI_LOCK:
                content = self.esxi_connection.content
                host = self.esxi_connection.get_host_system()
                resource_pool = host.parent.resourcePool
                datacenter = content.rootFolder.childEntity[0]
                datastore = self.esxi_connection.find_datastore(datastore_name)
                result = content.ovfManager.CreateImportSpec(
                    ovfDescriptor=descriptor,
                    resourcePool=resource_pool,
                    datastore=datastore,
                    cisp=vim.OvfManager.CreateImportSpecParams(
                        entityName=vm_name, diskProvisioning="thin"
                    ),
                )
                if result.error:
                    messages = "; ".join(
                        getattr(e, "localizedMessage", None) or str(e)
                        for e in result.error
                    )
                    raise RuntimeError(
                        f"The OVA at {url} cannot be imported: {messages}"
                    )
                for warning in result.warning or []:
                    logger.warning(
                        f"OVF import warning for {vm_name}: {getattr(warning, 'localizedMessage', warning)}"
                    )
                self._edit_nics(result, network_names)
                self._strip_iso_images(result)
                lease = resource_pool.ImportVApp(
                    spec=result.importSpec, folder=datacenter.vmFolder, host=host
                )
                self._wait_for_lease_ready(lease)
                if not lease.capabilities.pullModeSupported:
                    raise RuntimeError(
                        f"ESXi host {self.esxi_connection.ip} does not support pull imports (needs ESXi 6.7 or newer)."
                    )
                sources = self._source_files(lease, result, url)
                task = lease.HttpNfcLeasePullFromUrls_Task(sources)
            logger.info(
                f"ESXi host {self.esxi_connection.ip} pulls {url} as '{vm_name}'"
            )
            self._wait_for_pull(task, lease, limit)
            with _PYVMOMI_LOCK:
                vm = lease.info.entity
                lease.HttpNfcLeaseComplete()
            lease = None
            return vm
        except BaseException:
            if lease is not None:
                try:
                    with _PYVMOMI_LOCK:
                        lease.HttpNfcLeaseAbort()
                except Exception:  # noqa: BLE001
                    logger.error(f"Aborting the import lease of '{vm_name}' failed.")
            raise

    def _edit_nics(
        self, result: vim.OvfManager.CreateImportSpecResult, network_names: list[str]
    ) -> None:
        config = result.importSpec.configSpec
        changes = [
            c
            for c in config.deviceChange
            if not isinstance(c.device, vim.vm.device.VirtualEthernetCard)
        ]
        key = -151  # new devices need a negative key; the host assigns the real one
        for name in network_names:
            network = self.esxi_connection.find_network(name)
            nic = vim.vm.device.VirtualVmxnet3()
            nic.key = key
            nic.addressType = "generated"
            nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
                startConnected=True, allowGuestControl=True, connected=False
            )
            nic.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
                deviceName=network.name, network=network, useAutoDetect=False
            )
            changes.append(
                vim.vm.device.VirtualDeviceSpec(
                    operation=vim.vm.device.VirtualDeviceSpec.Operation.add, device=nic
                )
            )
            key -= 1
        config.deviceChange = changes

    @staticmethod
    def _strip_iso_images(result: vim.OvfManager.CreateImportSpecResult) -> None:
        """Leaves ISO files and their CD drives out: a host cannot receive an ISO through an import lease."""
        isos = [
            item
            for item in (result.fileItem or [])
            if item.path.lower().endswith(".iso")
        ]
        if not isos:
            return
        config = result.importSpec.configSpec
        config.deviceChange = [
            c
            for c in config.deviceChange
            if not (
                isinstance(c.device, vim.vm.device.VirtualCdrom)
                and isinstance(
                    c.device.backing, vim.vm.device.VirtualCdrom.IsoBackingInfo
                )
            )
        ]
        result.fileItem = [item for item in result.fileItem if item not in isos]
        logger.info(
            f"Skipping ISO image(s) a host cannot import: {', '.join(i.path for i in isos)}"
        )

    @staticmethod
    def _wait_for_lease_ready(lease: vim.HttpNfcLease, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while lease.state == vim.HttpNfcLease.State.initializing:
            if time.monotonic() > deadline:
                raise TimeoutError("The import lease did not become ready in time.")
            time.sleep(_LEASE_POLL_INTERVAL_SECONDS)
        if lease.state != vim.HttpNfcLease.State.ready:
            raise RuntimeError(
                f"The import lease failed: {getattr(lease.error, 'msg', lease.error)}"
            )

    @staticmethod
    def _source_files(
        lease: vim.HttpNfcLease, result: vim.OvfManager.CreateImportSpecResult, url: str
    ) -> list[vim.HttpNfcLease.SourceFile]:
        devices = {
            d.importKey: d
            for d in lease.info.deviceUrl
            if getattr(d, "importKey", None)
        }
        sources = []
        for item in result.fileItem or []:
            device = devices.get(item.deviceId)
            if device is None:
                raise RuntimeError(f"The import lease has no target for {item.path}.")
            sources.append(
                vim.HttpNfcLease.SourceFile(
                    url=url,
                    create=item.create,
                    targetDeviceId=device.importKey,
                    memberName=item.path,
                )
            )
        return sources

    def _wait_for_pull(
        self,
        task: vim.Task,
        lease: vim.HttpNfcLease,
        limit: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        started = last_keepalive = time.monotonic()
        while True:
            with _PYVMOMI_LOCK:
                info = task.info
                state, progress = info.state, getattr(info, "progress", None)
                if state == vim.TaskInfo.State.error:
                    message = getattr(info.error, "msg", info.error)
                    raise RuntimeError(
                        f"ESXi host {self.esxi_connection.ip} could not pull the OVA: {message}. "
                        f"Check that the host reaches the OVA server and its '{_HTTP_CLIENT_RULESET}' firewall "
                        f"ruleset is enabled ({_FIREWALL_COMMAND})."
                    )
                if state == vim.TaskInfo.State.success:
                    return
                now = time.monotonic()
                if now - started > limit:
                    raise TimeoutError(
                        f"The OVA pull did not finish within {limit:.0f} s."
                    )
                if now - last_keepalive >= _KEEPALIVE_INTERVAL_SECONDS:
                    last_keepalive = now
                    try:
                        lease.HttpNfcLeaseProgress(int(progress or 0))
                    except Exception as error:  # noqa: BLE001 - a missed keepalive is not fatal by itself
                        logger.warning(f"Import lease keepalive failed: {error}")
            sleep(_PULL_POLL_INTERVAL_SECONDS)
