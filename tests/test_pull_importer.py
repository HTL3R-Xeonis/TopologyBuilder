"""
Tests to validate functionality of src/pull_importer.py
"""

__license__ = "GNU GPLv3"

import io
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import allure
import pytest
from pyVmomi import vim, vmodl

from src.pull_importer import (
    _FIREWALL_COMMAND,
    HTTPRangeFile,
    PullImporter,
    _ovf_descriptor,
    check_ova_readable,
    ensure_http_client_enabled,
    ova_url,
)
from src.settings import Settings

_DESCRIPTOR = '<?xml version="1.0"?><Envelope><VirtualSystem/></Envelope>'
_DISK = bytes(range(256)) * 40  # 10240 bytes, every offset has a recognisable value


def _make_ova_bytes(
    descriptor: bytes | None = _DESCRIPTOR.encode(), disk: bytes = _DISK
) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        members = []
        if descriptor is not None:
            members.append(("vm.ovf", descriptor))
        members.append(("vm-disk1.vmdk", disk))
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# path on the local test server -> (body, header behaviour)
_FILES: dict[str, tuple[bytes, str]] = {
    "/ok.ova": (_make_ova_bytes(), "ranges"),
    "/sub dir/with space.ova": (_make_ova_bytes(), "ranges"),
    "/bom.ova": (_make_ova_bytes(b"\xef\xbb\xbf" + _DESCRIPTOR.encode()), "ranges"),
    "/noovf.ova": (_make_ova_bytes(None), "ranges"),
    "/tiny.ova": (b"x" * 100, "ranges"),
    "/nolength.ova": (_make_ova_bytes(), "nolength"),
    "/noranges.ova": (_make_ova_bytes(), "acceptnone"),
    "/ignoresrange.ova": (_make_ova_bytes(), "ignorerange"),
}


