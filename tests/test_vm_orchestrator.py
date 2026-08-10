"""
Tests to validate functionality of vm_orchestrator.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest

from src import logger_adapter
from src.factories import GenericNode, NodeFactory
from src.vm_orchestrator import VMOrchestrator

logger_adapter.LoggerAdapter.is_test_run = True


def _make_orchestrator() -> tuple[VMOrchestrator, MagicMock]:
    with patch("src.vm_orchestrator.ESXiConnection") as esxi_cls:
        esxi_connection = esxi_cls.return_value
        orchestrator = VMOrchestrator("10.20.20.201", "root", "pw")
    return orchestrator, esxi_connection


@allure.title("Neue GNS3 VM ohne vorhandene VM")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm ohne vorhandene VM weder power_off_vm "
    "noch rename_vm noch set_vm_mac_address aufruft, die OVA mit Mgmt-Netz zuerst "
    "und Trunk-Netz danach importiert, die neue VM startet und deren IP zurückgibt"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_000() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.221"

    with patch("src.vm_orchestrator.OVAImporter") as importer_cls:
        importer = importer_cls.return_value
        importer.import_ova.return_value = "new-vm-handle"

        ip = orchestrator.deploy_fresh_gns3_vm(
            "/tmp/gns3.ova", "datastore1", "PG-MGMT", "PG-TRUNK"
        )

    esxi_connection.power_off_vm.assert_not_called()
    esxi_connection.rename_vm.assert_not_called()
    esxi_connection.set_vm_mac_address.assert_not_called()
    importer.import_ova.assert_called_once_with(
        "/tmp/gns3.ova", "GNS3", "datastore1", ["PG-MGMT", "PG-TRUNK"]
    )
    esxi_connection.power_on_vm.assert_called_once_with("new-vm-handle")
    assert ip == "10.20.20.221"


@allure.title("Neue GNS3 VM ersetzt bestehende VM unter Beibehaltung der MAC")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm bei bereits vorhandener VM diese "
    "herunterfährt und mit Zeitstempel umbenennt, und der neuen VM danach die "
    "MAC-Adresse der alten VM setzt, damit DHCP dieselbe IP wieder vergibt"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_001() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    old_vm = MagicMock(name="old_vm")
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:11:22:33:44:55"
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.221"

    with patch("src.vm_orchestrator.OVAImporter") as importer_cls:
        importer = importer_cls.return_value
        importer.import_ova.return_value = "new-vm-handle"

        orchestrator.deploy_fresh_gns3_vm(
            "/tmp/gns3.ova", "datastore1", "PG-MGMT", "PG-TRUNK", vm_name="GNS3"
        )

    esxi_connection.power_off_vm.assert_called_once_with(old_vm)
    rename_args = esxi_connection.rename_vm.call_args.args
    assert rename_args[0] is old_vm
    assert rename_args[1].startswith("GNS3-backup-")
    esxi_connection.set_vm_mac_address.assert_called_once_with(
        "new-vm-handle", "00:11:22:33:44:55"
    )


@allure.title("Timeout, wenn die neue VM keine IP meldet")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm einen TimeoutError wirft, wenn die "
    "neue VM innerhalb des Timeouts keine IP-Adresse meldet"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_002() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_vm_ip_address.return_value = None

    with (
        patch("src.vm_orchestrator.OVAImporter") as importer_cls,
        patch("src.vm_orchestrator.time.sleep"),
        patch("src.vm_orchestrator.time.monotonic") as monotonic,
    ):
        importer_cls.return_value.import_ova.return_value = "new-vm-handle"
        monotonic.side_effect = [0, 1, 999]

        with pytest.raises(
            TimeoutError, match=r"'GNS3' VM did not report an IP address"
        ):
            orchestrator.deploy_fresh_gns3_vm(
                "/tmp/gns3.ova",
                "datastore1",
                "PG-MGMT",
                "PG-TRUNK",
                ip_wait_timeout_seconds=5,
            )


@allure.title("GNS3 VM IP-Lookup ohne gefundene VM wirft Fehler")
@allure.description(
    "Überprüft, dass _get_gns3_vm_ip einen ConnectionError wirft, wenn keine IP "
    "für die gesuchte VM gefunden wird"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_003() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = None

    with pytest.raises(ConnectionError, match=r"Cannot connect to 'GNS3' VM"):
        orchestrator._get_gns3_vm_ip("GNS3")


@allure.title(
    "Konfigurationsdatei erstellt Port-Groups pro VLAN und schreibt die GNS3-Config"
)
@allure.description(
    "Überprüft, dass create_gns3_configuration_file für jede zugewiesene VLAN "
    "eine ESXi-Port-Group sicherstellt und anschließend die Subinterface-"
    "Konfiguration über SSH auf die GNS3 VM schreibt"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_004() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.221"

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}

    with (
        patch("src.vm_orchestrator.SSHConnection") as ssh_cls,
        patch("src.vm_orchestrator.GNS3VMInterfaceSetup") as setup_cls,
    ):
        orchestrator.create_gns3_configuration_file(nodes)

        setup = setup_cls.return_value
        setup.write_config_file.assert_called_once_with(nodes)
        ssh_cls.assert_called_once_with("10.20.20.221", "gns3", "gns3")

    esxi_connection.ensure_port_group.assert_called_once()
    vlan_name, vlan_id = esxi_connection.ensure_port_group.call_args.args
    assert vlan_name == vm.interfaces["ens160"].esxi_vlan
    assert vlan_id == 2


@allure.title(
    "GNS3-Topologie-Deployment löst die VM-IP auf und delegiert an deploy_topology"
)
@allure.description(
    "Überprüft, dass deploy_gns3_topology die IP der GNS3 VM nachschlägt und "
    "deploy_topology mit der daraus gebauten URL, dem Projektnamen und den Nodes aufruft"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_005() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    nodes = {}
    with patch("src.vm_orchestrator.deploy_topology") as deploy:
        orchestrator.deploy_gns3_topology(nodes, "Lab", vm_name="GNS3-VM")

    deploy.assert_called_once_with("http://10.20.20.231", "Lab", nodes)
