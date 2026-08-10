"""
Tests to validate functionality of connections_handler.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest
from pyVmomi import vim

from src import logger_adapter
from src.connections_handler import ESXiConnection

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
