"""
Tests to validate that the notes about automatically corrected interface names reach the caller of TopologyBackend
(src/backend.py, src/vm_orchestrator/vm_orchestrator.py)
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock

import allure

from src.backend import TopologyBackend
from src.vm_orchestrator.vm_orchestrator import VMOrchestrator


@allure.title("take_link_warnings gibt die Hinweise der GNS3-Connection zurück")
@allure.description(
    "Überprüft, dass VMOrchestrator.take_link_warnings die Warnungen der Connection des letzten Deploys einmal "
    "zurückgibt und die Connection danach leer ist"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def link_warnings_001() -> None:
    orchestrator = VMOrchestrator.__new__(VMOrchestrator)
    connection = MagicMock()
    connection.take_warnings.side_effect = [["R1: gi0/2 -> Ethernet2"], []]
    orchestrator._gns3_conn = connection

    assert orchestrator.take_link_warnings() == ["R1: gi0/2 -> Ethernet2"]
    assert orchestrator.take_link_warnings() == []


@allure.title("take_link_warnings ist leer, solange noch nichts deployt wurde")
@allure.description(
    "Überprüft, dass take_link_warnings eine leere Liste liefert, wenn der Orchestrator noch keine GNS3-Connection "
    "hat (auch wenn er ohne __init__ erzeugt wurde)"
)
@allure.tag("positiv-test", "vm-orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def link_warnings_002() -> None:
    orchestrator = VMOrchestrator.__new__(VMOrchestrator)
    assert orchestrator.take_link_warnings() == []
    orchestrator._gns3_conn = None
    assert orchestrator.take_link_warnings() == []


@allure.title(
    "TopologyBackend.take_warnings reicht die Hinweise des Orchestrators durch"
)
@allure.description(
    "Überprüft, dass TopologyBackend.take_warnings die Liste von VMOrchestrator.take_link_warnings zurückgibt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.NORMAL)
def link_warnings_003() -> None:
    backend = TopologyBackend.__new__(TopologyBackend)
    backend._orchestrator = MagicMock()
    backend._orchestrator.take_link_warnings.return_value = ["a", "b"]

    assert backend.take_warnings() == ["a", "b"]
