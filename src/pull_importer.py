"""
Imports an OVA as a new VM on an ESXi host in *pull mode*: this process only reads the OVF descriptor out of the OVA
over HTTP range requests, builds the import specification and opens an HttpNfcLease. The ESXi host then downloads the
disks itself (``HttpNfcLease.HttpNfcLeasePullFromUrls_Task``), so no disk data runs through this machine and no
separate upload service is needed.

The host needs its ``httpClient`` firewall ruleset enabled to fetch from an HTTP server; ``ensure_http_client_enabled``
does that through the host API with the login the connection already has.

A failed or aborted import cleans up after itself, but only what *that* import created: after the lease is aborted
the VM of that name is destroyed if it was not there before, and a datastore folder ``<vm name>`` (or the numbered
``<vm name>_<n>`` ESXi picks when the name is taken) is deleted if it did not exist before and no registered VM lives
in it. Every cleanup step is best effort and never replaces the original error.

Open: once, right after an aborted import, the next import of the same VM name failed with an HTTP 403 reported by the
pull task; a retry worked at once. The cause could not be found in this code (the URL, lease and spec are built fresh
for every import, nothing is shared between two imports). The task error text now carries the full fault (type,
message, status code, nested causes), so a repeat shows which side answered 403.
"""

from __future__ import annotations

import io
import re
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import requests
from loguru import logger
from pyVmomi import vim, vmodl

from src.connections.esxi_connection import _PYVMOMI_LOCK, ESXiConnection
from src.settings import Settings

_LEASE_POLL_INTERVAL_SECONDS = 1
_PULL_POLL_INTERVAL_SECONDS = 2
_KEEPALIVE_INTERVAL_SECONDS = 30
_HTTP_CLIENT_RULESET = "httpClient"
_FIREWALL_COMMAND = "esxcli network firewall ruleset set -r httpClient -e true"
_FAULT_SKIPPED_FIELDS = {"dynamicType", "dynamicProperty", "msg", "faultMessage"}
_MAX_ERROR_TEXT = 1500


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


def describe_task_error(error: object) -> str:
    """
    Turns the error of a vSphere task into one readable text. ``error.msg`` alone is often empty or only says "A general
    system error occurred"; the useful part (an HTTP status code and URL, a nested cause) sits in the other fields of the
    fault, so they are all included.
    :param error: ``TaskInfo.error``, normally a pyVmomi fault.
    :return: fault type, message, localized messages and the remaining fault fields, never empty.
    """
    parts = []
    name = type(error).__name__
    if name not in ("SimpleNamespace", "str", "NoneType"):
        parts.append(name)
    message = getattr(error, "msg", None)
    if message:
        parts.append(str(message))
    for localized in getattr(error, "faultMessage", None) or []:
        text = getattr(localized, "message", None)
        if text:
            parts.append(str(text))
    properties = getattr(error, "_GetPropertyList", None)
    if properties is not None:
        for prop in properties():
            if prop.name in _FAULT_SKIPPED_FIELDS:
                continue
            value = getattr(error, prop.name, None)
            if value is None or value == []:
                continue
            if prop.name == "faultCause":
                parts.append(f"cause: {describe_task_error(value)}")
            else:
                parts.append(f"{prop.name}={value}")
    if not parts:
        parts.append(str(error))
    return "; ".join(parts)[:_MAX_ERROR_TEXT]


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


@dataclass(frozen=True)
class _ImportBaseline:
    """What existed before an import started, so a failed one only removes what it created itself."""

    vm_moids: frozenset[str]
    """managed object ids of the VMs that already carry exactly the import's VM name"""
    folders: frozenset[str]
    """names of the datastore folders ``<vm name>`` / ``<vm name>_<n>`` that already existed"""


