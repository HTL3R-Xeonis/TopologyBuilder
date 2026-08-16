"""
Tests to validate functionality of connections_handler.py
"""

__license__ = "GNU GPLv3"

import tarfile
from unittest.mock import MagicMock, patch

import allure
import paramiko
import pytest
from pyVmomi import vim

from src import logger_adapter
from src import connections_handler
from src.connections_handler import (
    APIFunctions,
    ESXiConnection,
    GenericConnection,
    SSHConnection,
    set_esxi_template_api_url,
    set_gns3_template_api_url,
)

logger_adapter.LoggerAdapter.is_test_run = True


class _MinimalConnection(GenericConnection):
    """Trivial concrete GenericConnection subclass, only for exercising the
    shared __init__/property behavior (IP validation, attribute setup,
    calling connect()) without any real connection type's extra complexity."""

    def connect(self):
        pass


def _make_esxi_connection(vm_names: list[str]) -> ESXiConnection:
    conn = ESXiConnection.__new__(ESXiConnection)
    vms = []
    for name in vm_names:
        vm = MagicMock()
        vm.name = name
        vms.append(vm)

    container_view = MagicMock()
    container_view.view = vms
    content = MagicMock()
    content.viewManager.CreateContainerView.return_value = container_view
    conn.content = content
    return conn


