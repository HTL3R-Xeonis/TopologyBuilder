"""
Tests to validate functionality of connections_handler.py
"""

__license__ = "GNU GPLv3"

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
    GNS3Connection,
    SSHConnection,
    set_esxi_template_api_url,
    set_gns3_template_api_url,
)

logger_adapter.LoggerAdapter.is_test_run = True


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
    with patch.object(GNS3Connection, "connect") as mock_connect:
        with pytest.raises(ValueError):
            GNS3Connection("not-an-ip-address", "user", "pass")
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
        GNS3Connection, "connect", return_value="fake-connection"
    ) as mock_connect:
        conn = GNS3Connection("10.20.20.235", "gns3", "secret")

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
