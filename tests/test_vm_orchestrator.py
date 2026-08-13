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
        # No VM auto-detected by default, so tests that pass an explicit
        # vm_name (or rely on the 'GNS3' fallback) aren't affected by
        # auto-detection unless they explicitly opt into testing it.
        esxi_connection.find_gns3_vm.return_value = None
        orchestrator = VMOrchestrator("10.20.20.201", "root", "pw")
    return orchestrator, esxi_connection


@allure.title("__init__ verbindet sich mit dem ESXi-Host und speichert die Verbindung")
@allure.description(
    "Überprüft, dass VMOrchestrator.__init__ eine ESXiConnection mit den "
    "gegebenen Zugangsdaten (Host, Benutzername, Passwort) aufbaut und das "
    "Ergebnis als self.esxi_connection speichert"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_010() -> None:
    with patch("src.vm_orchestrator.ESXiConnection") as esxi_cls:
        orchestrator = VMOrchestrator("10.20.20.202", "root", "secret")

    esxi_cls.assert_called_once_with("10.20.20.202", "root", "secret")
    assert orchestrator.esxi_connection is esxi_cls.return_value


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
        orchestrator.create_gns3_configuration_file(nodes, vm_name="GNS3")

        setup = setup_cls.return_value
        setup.write_config_file.assert_called_once_with(nodes, trunk_interface=None)
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

    deploy.assert_called_once_with(
        "http://10.20.20.231", "Lab", nodes, incremental=False
    )


@allure.title("GNS3-VM-Name wird automatisch erkannt, wenn keiner angegeben ist")
@allure.description(
    "Überprüft, dass _get_gns3_vm_ip ohne angegebenen VM-Namen die gefundene "
    "GNS3-VM automatisch verwendet, statt einen Namen zu verlangen"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_006() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    found_vm = MagicMock(name="GNS3-VM")
    found_vm.name = "GNS3-VM"
    esxi_connection.find_gns3_vm.return_value = found_vm
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    ip = orchestrator._get_gns3_vm_ip(None)

    esxi_connection.find_gns3_vm.assert_called_once()
    esxi_connection.get_vm_ip_address.assert_called_once_with("GNS3-VM")
    assert ip == "10.20.20.231"


@allure.title("Fehler, wenn keine GNS3-VM automatisch gefunden wird")
@allure.description(
    "Überprüft, dass _get_gns3_vm_ip einen ValueError wirft, wenn kein "
    "VM-Name angegeben ist und auch keine VM automatisch gefunden wird, "
    "statt stillschweigend einen falschen Standardnamen zu verwenden"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_007() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.find_gns3_vm.return_value = None

    with pytest.raises(ValueError, match=r"Could not find a GNS3 VM automatically"):
        orchestrator._get_gns3_vm_ip(None)


@allure.title("deploy_fresh_gns3_vm fällt ohne gefundene VM auf 'GNS3' zurück")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm ohne angegebenen VM-Namen und ohne "
    "automatisch gefundene VM auf den Standardnamen 'GNS3' zurückfällt, da "
    "in diesem Fall noch keine VM existieren muss"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_008() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.find_gns3_vm.return_value = None
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.221"

    with patch("src.vm_orchestrator.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = "new-vm-handle"
        orchestrator.deploy_fresh_gns3_vm(
            "/tmp/gns3.ova", "datastore1", "PG-MGMT", "PG-TRUNK"
        )

    importer_cls.return_value.import_ova.assert_called_once_with(
        "/tmp/gns3.ova", "GNS3", "datastore1", ["PG-MGMT", "PG-TRUNK"]
    )


@allure.title("Alte ESXi-VMs und Port-Groups werden vor dem Redeploy gelöscht")
@allure.description(
    "Überprüft, dass delete_stale_esxi_resources für jede ESXi-gehostete "
    "Node alle passenden VMs löscht und die Port-Group jeder ihrer "
    "Interfaces löscht, GNS3-gehostete Nodes aber ignoriert"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_009() -> None:
    orchestrator, esxi_connection = _make_orchestrator()

    nf = NodeFactory()
    gns3_node = nf.create_node("VPCS", "ROUTER", "R1")
    esxi_node: GenericNode = nf.create_node("Ubuntu-Server", "VM", "PC4")
    esxi_node.add_interface("ens160")
    nodes = {"R1": gns3_node, "PC4": esxi_node}

    stale_vm = MagicMock()
    stale_vm.name = "PC4_1"
    esxi_connection.find_vms_matching.return_value = [stale_vm]

    orchestrator.delete_stale_esxi_resources(nodes)

    esxi_connection.find_vms_matching.assert_called_once_with("PC4")
    esxi_connection.delete_vm.assert_called_once_with(stale_vm)
    esxi_connection.delete_port_group.assert_called_once_with(
        esxi_node.interfaces["ens160"].esxi_vlan
    )


@allure.title("GNS3-Deployment erfasst SSH-Diagnosen bei Konsolen-Port-Kollision")
@allure.description(
    "Überprüft, dass deploy_gns3_topology bei einem RuntimeError mit "
    "Konsolen-Port-Kollisions-Signatur per SSH auf die GNS3-VM zugreift, um "
    "'ss -tlnp' und 'ps aux | grep qemu' zu protokollieren, und den "
    "ursprünglichen Fehler danach trotzdem weiterwirft"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_011() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    with (
        patch("src.vm_orchestrator.deploy_topology") as deploy,
        patch("src.vm_orchestrator.SSHConnection") as ssh_cls,
    ):
        deploy.side_effect = RuntimeError(
            "Failed to start 1/1 node(s): ['R1']: address already in use"
        )
        ssh_connection = ssh_cls.return_value
        stdout = MagicMock()
        stdout.read.return_value = b"tcp LISTEN 0 128 *:5000"
        ssh_connection.exec_command.return_value = (None, stdout, None)

        with pytest.raises(RuntimeError, match=r"address already in use"):
            orchestrator.deploy_gns3_topology({}, "Lab", vm_name="GNS3-VM")

    ssh_cls.assert_called_once_with("10.20.20.231", "gns3", "gns3")
    assert ssh_connection.exec_command.call_count == 2


@allure.title("GNS3-Deployment versucht keine SSH-Diagnose bei anderen Fehlern")
@allure.description(
    "Überprüft, dass deploy_gns3_topology bei einem RuntimeError ohne "
    "Konsolen-Port-Kollisions-Signatur keine SSH-Verbindung aufbaut und den "
    "Fehler unverändert weiterwirft"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_012() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    with (
        patch("src.vm_orchestrator.deploy_topology") as deploy,
        patch("src.vm_orchestrator.SSHConnection") as ssh_cls,
    ):
        deploy.side_effect = RuntimeError("Failed to start 1/1 node(s): ['R1']: boom")

        with pytest.raises(RuntimeError, match=r"boom"):
            orchestrator.deploy_gns3_topology({}, "Lab", vm_name="GNS3-VM")

    ssh_cls.assert_not_called()


@allure.title("SSH-Diagnosefehler maskiert den ursprünglichen Deployment-Fehler nicht")
@allure.description(
    "Überprüft, dass deploy_gns3_topology den ursprünglichen "
    "Konsolen-Port-Kollisionsfehler weiterhin wirft, selbst wenn die "
    "SSH-Diagnose selbst fehlschlägt (z.B. SSH-Verbindung nicht möglich)"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_013() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    with (
        patch("src.vm_orchestrator.deploy_topology") as deploy,
        patch("src.vm_orchestrator.SSHConnection") as ssh_cls,
    ):
        deploy.side_effect = RuntimeError(
            "Failed to start 1/1 node(s): ['R1']: address already in use"
        )
        ssh_cls.side_effect = ConnectionError("no route to host")

        with pytest.raises(RuntimeError, match=r"address already in use"):
            orchestrator.deploy_gns3_topology({}, "Lab", vm_name="GNS3-VM")


@allure.title("destroy_gns3_topology löscht alle Nodes im aufgelösten Projekt")
@allure.description(
    "Überprüft, dass destroy_gns3_topology die IP der GNS3-VM nachschlägt, "
    "das Projekt per Namen auflöst und anschließend alle seine Nodes löscht"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_014() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.get_or_create_project.return_value = {"project_id": "proj-1"}

        orchestrator.destroy_gns3_topology("Lab", vm_name="GNS3-VM")

    client_cls.assert_called_once_with("http://10.20.20.231")
    client.get_or_create_project.assert_called_once_with("Lab")
    client.delete_all_nodes.assert_called_once_with("proj-1")


@allure.title(
    "create_gns3_configuration_file bricht ab, wenn die Trunk-NIC falsch verkabelt ist"
)
@allure.description(
    "Überprüft, dass create_gns3_configuration_file einen ValueError wirft, "
    "wenn die GNS3-VM keinen Netzwerkadapter hat, der mit der angegebenen "
    "Trunk-Port-Group verbunden ist - ESXi meldet diese Fehlkonfiguration "
    "sonst nirgendwo, die Cloud-Node-Bridge würde einfach stillschweigend "
    "nicht funktionieren"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_015() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.221"
    trunk_vm = MagicMock()
    esxi_connection.get_vm.return_value = trunk_vm
    esxi_connection.get_vm_network_names.return_value = ["PG-MGMT"]

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}

    with pytest.raises(
        ValueError, match=r"no network adapter connected to port group 'PG-GNS3-TRUNK'"
    ):
        orchestrator.create_gns3_configuration_file(
            nodes, vm_name="GNS3", trunk_network_name="PG-GNS3-TRUNK"
        )

    esxi_connection.get_vm.assert_called_once_with("GNS3")
    esxi_connection.get_vm_network_names.assert_called_once_with(trunk_vm)


@allure.title(
    "create_gns3_configuration_file läuft normal weiter, wenn die Trunk-NIC "
    "korrekt verkabelt ist"
)
@allure.description(
    "Überprüft, dass create_gns3_configuration_file mit einer korrekt "
    "verkabelten Trunk-NIC ganz normal bis zum Schreiben der GNS3-Konfiguration "
    "durchläuft"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_016() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.221"
    esxi_connection.get_vm.return_value = MagicMock()
    esxi_connection.get_vm_network_names.return_value = ["PG-MGMT", "PG-GNS3-TRUNK"]

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}

    with (
        patch("src.vm_orchestrator.SSHConnection") as ssh_cls,
        patch("src.vm_orchestrator.GNS3VMInterfaceSetup") as setup_cls,
    ):
        orchestrator.create_gns3_configuration_file(
            nodes, vm_name="GNS3", trunk_network_name="PG-GNS3-TRUNK"
        )
        setup_cls.return_value.write_config_file.assert_called_once()

    ssh_cls.assert_called_once_with("10.20.20.221", "gns3", "gns3")


@allure.title(
    "Trunk-Verkabelungs-Check überspringt sich selbst, wenn die VM nicht gefunden wird"
)
@allure.description(
    "Überprüft, dass create_gns3_configuration_file bei get_vm=None keinen "
    "eigenen Fehler zur Verkabelung wirft, sondern die spätere IP-Abfrage "
    "die eigentliche 'VM nicht gefunden'-Fehlermeldung liefert"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_017() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_vm_ip_address.return_value = None

    with pytest.raises(ConnectionError, match=r"Cannot connect to 'GNS3' VM"):
        orchestrator.create_gns3_configuration_file(
            {}, vm_name="GNS3", trunk_network_name="PG-GNS3-TRUNK"
        )

    esxi_connection.get_vm_network_names.assert_not_called()


@allure.title(
    "deploy_esxi_nodes lädt jedes Image nur einmal herunter und importiert jeden ESXi-Knoten"
)
@allure.description(
    "Überprüft, dass deploy_esxi_nodes GNS3-gehostete Knoten überspringt, "
    "für jeden ESXi-gehosteten Knoten die passende OVA importiert und die "
    "resultierende VM einschaltet - und ein Image, das sich mehrere Knoten "
    "teilen, nur ein einziges Mal herunterlädt statt einmal pro Knoten"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_018() -> None:
    orchestrator, esxi_connection = _make_orchestrator()

    nf = NodeFactory()
    gns3_node = nf.create_node("VPCS", "ROUTER", "R1")
    vm1: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm1.add_interface("ens160")
    vm2: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM2")
    vm2.add_interface("ens160")
    nodes = {"R1": gns3_node, "VM1": vm1, "VM2": vm2}

    with (
        patch(
            "src.vm_orchestrator.APIFunctions.download_esxi_template"
        ) as mock_download,
        patch("src.vm_orchestrator.OVAImporter") as importer_cls,
    ):
        importer = importer_cls.return_value
        importer.import_ova.side_effect = ["vm1-handle", "vm2-handle"]

        orchestrator.deploy_esxi_nodes(nodes, "datastore1")

    mock_download.assert_called_once()
    assert importer.import_ova.call_count == 2
    esxi_connection.power_on_vm.assert_any_call("vm1-handle")
    esxi_connection.power_on_vm.assert_any_call("vm2-handle")


@allure.title("deploy_esxi_nodes legt das OVA-Cache-Verzeichnis an, falls angegeben")
@allure.description(
    "Überprüft, dass deploy_esxi_nodes einen gegebenen download_dir "
    "erstellt, bevor die OVA-Downloads darin gestaged werden"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_019(tmp_path) -> None:
    orchestrator, _ = _make_orchestrator()
    download_dir = tmp_path / "ova-cache"

    with patch("src.vm_orchestrator.OVAImporter"):
        orchestrator.deploy_esxi_nodes({}, "datastore1", download_dir=str(download_dir))

    assert download_dir.is_dir()


@allure.title(
    "deploy_esxi_nodes überspringt bereits vorhandene VMs im incremental-Modus"
)
@allure.description(
    "Überprüft, dass deploy_esxi_nodes mit incremental=True weder OVA "
    "herunterlädt noch importiert, wenn find_vms_matching bereits eine "
    "passende VM findet"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_020() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}
    esxi_connection.find_vms_matching.return_value = [MagicMock()]

    with (
        patch(
            "src.vm_orchestrator.APIFunctions.download_esxi_template"
        ) as mock_download,
        patch("src.vm_orchestrator.OVAImporter") as importer_cls,
    ):
        orchestrator.deploy_esxi_nodes(nodes, "datastore1", incremental=True)

    mock_download.assert_not_called()
    importer_cls.return_value.import_ova.assert_not_called()


@allure.title(
    "plan_destroy meldet zu löschende ESXi-Ressourcen und GNS3-Nodes, löscht aber nichts"
)
@allure.description(
    "Überprüft, dass plan_destroy die vorhandene ESXi-VM, ihre Port-Group "
    "und den vorhandenen GNS3-Node als 'würde gelöscht' meldet, ohne "
    "delete_vm/delete_all_nodes tatsächlich aufzurufen"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_021() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}

    stale_vm = MagicMock()
    stale_vm.name = "VM1"
    esxi_connection.find_vms_matching.return_value = [stale_vm]

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.list_projects.return_value = [{"project_id": "p1", "name": "Lab"}]
        client.list_nodes.return_value = [{"node_id": "n1", "name": "R1"}]

        lines = orchestrator.plan_destroy(nodes, "Lab", vm_name="GNS3-VM")

    esxi_connection.delete_vm.assert_not_called()
    client.delete_all_nodes.assert_not_called()
    assert any("Would delete ESXi VM 'VM1'" in line for line in lines)
    assert any("Would delete GNS3 node 'R1'" in line for line in lines)


@allure.title("plan_destroy meldet ein nicht existierendes GNS3-Projekt")
@allure.description(
    "Überprüft, dass plan_destroy meldet, dass das GNS3-Projekt nicht "
    "existiert, statt einen Fehler zu werfen"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_022() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"
    esxi_connection.find_vms_matching.return_value = []

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client_cls.return_value.list_projects.return_value = []
        lines = orchestrator.plan_destroy({}, "Lab", vm_name="GNS3-VM")

    assert any("does not exist" in line for line in lines)


@allure.title("plan_deploy meldet zu erstellende Port-Groups, VMs und GNS3-Nodes")
@allure.description(
    "Überprüft, dass plan_deploy fehlende Port-Groups, zu importierende "
    "ESXi-VMs und zu erstellende GNS3-Nodes meldet, ohne irgendetwas zu "
    "verändern"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_023() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"
    esxi_connection.list_port_groups.return_value = []
    esxi_connection.find_vms_matching.return_value = []

    nf = NodeFactory()
    gns3_node = nf.create_node("VPCS", "ROUTER", "R1")
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"R1": gns3_node, "VM1": vm}

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client_cls.return_value.list_projects.return_value = []

        lines = orchestrator.plan_deploy(nodes, "Lab", vm_name="GNS3-VM")

    esxi_connection.ensure_port_group.assert_not_called()
    assert any("Would create ESXi port group" in line for line in lines)
    assert any("Would import ESXi VM 'VM1'" in line for line in lines)
    assert any("Would create GNS3 node 'R1'" in line for line in lines)


@allure.title(
    "plan_deploy überspringt den GNS3-Teil, wenn --fresh-gns3-vm laufen würde"
)
@allure.description(
    "Überprüft, dass plan_deploy mit fresh_gns3_vm=True keinen GNS3Client "
    "instanziiert, da die GNS3-VM in diesem Fall erst noch ersetzt würde"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.NORMAL)
def vm_orchestrator_024() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.list_port_groups.return_value = []

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        lines = orchestrator.plan_deploy({}, "Lab", fresh_gns3_vm=True)

    client_cls.assert_not_called()
    assert any("--fresh-gns3-vm" in line for line in lines)


@allure.title(
    "verify_topology meldet gestarteten GNS3-Node und eingeschaltete ESXi-VM als bestanden"
)
@allure.description(
    "Überprüft, dass verify_topology für einen gestarteten GNS3-Node und "
    "eine eingeschaltete ESXi-VM mit gemeldeter IP jeweils einen "
    "bestandenen Check zurückgibt"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_025() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"
    esxi_connection.list_port_groups.return_value = []
    esxi_connection.get_vm.return_value = MagicMock()
    esxi_connection.is_vm_powered_on.return_value = True

    nf = NodeFactory()
    gns3_node = nf.create_node("VPCS", "ROUTER", "R1")
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    nodes = {"R1": gns3_node, "VM1": vm}

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.list_projects.return_value = [{"project_id": "p1", "name": "Lab"}]
        client.list_nodes.return_value = [
            {"node_id": "n1", "name": "R1", "status": "started"}
        ]
        client.list_links.return_value = []

        results = orchestrator.verify_topology(nodes, "Lab", vm_name="GNS3-VM")

    assert any(ok and "R1" in d and "started" in d for ok, d in results)
    assert any(ok and "VM1" in d and "powered on" in d for ok, d in results)


@allure.title("verify_topology meldet eine nicht gefundene ESXi-VM als fehlgeschlagen")
@allure.description(
    "Überprüft, dass verify_topology einen fehlgeschlagenen Check meldet, "
    "wenn die erwartete ESXi-VM nicht gefunden wird"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_026() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = None
    esxi_connection.list_port_groups.return_value = []
    esxi_connection.get_vm.return_value = None

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    nodes = {"VM1": vm}

    with patch("src.vm_orchestrator.GNS3Client"):
        results = orchestrator.verify_topology(nodes, "Lab", vm_name="GNS3-VM")

    assert any(not ok and "VM1" in d and "not found" in d for ok, d in results)


@allure.title(
    "verify_topology erkennt eine VLAN-Kollision bei einem direkten ESXi-Link"
)
@allure.description(
    "Überprüft, dass verify_topology einen fehlgeschlagenen Check meldet, "
    "wenn die Port-Groups beider Seiten einer direkten ESXi-ESXi-"
    "Verbindung unterschiedliche VLAN-IDs tragen"
)
@allure.tag("negativ-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_027() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = None
    esxi_connection.get_vm.return_value = MagicMock()
    esxi_connection.is_vm_powered_on.return_value = True

    nf = NodeFactory()
    vm1: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm2: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM2")
    if1 = vm1.add_interface("ens160")
    if2 = vm2.add_interface("ens160")
    NodeFactory.create_edge(if1, if2)
    nodes = {"VM1": vm1, "VM2": vm2}

    esxi_connection.list_port_groups.return_value = [
        {"name": if1.esxi_vlan, "vlan_id": 2, "vswitch": "vSwitch0"},
        {"name": if2.esxi_vlan, "vlan_id": 3, "vswitch": "vSwitch0"},
    ]

    with patch("src.vm_orchestrator.GNS3Client"):
        results = orchestrator.verify_topology(nodes, "Lab", vm_name="GNS3-VM")

    assert any(not ok and "VLAN mismatch" in d for ok, d in results)


@allure.title(
    "verify_topology bestätigt eine ESXi<->GNS3-Bridge, wenn Port-Group und Cloud-Node existieren"
)
@allure.description(
    "Überprüft, dass verify_topology einen bestandenen Check meldet, wenn "
    "sowohl die erwartete ESXi-Port-Group als auch der passende Cloud-Node "
    "im GNS3-Projekt existieren"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_032() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"
    esxi_connection.get_vm.return_value = None

    nf = NodeFactory()
    router = nf.create_node("VPCS", "ROUTER", "R1")
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    router_if = router.add_interface("gi0/0")
    vm_if = vm.add_interface("ens160")
    NodeFactory.create_edge(router_if, vm_if)
    nodes = {"R1": router, "VM1": vm}

    esxi_connection.list_port_groups.return_value = [
        {"name": vm_if.esxi_vlan, "vlan_id": 2, "vswitch": "vSwitch0"}
    ]

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.list_projects.return_value = [{"project_id": "p1", "name": "Lab"}]
        client.list_nodes.return_value = [
            {"node_id": "n1", "name": "R1", "status": "started"},
            {"node_id": "c1", "name": f"cloud-{vm_if.esxi_vlan}", "status": "started"},
        ]
        client.list_links.return_value = []

        results = orchestrator.verify_topology(nodes, "Lab", vm_name="GNS3-VM")

    assert any(ok and "bridged via" in d for ok, d in results)


@allure.title("verify_topology bestätigt einen bestehenden GNS3-internen Link")
@allure.description(
    "Überprüft, dass verify_topology einen bestandenen Check meldet, wenn "
    "zwischen zwei rein GNS3-gehosteten Nodes tatsächlich ein Link mit den "
    "erwarteten Node-IDs existiert"
)
@allure.tag("positiv-test", "vm_orchestrator")
@allure.feature("vm_orchestrator")
@allure.severity(allure.severity_level.CRITICAL)
def vm_orchestrator_033() -> None:
    orchestrator, esxi_connection = _make_orchestrator()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.231"
    esxi_connection.list_port_groups.return_value = []

    nf = NodeFactory()
    r1 = nf.create_node("VPCS", "ROUTER", "R1")
    r2 = nf.create_node("VPCS", "ROUTER", "R2")
    NodeFactory.create_edge(r1.add_interface("gi0/0"), r2.add_interface("gi0/0"))
    nodes = {"R1": r1, "R2": r2}

    with patch("src.vm_orchestrator.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.list_projects.return_value = [{"project_id": "p1", "name": "Lab"}]
        client.list_nodes.return_value = [
            {"node_id": "n1", "name": "R1", "status": "started"},
            {"node_id": "n2", "name": "R2", "status": "started"},
        ]
        client.list_links.return_value = [
            {"nodes": [{"node_id": "n1"}, {"node_id": "n2"}]}
        ]

        results = orchestrator.verify_topology(nodes, "Lab", vm_name="GNS3-VM")

    assert any(ok and "R1:gi0/0 <-> R2:gi0/0: linked" in d for ok, d in results)
