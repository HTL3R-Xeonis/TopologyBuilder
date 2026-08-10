"""
Tests to validate functionality of connections_handler.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock

import allure
import pytest

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