class PullImporter:
    """Imports an OVA served over HTTP as a new VM, the ESXi host downloading it itself."""

    _CLEANUP_TASK_WAIT_SECONDS = 60.0
    """how long a cleanup waits for the (cancelled) pull task to stop writing before it deletes files"""
    _CLEANUP_RETRY_SECONDS = 5.0
    """pause between the attempts to delete a folder whose files are still locked"""
    _CLEANUP_ATTEMPTS = 3

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
        task = None
        baseline = self._baseline(vm_name, datastore_name)
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
            if lease is not None or task is not None:
                self._cleanup_failed_import(vm_name, datastore_name, baseline, task)
            raise

    def _baseline(self, vm_name: str, datastore_name: str) -> _ImportBaseline | None:
        """Records the VMs and datastore folders of this name that exist right now; ``None`` when that fails."""
        try:
            with _PYVMOMI_LOCK:
                vms = self._vms_named(vm_name)
                folders = self._folders(datastore_name, vm_name)
            return _ImportBaseline(
                frozenset(vm._moId for vm in vms), frozenset(folders)
            )
        except Exception as error:  # noqa: BLE001 - without a baseline nothing is cleaned up, the import goes on
            logger.warning(
                f"Could not record what exists for '{vm_name}' on {datastore_name} before the import "
                f"({error}); a failed import will not be cleaned up automatically."
            )
            return None

    def _vms_named(self, vm_name: str) -> list[vim.VirtualMachine]:
        vms = []
        for vm in self.esxi_connection.get_all_vms():
            try:
                if vm.name == vm_name:
                    vms.append(vm)
            except vmodl.fault.ManagedObjectNotFound:
                continue  # removed while listing
        return vms

    def _folders(self, datastore_name: str, vm_name: str) -> set[str]:
        """Names of the datastore folders ``<vm_name>`` and ``<vm_name>_<n>`` in the root of the datastore."""
        datastore = self.esxi_connection.find_datastore(datastore_name)
        spec = vim.host.DatastoreBrowser.SearchSpec(
            query=[vim.host.DatastoreBrowser.FolderQuery()],
            matchPattern=[vm_name, f"{vm_name}_*"],
        )
        task = datastore.browser.SearchDatastore_Task(
            datastorePath=f"[{datastore_name}]", searchSpec=spec
        )
        self.esxi_connection._wait_for_task(task)  # noqa: SLF001
        pattern = re.compile(rf"{re.escape(vm_name)}(_\d+)?")
        return {
            entry.path
            for entry in task.info.result.file or []
            if pattern.fullmatch(entry.path)
        }

    def _cleanup_failed_import(
        self,
        vm_name: str,
        datastore_name: str,
        baseline: _ImportBaseline | None,
        task: vim.Task | None,
    ) -> None:
        """
        Removes what a failed import left behind, after its lease was aborted: the VM of this name that was not there
        before and every datastore folder of this name that did not exist before and holds no registered VM. Never
        raises (a failing step only logs a warning with the manual command), so the original error stays the one the
        caller sees.
        """
        if baseline is None:
            logger.warning(
                f"No cleanup for the failed import of '{vm_name}': remove a leftover VM '{vm_name}' and the "
                f"folder '[{datastore_name}] {vm_name}' by hand in the ESXi host client if they exist."
            )
            return
        hint = (
            f"Remove it by hand in the ESXi host client (Storage > {datastore_name} > Datastore browser > "
            f"'{vm_name}')."
        )
        try:
            self._wait_for_pull_to_stop(task)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"Could not stop the pull task of '{vm_name}': {error}")
        try:
            self._destroy_new_vms(vm_name, baseline)
        except Exception as error:  # noqa: BLE001
            logger.warning(
                f"Could not delete the VM '{vm_name}' left by the failed import: {error}. "
                f"Delete that VM by hand in the ESXi host client."
            )
        try:
            self._delete_new_folders(vm_name, datastore_name, baseline)
        except Exception as error:  # noqa: BLE001
            logger.warning(
                f"Could not clean the datastore folder of '{vm_name}' after the failed import: {error}. {hint}"
            )

    def _wait_for_pull_to_stop(self, task: vim.Task | None) -> None:
        """Cancels the pull task if it still runs and waits until it stopped writing (or the wait is over)."""
        if task is None:
            return
        deadline = time.monotonic() + self._CLEANUP_TASK_WAIT_SECONDS
        cancelled = False
        while True:
            with _PYVMOMI_LOCK:
                info = task.info
                if info.state not in (
                    vim.TaskInfo.State.queued,
                    vim.TaskInfo.State.running,
                ):
                    return
                if not cancelled and getattr(info, "cancelable", True):
                    cancelled = True
                    try:
                        task.CancelTask()
                    except Exception as error:  # noqa: BLE001
                        logger.warning(f"Cancelling the pull task failed: {error}")
            if time.monotonic() >= deadline:
                logger.warning("The pull task still runs; cleaning up anyway.")
                return
            time.sleep(_PULL_POLL_INTERVAL_SECONDS)

    def _destroy_new_vms(self, vm_name: str, baseline: _ImportBaseline) -> None:
        """Destroys VMs named ``vm_name`` that are not in the baseline and not powered on."""
        with _PYVMOMI_LOCK:
            created = [
                vm
                for vm in self._vms_named(vm_name)
                if vm._moId not in baseline.vm_moids
            ]
        for vm in created:
            with _PYVMOMI_LOCK:
                try:
                    if vm.runtime.powerState == vim.VirtualMachine.PowerState.poweredOn:
                        logger.warning(
                            f"The VM '{vm_name}' is powered on, so it is not deleted by the import cleanup."
                        )
                        continue
                    self.esxi_connection.delete_vm(vm)
                except vmodl.fault.ManagedObjectNotFound:
                    continue  # the host removed it already
            logger.info(f"Deleted the VM '{vm_name}' left by the failed import")

    def _delete_new_folders(
        self, vm_name: str, datastore_name: str, baseline: _ImportBaseline
    ) -> None:
        """Deletes datastore folders of this name that did not exist before the import and hold no registered VM."""
        with _PYVMOMI_LOCK:
            new = sorted(self._folders(datastore_name, vm_name) - baseline.folders)
            registered = set()
            for vm in self.esxi_connection.get_all_vms():
                try:
                    registered.add(
                        vm.summary.config.vmPathName.split("] ", 1)[-1].split("/")[0]
                    )
                except vmodl.fault.ManagedObjectNotFound:
                    continue
        for folder in new:
            if folder in registered:
                logger.warning(
                    f"The folder '[{datastore_name}] {folder}' holds a registered VM and is kept."
                )
                continue
            self._delete_folder(datastore_name, folder)

    def _delete_folder(self, datastore_name: str, folder: str) -> None:
        for attempt in range(1, self._CLEANUP_ATTEMPTS + 1):
            try:
                with _PYVMOMI_LOCK:
                    content = self.esxi_connection.content
                    self.esxi_connection._wait_for_task(  # noqa: SLF001
                        content.fileManager.DeleteDatastoreFile_Task(
                            name=f"[{datastore_name}] {folder}",
                            datacenter=content.rootFolder.childEntity[0],
                        )
                    )
            except Exception as error:  # noqa: BLE001
                if attempt == self._CLEANUP_ATTEMPTS:
                    raise
                logger.info(
                    f"Deleting '[{datastore_name}] {folder}' failed ({error}); trying again."
                )
                time.sleep(self._CLEANUP_RETRY_SECONDS)
            else:
                logger.info(
                    f"Deleted the folder '[{datastore_name}] {folder}' left by the failed import"
                )
                return

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
                    message = describe_task_error(info.error)
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