@allure.title("GNS3-VM wird anhand des Namens gefunden")
@allure.description(
    "Überprüft, dass find_gns3_vm eine VM findet, deren Name 'gns3' "
    "unabhängig von Groß-/Kleinschreibung als Teilstring enthält"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_000() -> None:
    conn = _make_esxi_connection(["PC4", "GNS3-VM", "PC5"])
    vm = conn.find_gns3_vm()
    assert vm.name == "GNS3-VM"


@allure.title("Keine passende VM gefunden")
@allure.description(
    "Überprüft, dass find_gns3_vm None zurückgibt, wenn keine VM 'gns3' im "
    "Namen enthält"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_001() -> None:
    conn = _make_esxi_connection(["PC4", "PC5"])
    assert conn.find_gns3_vm() is None


@allure.title("Mehrdeutigkeit bei mehreren passenden VMs wirft Fehler")
@allure.description(
    "Überprüft, dass find_gns3_vm einen ValueError wirft, statt zu raten, "
    "wenn mehr als eine VM wie eine GNS3-VM aussieht"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_002() -> None:
    conn = _make_esxi_connection(["GNS3", "GNS3-VM"])
    with pytest.raises(ValueError, match=r"Multiple VMs look like a GNS3 VM"):
        conn.find_gns3_vm()


@allure.title("Passende VMs inklusive automatisch umbenannter Duplikate finden")
@allure.description(
    "Überprüft, dass find_vms_matching sowohl die exakt benannte VM als auch "
    "von ESXi bei Namenskollisionen automatisch umbenannte Duplikate (z.B. "
    "'PC4_1', 'PC4 (1)') findet, aber keine unverwandten VMs mit ähnlichem "
    "Namen wie 'PC40' oder 'MyPC4'"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_003() -> None:
    conn = _make_esxi_connection(["PC4", "PC4_1", "PC4 (1)", "PC40", "MyPC4", "PC5"])
    matches = {vm.name for vm in conn.find_vms_matching("PC4")}
    assert matches == {"PC4", "PC4_1", "PC4 (1)"}


@allure.title("VM wird vor dem Löschen heruntergefahren")
@allure.description(
    "Überprüft, dass delete_vm eine laufende VM zuerst herunterfährt und dann zerstört"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_004() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    vm = MagicMock()
    vm.runtime.powerState = "poweredOn"
    task = MagicMock()
    task.info.state = "success"
    vm.PowerOffVM_Task.return_value = task
    vm.Destroy_Task.return_value = task

    conn.delete_vm(vm)

    vm.PowerOffVM_Task.assert_called_once()
    vm.Destroy_Task.assert_called_once()


@allure.title("Löschen einer nicht vorhandenen Port-Group ist ein No-Op")
@allure.description(
    "Überprüft, dass delete_port_group keine Löschanfrage sendet, wenn die "
    "Port-Group nicht existiert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_005() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = []
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.delete_port_group("PC4_gi0-0")

    host_system.configManager.networkSystem.RemovePortGroup.assert_not_called()


@allure.title("Vorhandene Port-Group wird gelöscht")
@allure.description(
    "Überprüft, dass delete_port_group eine vorhandene Port-Group über "
    "RemovePortGroup entfernt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_006() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    existing = MagicMock()
    existing.spec.name = "PC4_gi0-0"
    host_system = MagicMock()
    host_system.configManager.networkSystem.networkInfo.portgroup = [existing]
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.delete_port_group("PC4_gi0-0")

    host_system.configManager.networkSystem.RemovePortGroup.assert_called_once_with(
        pgName="PC4_gi0-0"
    )


@allure.title("Backup-VMs werden bei der automatischen Erkennung ignoriert")
@allure.description(
    "Überprüft, dass find_gns3_vm eine von deploy_fresh_gns3_vm umbenannte "
    "Backup-VM (Name endet auf '-backup-<Zeitstempel>') nicht als die "
    "aktuelle GNS3-VM erkennt, obwohl ihr Name weiterhin 'gns3' enthält - "
    "sonst würde ein Redeploy die falsche (bereits ersetzte) VM referenzieren"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_007() -> None:
    conn = _make_esxi_connection(["GNS3-VM-backup-20260810171954", "PC4"])
    assert conn.find_gns3_vm() is None


@allure.title("GenericConnection.__init__ lehnt eine ungültige IP-Adresse ab")
@allure.description(
    "Überprüft, dass GenericConnection.__init__ einen ValueError wirft, "
    "bevor irgendein Attribut gesetzt oder connect() aufgerufen wird, wenn "
    "die gegebene IP-Adresse ungültig ist"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_009() -> None:
    with patch.object(_MinimalConnection, "connect") as mock_connect:
        with pytest.raises(ValueError):
            _MinimalConnection("not-an-ip-address", "user", "pass")
    mock_connect.assert_not_called()


@allure.title("GenericConnection.__init__ setzt Attribute und ruft connect() auf")
@allure.description(
    "Überprüft, dass GenericConnection.__init__ IP-Adresse, Benutzername und "
    "Passwort als Properties bereitstellt und das Ergebnis von connect() "
    "als .connection speichert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_010() -> None:
    with patch.object(
        _MinimalConnection, "connect", return_value="fake-connection"
    ) as mock_connect:
        conn = _MinimalConnection("10.20.20.235", "gns3", "secret")

    mock_connect.assert_called_once()
    assert conn.ip_address == "10.20.20.235"
    assert conn.username == "gns3"
    assert conn.password == "secret"
    assert conn.connection == "fake-connection"


@allure.title("SSHConnection.connect baut eine paramiko-SSH-Verbindung auf")
@allure.description(
    "Überprüft, dass SSHConnection.connect einen paramiko.SSHClient anlegt, "
    "System-Host-Keys lädt, unbekannte Host-Keys automatisch akzeptiert und "
    "sich mit Host, Port 22, Benutzername und Passwort verbindet"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_011() -> None:
    mock_client = MagicMock()
    with patch("src.connections_handler.paramiko.SSHClient", return_value=mock_client):
        conn = SSHConnection("10.20.20.235", "gns3", "gns3")

    mock_client.load_system_host_keys.assert_called_once()
    (policy,), _ = mock_client.set_missing_host_key_policy.call_args
    assert isinstance(policy, paramiko.AutoAddPolicy)
    mock_client.connect.assert_called_once_with(
        hostname="10.20.20.235", port=22, username="gns3", password="gns3", timeout=10
    )
    assert conn.connection is mock_client


@allure.title("get_vm findet eine VM anhand des exakten Namens")
@allure.description(
    "Überprüft, dass get_vm die VM mit exakt passendem Namen zurückgibt und "
    "den ContainerView danach zerstört"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_012() -> None:
    conn = _make_esxi_connection(["PC5", "PC4"])
    target = conn.content.viewManager.CreateContainerView.return_value.view[1]

    result = conn.get_vm("PC4")

    assert result is target
    conn.content.viewManager.CreateContainerView.return_value.Destroy.assert_called_once()


@allure.title("get_vm gibt None zurück, wenn keine VM passt")
@allure.description(
    "Überprüft, dass get_vm None zurückgibt und den ContainerView trotzdem "
    "zerstört, wenn keine VM mit dem gegebenen Namen existiert"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_013() -> None:
    conn = _make_esxi_connection(["PC5"])

    assert conn.get_vm("PC4") is None
    conn.content.viewManager.CreateContainerView.return_value.Destroy.assert_called_once()


@allure.title("get_vm_ip_address findet die erste gültige IPv4-Adresse")
@allure.description(
    "Überprüft, dass get_vm_ip_address IPv6- (inkl. Link-Local) und IPv4-"
    "Link-Local-Adressen überspringt und die erste normale IPv4-Adresse "
    "zurückgibt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_014() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    nic = MagicMock()
    nic.ipAddress = ["fe80::1", "169.254.1.1", "10.20.20.235", "::1"]
    vm = MagicMock()
    vm.guest.net = [nic]
    conn.get_vm = MagicMock(return_value=vm)

    assert conn.get_vm_ip_address("GNS3-VM") == "10.20.20.235"


@allure.title(
    "get_vm_ip_address gibt None zurück, wenn nur Sonderadressen vorhanden sind"
)
@allure.description(
    "Überprüft, dass get_vm_ip_address None zurückgibt, wenn die VM nur "
    "Loopback-, Link-Local- oder Multicast-Adressen hat"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_015() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    nic = MagicMock()
    nic.ipAddress = ["127.0.0.1", "169.254.5.5", "224.0.0.1"]
    vm = MagicMock()
    vm.guest.net = [nic]
    conn.get_vm = MagicMock(return_value=vm)

    assert conn.get_vm_ip_address("GNS3-VM") is None


@allure.title("get_vm_ip_address gibt None zurück, wenn die VM nicht existiert")
@allure.description(
    "Überprüft, dass get_vm_ip_address None zurückgibt, ohne guest.net "
    "anzufassen, wenn get_vm keine VM findet"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_016() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn.get_vm = MagicMock(return_value=None)

    assert conn.get_vm_ip_address("GNS3-VM") is None


@allure.title("Falsches ESXi-Passwort wirft eine klare Fehlermeldung")
@allure.description(
    "Überprüft, dass ein VimFault (z.B. InvalidLogin) beim Verbindungsaufbau "
    "als klarer ConnectionError weitergegeben wird, statt das rohe pyVmomi-"
    "Fault-Objekt durchzureichen - das lässt Typers Pretty-Traceback-"
    "Renderer abstürzen (pyVmomis DataObject.__setattr__ lehnt das von Typer "
    "angehängte Debug-Attribut ab) und verschleiert die eigentliche, "
    "einfache Fehlerursache hinter einer verwirrenden zweiten Exception"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_008() -> None:
    fault = vim.fault.InvalidLogin(
        msg="Cannot complete login due to an incorrect user name or password."
    )
    with patch("src.connections_handler.SmartConnect", side_effect=fault):
        with pytest.raises(
            ConnectionError,
            match=r"Failed to connect to ESXi host 10\.20\.20\.202 as 'root'",
        ):
            ESXiConnection("10.20.20.202", "root", "wrong-password")


@allure.title("set_esxi_template_api_url überschreibt die ESXi-Template-API-URL")
@allure.description(
    "Überprüft, dass set_esxi_template_api_url den module-level Default für "
    "die ESXi/NFS-Template-API-Basis-URL ersetzt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_017() -> None:
    original = connections_handler._ESXI_TEMPLATE_API_BASE_URL
    try:
        set_esxi_template_api_url("http://esxi-templates.example:9000")
        assert (
            connections_handler._ESXI_TEMPLATE_API_BASE_URL
            == "http://esxi-templates.example:9000"
        )
    finally:
        set_esxi_template_api_url(original)


@allure.title("set_gns3_template_api_url überschreibt die GNS3-Template-API-URL")
@allure.description(
    "Überprüft, dass set_gns3_template_api_url den module-level Default für "
    "die GNS3-Template-API-Basis-URL ersetzt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_018() -> None:
    original = connections_handler._GNS3_TEMPLATE_API_BASE_URL
    try:
        set_gns3_template_api_url("http://gns3-templates.example:9001")
        assert (
            connections_handler._GNS3_TEMPLATE_API_BASE_URL
            == "http://gns3-templates.example:9001"
        )
    finally:
        set_gns3_template_api_url(original)


@allure.title("download_esxi_template nutzt die überschriebene ESXi-Template-API-URL")
@allure.description(
    "Überprüft end-to-end, dass download_esxi_template tatsächlich die per "
    "set_esxi_template_api_url gesetzte URL für den Download-Request "
    "verwendet, nicht den ursprünglichen Default - da jede APIFunctions-"
    "Methode den module-level Global bei jedem Aufruf frisch liest, statt "
    "ihn nur einmal beim Import als Parameter-Default zu binden"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_019(tmp_path) -> None:
    original = connections_handler._ESXI_TEMPLATE_API_BASE_URL
    try:
        set_esxi_template_api_url("http://esxi-templates.example:9000")
        dest_path = tmp_path / "template.ova"

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [b"fake-ova-bytes"]

        with (
            patch(
                "src.connections_handler.requests.get", return_value=response
            ) as mock_get,
            patch("src.connections_handler.tarfile.open") as mock_tar_open,
        ):
            mock_tar_open.return_value.__enter__.return_value.getmembers.return_value = []
            APIFunctions.download_esxi_template("Ubuntu-Server", str(dest_path))

        mock_get.assert_called_once_with(
            "http://esxi-templates.example:9000/api/download",
            params={"name": "Ubuntu-Server"},
            stream=True,
        )
    finally:
        set_esxi_template_api_url(original)


@allure.title("get_vm_network_names liefert die Port-Group jedes Ethernet-Adapters")
@allure.description(
    "Überprüft, dass get_vm_network_names für jeden VirtualEthernetCard das "
    "backing.deviceName (die Port-Group) zurückgibt, in Geräte-Reihenfolge, "
    "und andere Gerätetypen (z.B. Disks) ignoriert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_020() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    nic1 = MagicMock()
    nic1.__class__ = vim.vm.device.VirtualEthernetCard
    nic1.backing.deviceName = "PG-MGMT"
    nic2 = MagicMock()
    nic2.__class__ = vim.vm.device.VirtualEthernetCard
    nic2.backing.deviceName = "PG-GNS3-TRUNK"
    disk = MagicMock()
    disk.__class__ = vim.vm.device.VirtualDisk
    vm = MagicMock()
    vm.config.hardware.device = [nic1, disk, nic2]

    assert conn.get_vm_network_names(vm) == ["PG-MGMT", "PG-GNS3-TRUNK"]


def _host_system_with_portgroups(portgroups):
    """Builds a MagicMock host system whose configManager.networkSystem
    exposes the given list of portgroup mocks (each needs .spec.name)."""
    network_system = MagicMock()
    network_system.networkInfo.portgroup = portgroups
    host_system = MagicMock()
    host_system.configManager.networkSystem = network_system
    return host_system, network_system


# --- _wait_for_task -------------------------------------------------------


@allure.title("_wait_for_task kehrt bei sofortigem Erfolg direkt zurück")
@allure.description(
    "Überprüft, dass _wait_for_task ohne Warten zurückkehrt, wenn der Task "
    "bereits im Zustand 'success' ist"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_021() -> None:
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.success

    with patch("src.connections_handler.time.sleep") as mock_sleep:
        ESXiConnection._wait_for_task(task)

    mock_sleep.assert_not_called()


@allure.title("_wait_for_task wirft einen RuntimeError, wenn der Task fehlschlägt")
@allure.description(
    "Überprüft, dass _wait_for_task einen RuntimeError mit dem Task-Fehler "
    "wirft, wenn der Task im Zustand 'error' endet"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_022() -> None:
    task = MagicMock()
    task.info.state = vim.TaskInfo.State.error
    task.info.error = "boom"

    with pytest.raises(RuntimeError, match=r"vSphere task failed: boom"):
        ESXiConnection._wait_for_task(task)


@allure.title("_wait_for_task pollt, bis der Task fertig ist")
@allure.description(
    "Überprüft, dass _wait_for_task wiederholt wartet, solange der Task "
    "weder 'success' noch 'error' ist, und erst danach zurückkehrt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_023() -> None:
    class _FakeTaskInfo:
        def __init__(self, states):
            self._states = iter(states)

        @property
        def state(self):
            return next(self._states)

    task = MagicMock()
    # 3 states to exit the while loop, plus a 4th for the post-loop error check
    task.info = _FakeTaskInfo(
        [
            vim.TaskInfo.State.running,
            vim.TaskInfo.State.running,
            vim.TaskInfo.State.success,
            vim.TaskInfo.State.success,
        ]
    )

    with patch("src.connections_handler.time.sleep") as mock_sleep:
        ESXiConnection._wait_for_task(task)

    assert mock_sleep.call_count == 2


# --- ensure_port_group / ensure_bridging_security_policy / delete_port_group / list_port_groups ---


@allure.title(
    "ensure_port_group legt keine neue Port-Group an, wenn der Name bereits existiert"
)
@allure.description(
    "Überprüft, dass ensure_port_group AddPortGroup nicht aufruft, wenn "
    "bereits eine Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_024() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    existing = MagicMock()
    existing.spec.name = "PG-VM1_if"
    host_system, network_system = _host_system_with_portgroups([existing])
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.ensure_port_group("PG-VM1_if", 2)

    network_system.AddPortGroup.assert_not_called()


@allure.title(
    "ensure_port_group legt eine fehlende Port-Group mit der richtigen VLAN-ID an"
)
@allure.description(
    "Überprüft, dass ensure_port_group AddPortGroup mit dem gegebenen Namen, "
    "der VLAN-ID und dem vSwitch-Namen aufruft, wenn die Port-Group noch nicht existiert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_025() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    host_system, network_system = _host_system_with_portgroups([])
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.ensure_port_group("PG-VM1_if", 2)

    network_system.AddPortGroup.assert_called_once()
    spec = network_system.AddPortGroup.call_args.kwargs["portgrp"]
    assert spec.name == "PG-VM1_if"
    assert spec.vlanId == 2
    assert spec.vswitchName == "vSwitch0"


@allure.title(
    "ensure_bridging_security_policy wirft einen Fehler bei unbekannter Port-Group"
)
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy einen ValueError wirft, "
    "wenn keine Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_026() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    host_system, _ = _host_system_with_portgroups([])
    conn.get_host_system = MagicMock(return_value=host_system)

    with pytest.raises(ValueError, match=r"Port group 'PG-GNS3-TRUNK' not found"):
        conn.ensure_bridging_security_policy("PG-GNS3-TRUNK")


@allure.title(
    "ensure_bridging_security_policy überspringt ein Update, wenn bereits korrekt gesetzt"
)
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy UpdatePortGroup nicht "
    "aufruft, wenn Promiscuous Mode, MAC-Änderungen und Forged Transmits "
    "bereits alle akzeptiert werden"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_027() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    existing = MagicMock()
    existing.spec.name = "PG-GNS3-TRUNK"
    existing.spec.policy.security.allowPromiscuous = True
    existing.spec.policy.security.macChanges = True
    existing.spec.policy.security.forgedTransmits = True
    host_system, network_system = _host_system_with_portgroups([existing])
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.ensure_bridging_security_policy("PG-GNS3-TRUNK")

    network_system.UpdatePortGroup.assert_not_called()


@allure.title(
    "ensure_bridging_security_policy aktiviert die Bridging-Policy, wenn nötig"
)
@allure.description(
    "Überprüft, dass ensure_bridging_security_policy UpdatePortGroup mit "
    "aktiviertem Promiscuous Mode, MAC-Änderungen und Forged Transmits "
    "aufruft, wenn die Policy das bisher nicht erlaubt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_028() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    existing = MagicMock()
    existing.spec.name = "PG-GNS3-TRUNK"
    existing.spec.policy.security.allowPromiscuous = False
    existing.spec.policy.security.macChanges = False
    existing.spec.policy.security.forgedTransmits = False
    host_system, network_system = _host_system_with_portgroups([existing])
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.ensure_bridging_security_policy("PG-GNS3-TRUNK")

    network_system.UpdatePortGroup.assert_called_once()
    spec = network_system.UpdatePortGroup.call_args.kwargs["portgrp"]
    assert spec.policy.security.allowPromiscuous is True
    assert spec.policy.security.macChanges is True
    assert spec.policy.security.forgedTransmits is True


@allure.title("delete_port_group löscht eine vorhandene Port-Group")
@allure.description(
    "Überprüft, dass delete_port_group RemovePortGroup aufruft, wenn eine "
    "Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_029() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    existing = MagicMock()
    existing.spec.name = "PG-VM1_if"
    host_system, network_system = _host_system_with_portgroups([existing])
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.delete_port_group("PG-VM1_if")

    network_system.RemovePortGroup.assert_called_once_with(pgName="PG-VM1_if")


@allure.title("delete_port_group ist ein No-Op, wenn die Port-Group nicht existiert")
@allure.description(
    "Überprüft, dass delete_port_group RemovePortGroup nicht aufruft, wenn "
    "keine Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_030() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    host_system, network_system = _host_system_with_portgroups([])
    conn.get_host_system = MagicMock(return_value=host_system)

    conn.delete_port_group("PG-VM1_if")

    network_system.RemovePortGroup.assert_not_called()


@allure.title("list_port_groups liefert Name, VLAN-ID und vSwitch jeder Port-Group")
@allure.description(
    "Überprüft, dass list_port_groups für jede Port-Group ein Dict mit "
    "name/vlan_id/vswitch aus deren spec zurückgibt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_031() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    pg = MagicMock()
    pg.spec.name = "PG-VM1_if"
    pg.spec.vlanId = 2
    pg.spec.vswitchName = "vSwitch0"
    host_system, _ = _host_system_with_portgroups([pg])
    conn.get_host_system = MagicMock(return_value=host_system)

    assert conn.list_port_groups() == [
        {"name": "PG-VM1_if", "vlan_id": 2, "vswitch": "vSwitch0"}
    ]


# --- find_datastore / find_network -----------------------------------------


@allure.title("find_datastore findet einen Datastore anhand des Namens")
@allure.description(
    "Überprüft, dass find_datastore den Datastore mit passendem Namen aus "
    "der ContainerView zurückgibt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_032() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    datastore = MagicMock()
    datastore.name = "datastore1"
    container_view = MagicMock()
    container_view.view = [datastore]
    content = MagicMock()
    content.viewManager.CreateContainerView.return_value = container_view
    conn.content = content

    assert conn.find_datastore("datastore1") is datastore


@allure.title("find_datastore wirft einen Fehler, wenn kein Datastore passt")
@allure.description(
    "Überprüft, dass find_datastore einen ValueError wirft, wenn kein "
    "Datastore mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_033() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    container_view = MagicMock()
    container_view.view = []
    content = MagicMock()
    content.viewManager.CreateContainerView.return_value = container_view
    conn.content = content

    with pytest.raises(ValueError, match=r"Datastore 'datastore1' not found"):
        conn.find_datastore("datastore1")


@allure.title("find_network findet ein Netzwerk anhand des Namens")
@allure.description(
    "Überprüft, dass find_network das Netzwerk/die Port-Group mit passendem "
    "Namen aus der ContainerView zurückgibt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_034() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    network = MagicMock()
    network.name = "PG-GNS3-TRUNK"
    container_view = MagicMock()
    container_view.view = [network]
    content = MagicMock()
    content.viewManager.CreateContainerView.return_value = container_view
    conn.content = content

    assert conn.find_network("PG-GNS3-TRUNK") is network


@allure.title("find_network wirft einen Fehler, wenn kein Netzwerk passt")
@allure.description(
    "Überprüft, dass find_network einen ValueError wirft, wenn kein "
    "Netzwerk/keine Port-Group mit dem gesuchten Namen existiert"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_035() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    container_view = MagicMock()
    container_view.view = []
    content = MagicMock()
    content.viewManager.CreateContainerView.return_value = container_view
    conn.content = content

    with pytest.raises(
        ValueError, match=r"Network/port group 'PG-GNS3-TRUNK' not found"
    ):
        conn.find_network("PG-GNS3-TRUNK")


# --- get_vm_mac_address / set_vm_mac_address / add_vm_network_adapters -----


@allure.title("get_vm_mac_address liefert die MAC des ersten Netzwerkadapters")
@allure.description(
    "Überprüft, dass get_vm_mac_address die MAC-Adresse des ersten "
    "VirtualEthernetCard-Geräts zurückgibt und andere Gerätetypen überspringt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_036() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    disk = MagicMock()
    disk.__class__ = vim.vm.device.VirtualDisk
    nic = MagicMock()
    nic.__class__ = vim.vm.device.VirtualEthernetCard
    nic.macAddress = "00:11:22:33:44:55"
    vm = MagicMock()
    vm.config.hardware.device = [disk, nic]

    assert conn.get_vm_mac_address(vm) == "00:11:22:33:44:55"


@allure.title("get_vm_mac_address liefert None ohne Netzwerkadapter")
@allure.description(
    "Überprüft, dass get_vm_mac_address None zurückgibt, wenn die VM kein "
    "VirtualEthernetCard-Gerät hat"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_037() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    disk = MagicMock()
    disk.__class__ = vim.vm.device.VirtualDisk
    vm = MagicMock()
    vm.config.hardware.device = [disk]

    assert conn.get_vm_mac_address(vm) is None


@allure.title("set_vm_mac_address rekonfiguriert den ersten Netzwerkadapter")
@allure.description(
    "Überprüft, dass set_vm_mac_address die MAC-Adresse und den Adresstyp "
    "des ersten Netzwerkadapters setzt und ReconfigVM_Task darauf wartet"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_038() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    nic = MagicMock()
    nic.__class__ = vim.vm.device.VirtualEthernetCard
    vm = MagicMock()
    vm.config.hardware.device = [nic]

    conn.set_vm_mac_address(vm, "00:11:22:33:44:55")

    assert nic.macAddress == "00:11:22:33:44:55"
    assert nic.addressType == "manual"
    vm.ReconfigVM_Task.assert_called_once()
    conn._wait_for_task.assert_called_once_with(vm.ReconfigVM_Task.return_value)


@allure.title("set_vm_mac_address wirft einen Fehler ohne Netzwerkadapter")
@allure.description(
    "Überprüft, dass set_vm_mac_address einen ValueError wirft, wenn die VM "
    "kein VirtualEthernetCard-Gerät hat, statt stillschweigend nichts zu tun"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_039() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    vm = MagicMock()
    vm.name = "VM1"
    vm.config.hardware.device = []

    with pytest.raises(ValueError, match=r"VM 'VM1' has no network adapter"):
        conn.set_vm_mac_address(vm, "00:11:22:33:44:55")


@allure.title("add_vm_network_adapters fügt für jedes Netzwerk einen Adapter hinzu")
@allure.description(
    "Überprüft, dass add_vm_network_adapters für jeden gegebenen Netzwerk-"
    "namen einen neuen VirtualVmxnet3-Adapter über find_network auflöst und "
    "ReconfigVM_Task mit allen Änderungen aufruft"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_040() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    # pyVmomi type-checks the 'network' field against vim.Network at
    # assignment time, so a plain MagicMock is rejected - use real
    # (unconnected) DataObject instances instead.
    conn.find_network = MagicMock(side_effect=lambda name: vim.Network(moId=name))
    vm = MagicMock()
    vm.name = "GNS3-VM"

    conn.add_vm_network_adapters(vm, ["PG-MGMT", "PG-GNS3-TRUNK"])

    assert conn.find_network.call_count == 2
    conn.find_network.assert_any_call("PG-MGMT")
    conn.find_network.assert_any_call("PG-GNS3-TRUNK")
    config_spec = vm.ReconfigVM_Task.call_args.kwargs["spec"]
    assert len(config_spec.deviceChange) == 2
    conn._wait_for_task.assert_called_once_with(vm.ReconfigVM_Task.return_value)


# --- power_off_vm / power_on_vm / delete_vm / rename_vm ---------------------


@allure.title("power_off_vm tut nichts, wenn die VM bereits ausgeschaltet ist")
@allure.description(
    "Überprüft, dass power_off_vm PowerOffVM_Task nicht aufruft, wenn die "
    "VM bereits im Zustand 'poweredOff' ist"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_041() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOff

    conn.power_off_vm(vm)

    vm.PowerOffVM_Task.assert_not_called()


@allure.title("power_off_vm schaltet eine laufende VM aus")
@allure.description(
    "Überprüft, dass power_off_vm PowerOffVM_Task aufruft und darauf "
    "wartet, wenn die VM eingeschaltet ist"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_042() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOn

    conn.power_off_vm(vm)

    conn._wait_for_task.assert_called_once_with(vm.PowerOffVM_Task.return_value)


@allure.title("power_on_vm tut nichts, wenn die VM bereits eingeschaltet ist")
@allure.description(
    "Überprüft, dass power_on_vm PowerOnVM_Task nicht aufruft, wenn die VM "
    "bereits im Zustand 'poweredOn' ist"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_043() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOn

    conn.power_on_vm(vm)

    vm.PowerOnVM_Task.assert_not_called()


@allure.title("power_on_vm schaltet eine ausgeschaltete VM ein")
@allure.description(
    "Überprüft, dass power_on_vm PowerOnVM_Task aufruft und darauf wartet, "
    "wenn die VM ausgeschaltet ist"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_044() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOff

    conn.power_on_vm(vm)

    conn._wait_for_task.assert_called_once_with(vm.PowerOnVM_Task.return_value)


@allure.title("delete_vm schaltet die VM aus und löscht sie dann")
@allure.description(
    "Überprüft, dass delete_vm zuerst power_off_vm aufruft und danach auf "
    "Destroy_Task wartet"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_045() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn.power_off_vm = MagicMock()
    conn._wait_for_task = MagicMock()
    vm = MagicMock()

    conn.delete_vm(vm)

    conn.power_off_vm.assert_called_once_with(vm)
    conn._wait_for_task.assert_called_once_with(vm.Destroy_Task.return_value)


@allure.title("rename_vm benennt die VM um")
@allure.description(
    "Überprüft, dass rename_vm Rename_Task mit dem neuen Namen aufruft und "
    "darauf wartet"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_046() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    conn._wait_for_task = MagicMock()
    vm = MagicMock()

    conn.rename_vm(vm, "GNS3-backup-20260811120000")

    vm.Rename_Task.assert_called_once_with(newName="GNS3-backup-20260811120000")
    conn._wait_for_task.assert_called_once_with(vm.Rename_Task.return_value)


# --- APIFunctions: _send_get_request / non-literal template lookups --------


@allure.title("_send_get_request liefert die JSON-Antwort")
@allure.description(
    "Überprüft, dass _send_get_request das geparste JSON zurückgibt, wenn "
    "die Antwort gültiges JSON ist"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_047() -> None:
    response = MagicMock()
    response.json.return_value = {"templates": []}
    with patch("src.connections_handler.requests.get", return_value=response):
        result = APIFunctions._send_get_request("http://example/api/templates")

    assert result == {"templates": []}


@allure.title(
    "_send_get_request faellt auf den rohen Text zurueck, wenn die Antwort kein JSON ist"
)
@allure.description(
    "Überprüft, dass _send_get_request response.text zurückgibt, wenn "
    "response.json() einen ValueError wirft"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_048() -> None:
    response = MagicMock()
    response.json.side_effect = ValueError("not json")
    response.text = "plain text body"
    with patch("src.connections_handler.requests.get", return_value=response):
        result = APIFunctions._send_get_request("http://example/api/templates")

    assert result == "plain text body"


@allure.title("get_esxi_template_names ruft ausserhalb des Testmodus die echte API auf")
@allure.description(
    "Überprüft, dass get_esxi_template_names bei deaktiviertem "
    "LITERAL_API_VALUES tatsächlich _send_get_request aufruft und die "
    "Template-Namen aus der Antwort extrahiert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_049() -> None:
    with (
        patch(
            "src.connections_handler.Settings.Testing.GithubWorkflow.LITERAL_API_VALUES",
            False,
        ),
        patch(
            "src.connections_handler.APIFunctions._send_get_request",
            return_value={
                "templates": [{"name": "Ubuntu-Server"}, {"name": "Rocky 9.2"}]
            },
        ) as mock_get,
    ):
        result = APIFunctions.get_esxi_template_names()

    mock_get.assert_called_once_with(
        f"{connections_handler._ESXI_TEMPLATE_API_BASE_URL}/api/templates"
    )
    assert result == {"Ubuntu-Server", "Rocky 9.2"}


@allure.title("get_gns3_template_names ruft ausserhalb des Testmodus die echte API auf")
@allure.description(
    "Überprüft, dass get_gns3_template_names bei deaktiviertem "
    "LITERAL_API_VALUES tatsächlich _send_get_request aufruft und die "
    "Template-Namen aus der Antwort extrahiert"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_050() -> None:
    with (
        patch(
            "src.connections_handler.Settings.Testing.GithubWorkflow.LITERAL_API_VALUES",
            False,
        ),
        patch(
            "src.connections_handler.APIFunctions._send_get_request",
            return_value={"templates": [{"name": "VPCS"}]},
        ) as mock_get,
    ):
        result = APIFunctions.get_gns3_template_names()

    mock_get.assert_called_once_with(
        f"{connections_handler._GNS3_TEMPLATE_API_BASE_URL}/api/templates"
    )
    assert result == {"VPCS"}


@allure.title(
    "download_esxi_template wiederholt den Download nach einem beschädigten Archiv"
)
@allure.description(
    "Überprüft, dass download_esxi_template bei einem tarfile.TarError im "
    "ersten Versuch einen zweiten Versuch startet und bei dessen Erfolg "
    "normal zurückkehrt"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_051(tmp_path) -> None:
    dest_path = tmp_path / "template.ova"
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"fake-bytes"]

    with (
        patch("src.connections_handler.requests.get", return_value=response),
        patch("src.connections_handler.tarfile.open") as mock_tar_open,
    ):
        mock_tar_open.return_value.__enter__.side_effect = [
            tarfile.ReadError("truncated"),
            MagicMock(getmembers=MagicMock(return_value=[])),
        ]
        APIFunctions.download_esxi_template("Ubuntu-Server", str(dest_path))

    assert mock_tar_open.call_count == 2


@allure.title(
    "download_esxi_template wirft nach erschöpften Versuchen einen RuntimeError"
)
@allure.description(
    "Überprüft, dass download_esxi_template nach _OVA_DOWNLOAD_MAX_ATTEMPTS "
    "durchgehend beschädigten Downloads einen RuntimeError mit dem letzten "
    "Fehler wirft"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.CRITICAL)
def connections_handler_052(tmp_path) -> None:
    dest_path = tmp_path / "template.ova"
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [b"fake-bytes"]

    with (
        patch("src.connections_handler.requests.get", return_value=response),
        patch("src.connections_handler.tarfile.open") as mock_tar_open,
    ):
        mock_tar_open.return_value.__enter__.side_effect = tarfile.ReadError(
            "truncated"
        )

        with pytest.raises(RuntimeError, match=r"Failed to download a complete OVA"):
            APIFunctions.download_esxi_template("Ubuntu-Server", str(dest_path))

    assert mock_tar_open.call_count == 3


@allure.title("is_vm_powered_on erkennt eine eingeschaltete VM")
@allure.description(
    "Überprüft, dass is_vm_powered_on True zurückgibt, wenn "
    "vm.runtime.powerState 'poweredOn' ist"
)
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_056() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOn

    assert conn.is_vm_powered_on(vm) is True


@allure.title("is_vm_powered_on erkennt eine ausgeschaltete VM")
@allure.description(
    "Überprüft, dass is_vm_powered_on False zurückgibt, wenn "
    "vm.runtime.powerState nicht 'poweredOn' ist"
)
@allure.tag("negativ-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_057() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    vm = MagicMock()
    vm.runtime.powerState = vim.VirtualMachine.PowerState.poweredOff

    assert conn.is_vm_powered_on(vm) is False


@allure.title("get_vm_uuid liefert die instanceUuid der VM")
@allure.description("Überprüft, dass get_vm_uuid vm.config.instanceUuid zurückgibt")
@allure.tag("positiv-test", "connections_handler")
@allure.feature("connections_handler")
@allure.severity(allure.severity_level.NORMAL)
def connections_handler_058() -> None:
    conn = ESXiConnection.__new__(ESXiConnection)
    vm = MagicMock()
    vm.config.instanceUuid = "5032c8a5-9f1e-4b3c-8f6a-1234567890ab"

    assert conn.get_vm_uuid(vm) == "5032c8a5-9f1e-4b3c-8f6a-1234567890ab"