class _Handler(BaseHTTPRequestHandler):
    """A tiny file server that behaves like nginx for ``ranges`` and misbehaves on purpose for the other modes."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def _entry(self) -> tuple[bytes, str] | None:
        return _FILES.get(unquote(self.path))

    def do_HEAD(self) -> None:
        entry = self._entry()
        if entry is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body, mode = entry
        self.send_response(200)
        if mode == "nolength":
            self.send_header("Connection", "close")
        else:
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "none" if mode == "acceptnone" else "bytes")
        self.end_headers()

    def do_GET(self) -> None:
        entry = self._entry()
        if entry is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body, mode = entry
        header = self.headers.get("Range")
        if header is None or mode == "ignorerange":
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        start, _, end = header.removeprefix("bytes=").partition("-")
        first = int(start)
        last = min(int(end), len(body) - 1) if end else len(body) - 1
        chunk = body[first : last + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {first}-{last}/{len(body)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(5)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch) -> None:
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")


# --- ova_url -----------------------------------------------------------------------------------------------------------


@allure.title("ova_url baut <Basis>/<Verzeichnis>/<Datei>")
@allure.description(
    "Überprüft, dass die URL aus OVA_BASE_URL, dem _source_dir und dem Dateinamen des Templates besteht und ein "
    "abschließender Schrägstrich der Basis nicht doppelt auftaucht"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_000() -> None:
    assert (
        ova_url("http://10.20.20.181:80", "linux/ubuntu", "u.ova")
        == "http://10.20.20.181:80/linux/ubuntu/u.ova"
    )
    assert (
        ova_url("http://10.20.20.181:80/", "linux", "u.ova")
        == "http://10.20.20.181:80/linux/u.ova"
    )


@allure.title("ova_url kodiert jeden Pfadteil prozentweise")
@allure.description(
    "Leerzeichen, Umlaute, '#', '?' und '%' in Verzeichnis und Dateiname werden kodiert, damit sie nicht als URL-Syntax "
    "gelesen werden; die '/' des Verzeichnisses bleiben Trenner"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_001() -> None:
    assert (
        ova_url("http://h", "my dir/über", "a b#c?d%e.ova")
        == "http://h/my%20dir/%C3%BCber/a%20b%23c%3Fd%25e.ova"
    )


@allure.title("ova_url lässt leere Verzeichnisteile weg")
@allure.description(
    "Ein leeres _source_dir, doppelte oder führende/abschließende '/' erzeugen keine leeren Pfadteile"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_002() -> None:
    assert ova_url("http://h", "", "a.ova") == "http://h/a.ova"
    assert ova_url("http://h", "/x//y/", "a.ova") == "http://h/x/y/a.ova"


# --- HTTPRangeFile -----------------------------------------------------------------------------------------------------


@allure.title("HTTPRangeFile liest Größe per HEAD und Bytebereiche per Range")
@allure.description(
    "Gegen einen lokalen http.server mit Range-Unterstützung: size aus Content-Length, read vom Anfang, nach seek in die "
    "Mitte und bis zum Ende, tell folgt der Position"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_010(server) -> None:
    body = _FILES["/ok.ova"][0]
    with HTTPRangeFile(f"{server}/ok.ova") as remote:
        assert remote.size == len(body)
        assert remote.readable() and remote.seekable()
        assert remote.tell() == 0
        assert remote.read(512) == body[:512]
        assert remote.tell() == 512
        assert remote.seek(1000) == 1000
        assert remote.read(100) == body[1000:1100]
        assert remote.seek(-50, 2) == len(body) - 50
        assert remote.read() == body[-50:]
        assert remote.read(10) == b""
        assert remote.seek(-30, 1) == len(body) - 30
        assert remote.read(None) == body[-30:]


@allure.title("HTTPRangeFile begrenzt read am Dateiende und liest ohne Größe alles")
@allure.description(
    "Ein read über das Ende hinaus liefert nur den Rest, read(-1) die ganze Datei, ein read hinter dem Ende nichts"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_011(server) -> None:
    body = _FILES["/ok.ova"][0]
    with HTTPRangeFile(f"{server}/ok.ova") as remote:
        remote.seek(len(body) - 10)
        assert remote.read(1000) == body[-10:]
        remote.seek(0)
        assert remote.read(-1) == body
        remote.seek(len(body) + 5)
        assert remote.read(10) == b""
        remote.seek(3)
        assert remote.read(0) == b""
        assert remote.tell() == 3


@allure.title(
    "HTTPRangeFile.seek lehnt eine negative Position und ein falsches whence ab"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_012(server) -> None:
    with HTTPRangeFile(f"{server}/ok.ova") as remote:
        with pytest.raises(ValueError, match="Negative"):
            remote.seek(-1)
        with pytest.raises(ValueError, match="Negative"):
            remote.seek(-(remote.size + 1), 2)
        with pytest.raises(ValueError, match="whence"):
            remote.seek(0, 7)


@allure.title(
    "HTTPRangeFile kann einen Pfad mit Leerzeichen laden, wenn er kodiert ist"
)
@allure.description(
    "Die von ova_url gebaute URL mit %20 im Verzeichnis und Dateinamen wird vom Server aufgelöst"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_013(server) -> None:
    url = ova_url(server, "sub dir", "with space.ova")
    with HTTPRangeFile(url) as remote:
        assert remote.read(4) == _FILES["/sub dir/with space.ova"][0][:4]


@allure.title("HTTPRangeFile wirft RuntimeError ohne Content-Length")
@allure.description(
    "Antwortet der Server auf HEAD ohne Content-Length, ist die Größe unbekannt und die Datei nicht nutzbar"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_014(server) -> None:
    with pytest.raises(RuntimeError, match="no Content-Length"):
        HTTPRangeFile(f"{server}/nolength.ova")


@allure.title("HTTPRangeFile wirft RuntimeError bei Accept-Ranges: none")
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_015(server) -> None:
    with pytest.raises(RuntimeError, match="range requests"):
        HTTPRangeFile(f"{server}/noranges.ova")


@allure.title(
    "HTTPRangeFile wirft RuntimeError, wenn die Datei fehlt oder der Server nicht antwortet"
)
@allure.description(
    "Ein 404 und ein geschlossener Port werden als RuntimeError mit der URL gemeldet, nicht als requests-Fehler"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_016(server) -> None:
    with pytest.raises(RuntimeError, match="can not be reached") as missing:
        HTTPRangeFile(f"{server}/missing.ova")
    assert f"{server}/missing.ova" in str(missing.value)
    with pytest.raises(RuntimeError, match="can not be reached"):
        HTTPRangeFile("http://127.0.0.1:1/x.ova", timeout=2)


@allure.title(
    "HTTPRangeFile.read wirft RuntimeError, wenn der Server den Range ignoriert"
)
@allure.description(
    "Beantwortet der Server eine Range-Anfrage mit 200 statt 206, würde der Anfang der Datei als Mitte gelesen: das "
    "muss ein Fehler sein"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_017(server) -> None:
    with HTTPRangeFile(f"{server}/ignoresrange.ova") as remote:
        remote.seek(100)
        with pytest.raises(RuntimeError, match="answered 200"):
            remote.read(10)


@allure.title("HTTPRangeFile.close schließt die Session und ist wiederholbar")
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_018(server) -> None:
    remote = HTTPRangeFile(f"{server}/ok.ova")
    remote.close()
    assert remote.closed
    remote.close()


# --- check_ova_readable ------------------------------------------------------------------------------------------------


@allure.title("check_ova_readable akzeptiert eine lesbare OVA")
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_020(server) -> None:
    check_ova_readable(f"{server}/ok.ova")


@allure.title("check_ova_readable lehnt zu kleine, fehlende und range-lose OVAs ab")
@allure.description(
    "Eine Datei unter 512 Byte, ein 404, ein Server ohne Content-Length und ohne Range-Unterstützung werden alle als "
    "RuntimeError gemeldet, bevor ein Deploy etwas löscht"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_021(server) -> None:
    with pytest.raises(RuntimeError, match="empty or cannot be read"):
        check_ova_readable(f"{server}/tiny.ova")
    for name in ("missing.ova", "nolength.ova", "noranges.ova"):
        with pytest.raises(RuntimeError):
            check_ova_readable(f"{server}/{name}")


@allure.title("check_ova_readable verwendet OVA_CHECK_TIMEOUT_SECONDS")
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_022() -> None:
    with patch("src.pull_importer.HTTPRangeFile") as range_file:
        range_file.return_value.__enter__.return_value.size = 4096
        range_file.return_value.__enter__.return_value.read.return_value = b"x" * 512
        check_ova_readable("http://h/a.ova")

    range_file.assert_called_once_with(
        "http://h/a.ova", timeout=Settings.API.OVA_CHECK_TIMEOUT_SECONDS
    )


# --- OVF descriptor ----------------------------------------------------------------------------------------------------


@allure.title("_ovf_descriptor liest nur den OVF-Descriptor aus der OVA")
@allure.description(
    "Der Descriptor wird über Range-Anfragen aus dem Tar gelesen, ein UTF-8-BOM wird entfernt"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_030(server) -> None:
    assert _ovf_descriptor(f"{server}/ok.ova") == _DESCRIPTOR
    assert _ovf_descriptor(f"{server}/bom.ova") == _DESCRIPTOR


@allure.title("_ovf_descriptor wirft RuntimeError, wenn die OVA keinen Descriptor hat")
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_031(server) -> None:
    with pytest.raises(RuntimeError, match="No OVF descriptor"):
        _ovf_descriptor(f"{server}/noovf.ova")


# --- ensure_http_client_enabled ----------------------------------------------------------------------------------------


def _firewall_connection(rulesets: list[SimpleNamespace] | None, *, has_firewall=True):
    connection = MagicMock()
    connection.ip = "10.20.20.204"
    host = MagicMock()
    connection.get_host_system.return_value = host
    if not has_firewall:
        host.configManager.firewallSystem = None
        return connection, None
    firewall = host.configManager.firewallSystem
    firewall.firewallInfo.ruleset = rulesets
    return connection, firewall


@allure.title("ensure_http_client_enabled tut nichts, wenn der Ruleset schon aktiv ist")
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_040() -> None:
    connection, firewall = _firewall_connection(
        [
            SimpleNamespace(key="sshServer", enabled=False),
            SimpleNamespace(key="httpClient", enabled=True),
        ]
    )

    ensure_http_client_enabled(connection)

    firewall.EnableRuleset.assert_not_called()


@allure.title(
    "ensure_http_client_enabled aktiviert einen ausgeschalteten httpClient-Ruleset"
)
@allure.description(
    "Nur der Ruleset httpClient wird über firewallSystem.EnableRuleset eingeschaltet, andere bleiben unberührt"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_041() -> None:
    connection, firewall = _firewall_connection(
        [
            SimpleNamespace(key="sshServer", enabled=False),
            SimpleNamespace(key="httpClient", enabled=False),
        ]
    )

    ensure_http_client_enabled(connection)

    firewall.EnableRuleset.assert_called_once_with(id="httpClient")


@allure.title("ensure_http_client_enabled meldet einen fehlenden Ruleset")
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_042() -> None:
    connection, firewall = _firewall_connection(
        [SimpleNamespace(key="sshServer", enabled=True)]
    )

    with pytest.raises(RuntimeError, match="no 'httpClient' firewall ruleset") as error:
        ensure_http_client_enabled(connection)

    assert "10.20.20.204" in str(error.value)
    firewall.EnableRuleset.assert_not_called()


@allure.title(
    "ensure_http_client_enabled nennt bei einem API-Fehler den manuellen Befehl"
)
@allure.description(
    "Schlägt EnableRuleset fehl (z.B. fehlende Rechte), enthält die RuntimeError den Host, den Grund der API und den "
    "esxcli-Befehl, mit dem der Ruleset von Hand eingeschaltet wird"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_043() -> None:
    connection, firewall = _firewall_connection(
        [SimpleNamespace(key="httpClient", enabled=False)]
    )
    firewall.EnableRuleset.side_effect = vim.fault.NoPermission()

    with pytest.raises(RuntimeError) as error:
        ensure_http_client_enabled(connection)

    text = str(error.value)
    assert "10.20.20.204" in text
    assert "esxcli network firewall ruleset set -r httpClient -e true" in text
    assert _FIREWALL_COMMAND in text
    assert isinstance(error.value.__cause__, vim.fault.NoPermission)


@allure.title(
    "ensure_http_client_enabled meldet einen Host ohne Firewall-System mit dem Befehl"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_044() -> None:
    connection, _ = _firewall_connection(None, has_firewall=False)

    with pytest.raises(RuntimeError, match="no firewall system") as error:
        ensure_http_client_enabled(connection)

    assert _FIREWALL_COMMAND in str(error.value)


# --- PullImporter.import_ova -------------------------------------------------------------------------------------------

_URL = "http://10.20.20.181:80/linux/ubuntu.ova"


def _ethernet(card_class, key: int) -> vim.vm.device.VirtualDeviceSpec:
    return vim.vm.device.VirtualDeviceSpec(
        operation=vim.vm.device.VirtualDeviceSpec.Operation.add,
        device=card_class(key=key),
    )


def _spec_result(
    *, errors=None, warnings=None
) -> vim.OvfManager.CreateImportSpecResult:
    """A CreateImportSpec result like the host would give for an OVA with an E1000 card, a disk, an ISO and a CD drive."""
    iso_drive = vim.vm.device.VirtualCdrom(
        key=3002,
        backing=vim.vm.device.VirtualCdrom.IsoBackingInfo(fileName="boot.iso"),
    )
    host_drive = vim.vm.device.VirtualCdrom(
        key=3003,
        backing=vim.vm.device.VirtualCdrom.AtapiBackingInfo(deviceName="/dev/cdrom"),
    )
    changes = [
        vim.vm.device.VirtualDeviceSpec(
            operation=vim.vm.device.VirtualDeviceSpec.Operation.add,
            device=vim.vm.device.VirtualLsiLogicController(key=1000),
        ),
        _ethernet(vim.vm.device.VirtualE1000, 4000),
        _ethernet(vim.vm.device.VirtualVmxnet3, 4001),
        vim.vm.device.VirtualDeviceSpec(
            operation=vim.vm.device.VirtualDeviceSpec.Operation.add, device=iso_drive
        ),
        vim.vm.device.VirtualDeviceSpec(
            operation=vim.vm.device.VirtualDeviceSpec.Operation.add, device=host_drive
        ),
    ]
    return vim.OvfManager.CreateImportSpecResult(
        importSpec=vim.vm.VmImportSpec(
            configSpec=vim.vm.ConfigSpec(deviceChange=changes)
        ),
        fileItem=[
            vim.OvfManager.FileItem(
                deviceId="/vm/disk1", path="vm-disk1.vmdk", create=True
            ),
            vim.OvfManager.FileItem(
                deviceId="/vm/cdrom", path="boot.iso", create=False
            ),
        ],
        error=errors or [],
        warning=warnings or [],
    )


class _FakeTask:
    """pyVmomi task whose ``info`` walks through the given states, the last one repeating."""

    def __init__(self, *states: SimpleNamespace) -> None:
        self._states = list(states)

    @property
    def info(self) -> SimpleNamespace:
        return self._states.pop(0) if len(self._states) > 1 else self._states[0]


def _success() -> SimpleNamespace:
    return SimpleNamespace(state=vim.TaskInfo.State.success, progress=100, error=None)


def _failed(message: str) -> SimpleNamespace:
    return SimpleNamespace(
        state=vim.TaskInfo.State.error,
        progress=None,
        error=SimpleNamespace(msg=message),
    )


def _running(progress: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        state=vim.TaskInfo.State.running, progress=progress, error=None
    )


class _Rig:
    """A fake ESXi connection with everything ``import_ova`` touches, plus the objects tests assert on."""

    def __init__(self, task: _FakeTask | None = None, result=None) -> None:
        self.connection = MagicMock()
        self.connection.ip = "10.20.20.204"
        self.host = self.connection.get_host_system.return_value
        self.resource_pool = self.host.parent.resourcePool
        self.datacenter = self.connection.content.rootFolder.childEntity[0]
        self.manager = self.connection.content.ovfManager
        self.result = result or _spec_result()
        self.manager.CreateImportSpec.return_value = self.result
        self.networks: dict[str, MagicMock] = {}
        self.connection.find_network.side_effect = self._find_network

        self.lease = self.resource_pool.ImportVApp.return_value
        self.lease.state = vim.HttpNfcLease.State.ready
        self.lease.capabilities.pullModeSupported = True
        self.lease.info.deviceUrl = [
            SimpleNamespace(importKey="/vm/disk1", key="disk-key"),
            SimpleNamespace(importKey=None, key="ignored"),
        ]
        self.vm = self.lease.info.entity
        self.lease.HttpNfcLeasePullFromUrls_Task.return_value = task or _FakeTask(
            _success()
        )

    def _find_network(self, name: str) -> MagicMock:
        network = MagicMock(spec=vim.Network)
        network.name = name
        self.networks[name] = network
        return network

    def run(self, network_names: list[str] | None = None, **kwargs):
        with (
            patch("src.pull_importer._ovf_descriptor", return_value="<descriptor/>"),
            patch("src.pull_importer.ensure_http_client_enabled") as firewall,
        ):
            self.firewall = firewall
            return PullImporter(self.connection).import_ova(
                _URL, "UBUNTU1", "datastore1", network_names or ["PG-A"], **kwargs
            )


@allure.title("import_ova importiert die OVA im Pull-Modus und gibt die neue VM zurück")
@allure.description(
    "Descriptor und Import-Spec werden aufgebaut, der Lease geöffnet, der Host zieht die OVA per "
    "HttpNfcLeasePullFromUrls_Task von der URL, danach wird der Lease abgeschlossen (nicht abgebrochen)"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_050() -> None:
    rig = _Rig()

    vm = rig.run(["PG-A"])

    assert vm is rig.vm
    rig.firewall.assert_called_once_with(rig.connection)
    kwargs = rig.manager.CreateImportSpec.call_args.kwargs
    assert kwargs["ovfDescriptor"] == "<descriptor/>"
    assert kwargs["resourcePool"] is rig.resource_pool
    assert kwargs["datastore"] is rig.connection.find_datastore.return_value
    rig.connection.find_datastore.assert_called_once_with("datastore1")
    assert kwargs["cisp"].entityName == "UBUNTU1"
    assert kwargs["cisp"].diskProvisioning == "thin"
    rig.resource_pool.ImportVApp.assert_called_once_with(
        spec=rig.result.importSpec, folder=rig.datacenter.vmFolder, host=rig.host
    )
    rig.lease.HttpNfcLeaseComplete.assert_called_once_with()
    rig.lease.HttpNfcLeaseAbort.assert_not_called()


@allure.title("import_ova übergibt dem Host genau die Disk als SourceFile")
@allure.description(
    "Pro fileItem ohne ISO entsteht ein SourceFile mit der URL, create-Flag, memberName des Pfads in der OVA und dem "
    "importKey des Lease-Ziels; Lease-Geräte ohne importKey zählen nicht"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_051() -> None:
    rig = _Rig()

    rig.run()

    (sources,) = rig.lease.HttpNfcLeasePullFromUrls_Task.call_args.args
    assert len(sources) == 1
    source = sources[0]
    assert isinstance(source, vim.HttpNfcLease.SourceFile)
    assert source.url == _URL
    assert source.create is True
    assert source.targetDeviceId == "/vm/disk1"
    assert source.memberName == "vm-disk1.vmdk"


@allure.title(
    "import_ova verwirft die NICs der OVA und legt pro Netz eine vmxnet3 in Reihenfolge an"
)
@allure.description(
    "Alle Ethernet-Karten aus dem Descriptor (E1000, vmxnet3) fallen weg, Controller und Nicht-ISO-Laufwerke bleiben; "
    "danach folgt je Port-Group in der angegebenen Reihenfolge eine vmxnet3 mit eigenem negativen Key, verbunden mit "
    "dem Netz, beim Start verbunden"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_052() -> None:
    rig = _Rig()

    rig.run(["PG-MGMT", "PG-TRUNK", "PG-LAN"])

    changes = rig.result.importSpec.configSpec.deviceChange
    devices = [c.device for c in changes]
    nics = [d for d in devices if isinstance(d, vim.vm.device.VirtualEthernetCard)]
    assert not any(isinstance(d, vim.vm.device.VirtualE1000) for d in devices)
    assert [type(n) for n in nics] == [vim.vm.device.VirtualVmxnet3] * 3
    assert [n.key for n in nics] == [-151, -152, -153]
    assert [n.backing.deviceName for n in nics] == ["PG-MGMT", "PG-TRUNK", "PG-LAN"]
    assert [n.backing.network for n in nics] == [
        rig.networks[name] for name in ("PG-MGMT", "PG-TRUNK", "PG-LAN")
    ]
    assert [c.args[0] for c in rig.connection.find_network.call_args_list] == [
        "PG-MGMT",
        "PG-TRUNK",
        "PG-LAN",
    ]
    assert all(n.addressType == "generated" for n in nics)
    assert all(
        n.connectable.startConnected and not n.connectable.connected for n in nics
    )
    assert all(
        c.operation == vim.vm.device.VirtualDeviceSpec.Operation.add
        for c in changes
        if isinstance(c.device, vim.vm.device.VirtualEthernetCard)
    )
    assert any(isinstance(d, vim.vm.device.VirtualLsiLogicController) for d in devices)
    # the new NICs come last, after everything that was kept
    assert changes[-3:] == [c for c in changes if c.device in nics]


@allure.title("import_ova entfernt ISO-Dateien und ihre CD-Laufwerke aus dem Import")
@allure.description(
    "Ein Host kann kein ISO über einen Lease aufnehmen: fileItem und das Laufwerk mit IsoBackingInfo fallen weg, ein "
    "Laufwerk mit anderem Backing bleibt"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_053() -> None:
    rig = _Rig()

    rig.run()

    assert [item.path for item in rig.result.fileItem] == ["vm-disk1.vmdk"]
    cdroms = [
        c.device
        for c in rig.result.importSpec.configSpec.deviceChange
        if isinstance(c.device, vim.vm.device.VirtualCdrom)
    ]
    assert [d.key for d in cdroms] == [3003]
    assert not any(
        isinstance(d.backing, vim.vm.device.VirtualCdrom.IsoBackingInfo) for d in cdroms
    )


@allure.title("import_ova lässt eine OVA ohne ISO unverändert")
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_054() -> None:
    result = _spec_result()
    result.fileItem = [result.fileItem[0]]
    rig = _Rig(result=result)

    rig.run()

    cdroms = [
        c.device
        for c in rig.result.importSpec.configSpec.deviceChange
        if isinstance(c.device, vim.vm.device.VirtualCdrom)
    ]
    assert [d.key for d in cdroms] == [3002, 3003]


@allure.title(
    "import_ova bricht den Lease ab und nennt Grund und Befehl, wenn der Host nicht ziehen kann"
)
@allure.description(
    "Endet der Pull-Task mit einem Fehler, enthält die RuntimeError die Host-Adresse, die Meldung des Hosts und den "
    "esxcli-Befehl; der Lease wird abgebrochen und nie abgeschlossen"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_055() -> None:
    rig = _Rig(task=_FakeTask(_failed("connection refused")))

    with pytest.raises(RuntimeError) as error:
        rig.run()

    text = str(error.value)
    assert "10.20.20.204" in text
    assert "could not pull" in text
    assert "connection refused" in text
    assert _FIREWALL_COMMAND in text
    rig.lease.HttpNfcLeaseAbort.assert_called_once_with()
    rig.lease.HttpNfcLeaseComplete.assert_not_called()


@allure.title(
    "import_ova wirft TimeoutError und bricht den Lease ab, wenn der Pull zu lange dauert"
)
@allure.description(
    "Läuft der Task nach Ablauf des Limits noch, wird TimeoutError geworfen und der Lease abgebrochen; ohne Parameter "
    "gilt Settings.API.OVA_DEPLOY_TIMEOUT_SECONDS"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_056() -> None:
    rig = _Rig(task=_FakeTask(_running()))
    with pytest.raises(TimeoutError, match="did not finish"):
        rig.run(timeout=-1)
    rig.lease.HttpNfcLeaseAbort.assert_called_once_with()
    rig.lease.HttpNfcLeaseComplete.assert_not_called()

    rig = _Rig(task=_FakeTask(_running()))
    with (
        patch.object(Settings.API, "OVA_DEPLOY_TIMEOUT_SECONDS", -1),
        pytest.raises(TimeoutError),
    ):
        rig.run()
    rig.lease.HttpNfcLeaseAbort.assert_called_once_with()


@allure.title(
    "import_ova meldet einen Host ohne Pull-Unterstützung und bricht den Lease ab"
)
@allure.description(
    "Ist capabilities.pullModeSupported false (ESXi älter als 6.7), kommt eine lesbare RuntimeError, der Pull wird nie "
    "gestartet und der Lease abgebrochen"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_057() -> None:
    rig = _Rig()
    rig.lease.capabilities.pullModeSupported = False

    with pytest.raises(RuntimeError, match="does not support pull imports") as error:
        rig.run()

    assert "6.7" in str(error.value)
    rig.lease.HttpNfcLeasePullFromUrls_Task.assert_not_called()
    rig.lease.HttpNfcLeaseAbort.assert_called_once_with()
    rig.lease.HttpNfcLeaseComplete.assert_not_called()


@allure.title("import_ova meldet Fehler der Import-Spec, ohne einen Lease zu öffnen")
@allure.description(
    "Liefert CreateImportSpec Fehler, werden ihre Meldungen in die RuntimeError übernommen und ImportVApp nicht "
    "aufgerufen"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_058() -> None:
    rig = _Rig(
        result=_spec_result(
            errors=[
                vmodl.LocalizedMethodFault(
                    localizedMessage="Unsupported hardware family"
                ),
                vmodl.LocalizedMethodFault(localizedMessage="Disk missing"),
            ]
        )
    )

    with pytest.raises(RuntimeError, match="cannot be imported") as error:
        rig.run()

    assert "Unsupported hardware family; Disk missing" in str(error.value)
    rig.resource_pool.ImportVApp.assert_not_called()
    rig.lease.HttpNfcLeaseAbort.assert_not_called()


@allure.title("import_ova bricht den Lease ab, wenn er in den Fehlerzustand geht")
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_059() -> None:
    rig = _Rig()
    rig.lease.state = vim.HttpNfcLease.State.error
    rig.lease.error = SimpleNamespace(msg="datastore full")

    with pytest.raises(RuntimeError, match="lease failed: datastore full"):
        rig.run()

    rig.lease.HttpNfcLeasePullFromUrls_Task.assert_not_called()
    rig.lease.HttpNfcLeaseAbort.assert_called_once_with()


@allure.title(
    "import_ova bricht den Lease ab, wenn ein Gerät des Imports kein Ziel hat"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_060() -> None:
    rig = _Rig()
    rig.lease.info.deviceUrl = []

    with pytest.raises(RuntimeError, match="no target for vm-disk1.vmdk"):
        rig.run()

    rig.lease.HttpNfcLeasePullFromUrls_Task.assert_not_called()
    rig.lease.HttpNfcLeaseAbort.assert_called_once_with()


@allure.title(
    "import_ova meldet einen Fehler beim Abbrechen des Leases nicht statt des Ursprungsfehlers"
)
@allure.description(
    "Schlägt HttpNfcLeaseAbort selbst fehl, bleibt der eigentliche Fehler des Pulls die gemeldete Ausnahme"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_061() -> None:
    rig = _Rig(task=_FakeTask(_failed("no route")))
    rig.lease.HttpNfcLeaseAbort.side_effect = vim.fault.NoPermission()

    with pytest.raises(RuntimeError, match="no route"):
        rig.run()


@allure.title(
    "import_ova liest zuerst den Descriptor und fasst den Host bei einem unerreichbaren Server nicht an"
)
@allure.description(
    "Ist der OVA-Server nicht erreichbar, scheitert der Import mit RuntimeError, bevor die Firewall des Hosts geändert "
    "oder ein Lease geöffnet wird"
)
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.CRITICAL)
def pull_importer_062() -> None:
    connection = MagicMock()
    with (
        patch("src.pull_importer.ensure_http_client_enabled") as firewall,
        pytest.raises(RuntimeError, match="can not be reached"),
    ):
        PullImporter(connection).import_ova(
            "http://127.0.0.1:1/x.ova", "VM", "ds", ["PG"]
        )

    firewall.assert_not_called()
    connection.content.ovfManager.CreateImportSpec.assert_not_called()


@allure.title("import_ova gibt den echten Descriptor der OVA an CreateImportSpec")
@allure.description(
    "Ende-zu-Ende gegen den lokalen Server: der aus dem Tar gelesene Descriptor landet unverändert als ovfDescriptor"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_063(server) -> None:
    rig = _Rig()

    with patch("src.pull_importer.ensure_http_client_enabled"):
        PullImporter(rig.connection).import_ova(
            f"{server}/ok.ova", "VM", "datastore1", ["PG"]
        )

    assert rig.manager.CreateImportSpec.call_args.kwargs["ovfDescriptor"] == _DESCRIPTOR


@allure.title("Der Pull-Wartevorgang hält den Lease mit Fortschritt am Leben")
@allure.description(
    "Nach 30 s ohne Abschluss ruft _wait_for_pull HttpNfcLeaseProgress mit dem Fortschritt des Tasks auf, davor nicht"
)
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_064() -> None:
    importer = PullImporter(MagicMock())
    lease = MagicMock()
    task = _FakeTask(_running(10), _running(42), _success())
    sleeps: list[float] = []

    with patch("src.pull_importer.time.monotonic", side_effect=[0, 10, 40]):
        importer._wait_for_pull(task, lease, 1000, sleep=sleeps.append)

    lease.HttpNfcLeaseProgress.assert_called_once_with(42)
    assert len(sleeps) == 2


@allure.title("Der Lease-Keepalive darf fehlschlagen, ohne den Pull abzubrechen")
@allure.tag("positiv-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_065() -> None:
    importer = PullImporter(MagicMock())
    lease = MagicMock()
    lease.HttpNfcLeaseProgress.side_effect = vim.fault.NoPermission()
    task = _FakeTask(_running(10), _success())

    with patch("src.pull_importer.time.monotonic", side_effect=[0, 35]):
        importer._wait_for_pull(task, lease, 1000, sleep=lambda _: None)

    lease.HttpNfcLeaseProgress.assert_called_once_with(10)


@allure.title("Ein Lease, der nicht rechtzeitig bereit wird, löst TimeoutError aus")
@allure.tag("negativ-test", "pull-importer")
@allure.feature("pull_importer")
@allure.severity(allure.severity_level.NORMAL)
def pull_importer_066() -> None:
    lease = MagicMock()
    lease.state = vim.HttpNfcLease.State.initializing

    with pytest.raises(TimeoutError, match="did not become ready"):
        PullImporter._wait_for_lease_ready(lease, timeout=-1)
