"""
Tests to validate functionality of src/gns3_vm_deploy.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest

from src.gns3_vm_deploy import deploy_fresh_gns3_vm


@allure.title("deploy_fresh_gns3_vm importiert direkt, wenn keine VM existiert")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm bei einer noch nicht "
    "existierenden GNS3-VM direkt die OVA importiert, ohne eine alte VM "
    "auszuschalten/umzubenennen oder eine MAC-Adresse zu übernehmen"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_000() -> None:
    esxi_connection = MagicMock()
    esxi_connection.get_vm.return_value = None
    new_vm = MagicMock()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = new_vm

        ip = deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
        )

    assert ip == "10.20.20.233"
    esxi_connection.power_off_vm.assert_not_called()
    esxi_connection.rename_vm.assert_not_called()
    esxi_connection.set_vm_mac_address.assert_not_called()
    esxi_connection.power_on_vm.assert_called_once_with(new_vm)
    importer_cls.return_value.import_ova.assert_called_once_with(
        "/mnt/nfs/gns3.ova", "GNS-VM-1", "datastore1", ["PG-MGMT", "PG_GNS3_TRUNK"]
    )


@allure.title("deploy_fresh_gns3_vm sichert eine bestehende VM statt sie zu löschen")
@allure.description(
    "Überprüft, dass eine bereits existierende gleichnamige VM zuerst "
    "ausgeschaltet und mit einem zeitgestempelten Backup-Namen umbenannt "
    "wird (nicht gelöscht), bevor die neue VM importiert wird, und dass "
    "die alte MAC-Adresse auf die neue VM übertragen wird"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_001() -> None:
    esxi_connection = MagicMock()
    old_vm = MagicMock()
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:11:22:33:44:55"
    new_vm = MagicMock()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = new_vm

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
        )

    esxi_connection.power_off_vm.assert_called_once_with(old_vm)
    esxi_connection.rename_vm.assert_called_once()
    rename_args = esxi_connection.rename_vm.call_args.args
    assert rename_args[0] is old_vm
    assert rename_args[1].startswith("GNS-VM-1-backup-")
    esxi_connection.delete_vm.assert_not_called()
    esxi_connection.set_vm_mac_address.assert_called_once_with(
        new_vm, "00:11:22:33:44:55"
    )


@allure.title("deploy_fresh_gns3_vm meldet Fortschritts-Stages über on_stage")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm bei jedem größeren Schritt den "
    "optionalen on_stage-Callback mit einem kurzen Stage-Namen aufruft, "
    "in der erwarteten Reihenfolge"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_deploy_002() -> None:
    esxi_connection = MagicMock()
    old_vm = MagicMock()
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:11:22:33:44:55"
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"
    stages = []

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = MagicMock()

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
            on_stage=stages.append,
        )

    assert stages == [
        "ensuring trunk network exists",
        "powering off existing VM",
        "importing OVA",
        "powering on",
        "waiting for an IP address",
    ]


@allure.title("deploy_fresh_gns3_vm wirft TimeoutError, wenn keine IP gemeldet wird")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm einen TimeoutError wirft, wenn "
    "die neu importierte VM innerhalb des Timeouts keine IP-Adresse "
    "meldet"
)
@allure.tag("negativ-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_003() -> None:
    esxi_connection = MagicMock()
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_vm_ip_address.return_value = None

    with (
        patch("src.gns3_vm_deploy.OVAImporter") as importer_cls,
        patch("src.gns3_vm_deploy.time.sleep"),
    ):
        importer_cls.return_value.import_ova.return_value = MagicMock()

        with pytest.raises(TimeoutError, match="did not report an IP address"):
            deploy_fresh_gns3_vm(
                esxi_connection,
                "GNS-VM-1",
                "/mnt/nfs/gns3.ova",
                "datastore1",
                "PG-MGMT",
                "PG_GNS3_TRUNK",
                ip_wait_timeout_seconds=0,
            )


@allure.title(
    "deploy_fresh_gns3_vm löscht die alte VM erst, nachdem die neue eine IP meldet"
)
@allure.description(
    "Überprüft, dass delete_old_vm=True die alte (umbenannte) VM erst "
    "dann permanent löscht, nachdem die neue VM erfolgreich eine IP-"
    "Adresse gemeldet hat (siehe gns3_vm_deploy_001 für den Standardfall "
    "delete_old_vm=False, wo delete_vm gar nicht aufgerufen wird)"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_004() -> None:
    esxi_connection = MagicMock()
    old_vm = MagicMock()
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:11:22:33:44:55"
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = MagicMock()

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
            delete_old_vm=True,
        )

    esxi_connection.delete_vm.assert_called_once_with(old_vm)


@allure.title(
    "deploy_fresh_gns3_vm löscht die alte VM nicht, wenn die neue keine IP meldet"
)
@allure.description(
    "Überprüft, dass delete_old_vm=True die alte VM NICHT löscht, wenn "
    "die neu importierte VM innerhalb des Timeouts keine IP meldet - der "
    "TimeoutError wird trotzdem geworfen, und die alte VM bleibt als "
    "Backup erhalten, damit ein fehlgeschlagenes Deployment nicht auch "
    "noch die funktionierende alte VM kostet"
)
@allure.tag("negativ-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_005() -> None:
    esxi_connection = MagicMock()
    old_vm = MagicMock()
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:11:22:33:44:55"
    esxi_connection.get_vm_ip_address.return_value = None

    with (
        patch("src.gns3_vm_deploy.OVAImporter") as importer_cls,
        patch("src.gns3_vm_deploy.time.sleep"),
    ):
        importer_cls.return_value.import_ova.return_value = MagicMock()

        with pytest.raises(TimeoutError):
            deploy_fresh_gns3_vm(
                esxi_connection,
                "GNS-VM-1",
                "/mnt/nfs/gns3.ova",
                "datastore1",
                "PG-MGMT",
                "PG_GNS3_TRUNK",
                ip_wait_timeout_seconds=0,
                delete_old_vm=True,
            )

    esxi_connection.delete_vm.assert_not_called()


@allure.title("deploy_fresh_gns3_vm stellt sicher, dass die Trunk-Port-Group existiert")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm vor dem Import ensure_virtual_"
    "switch_exists und ensure_trunk_port_group_exists aufruft - auf einem "
    "frisch aufgesetzten ESXi-Host, auf dem noch keine Topologie deployt "
    "wurde, existiert das Trunk-Netzwerk sonst noch gar nicht, und "
    "OVAImporter.import_ova würde mit einem reinen ValueError aus "
    "find_network fehlschlagen statt es selbst anzulegen"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_006() -> None:
    esxi_connection = MagicMock()
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = MagicMock()

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
        )

    esxi_connection.ensure_virtual_switch_exists.assert_called_once()
    esxi_connection.ensure_trunk_port_group_exists.assert_called_once()


@allure.title(
    "deploy_fresh_gns3_vm weist eine MAC aus mac_range zu, wenn keine alte VM existiert"
)
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm ohne existierende alte VM eine "
    "MAC-Adresse innerhalb des übergebenen mac_range auswählt und sie "
    "der neuen VM zuweist"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_007() -> None:
    esxi_connection = MagicMock()
    esxi_connection.get_vm.return_value = None
    esxi_connection.get_all_vms.return_value = []
    new_vm = MagicMock()
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = new_vm

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
            mac_range=("00:50:56:00:10:00", "00:50:56:00:10:ff"),
        )

    esxi_connection.set_vm_mac_address.assert_called_once()
    args = esxi_connection.set_vm_mac_address.call_args.args
    assert args[0] is new_vm
    assert args[1].startswith("00:50:56:00:10:")


@allure.title(
    "deploy_fresh_gns3_vm behält die alte MAC, wenn sie schon im mac_range liegt"
)
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm die geerbte MAC der alten VM "
    "unverändert übernimmt, statt eine neue zu würfeln, wenn diese MAC "
    "bereits innerhalb des konfigurierten mac_range liegt - erhält so "
    "dieselbe DHCP-vergebene IP über ein Redeploy hinweg"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_008() -> None:
    esxi_connection = MagicMock()
    old_vm = MagicMock()
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:50:56:00:10:42"
    esxi_connection.get_all_vms.return_value = []
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = MagicMock()

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
            mac_range=("00:50:56:00:10:00", "00:50:56:00:10:ff"),
        )

    esxi_connection.set_vm_mac_address.assert_called_once()
    args = esxi_connection.set_vm_mac_address.call_args.args
    assert args[1] == "00:50:56:00:10:42"


@allure.title(
    "deploy_fresh_gns3_vm würfelt eine neue MAC, wenn die alte außerhalb von mac_range liegt"
)
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm eine frische MAC aus mac_range "
    "wählt, statt die geerbte MAC der alten VM zu übernehmen, wenn diese "
    "außerhalb des konfigurierten Bereichs liegt"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_009() -> None:
    esxi_connection = MagicMock()
    old_vm = MagicMock()
    esxi_connection.get_vm.return_value = old_vm
    esxi_connection.get_vm_mac_address.return_value = "00:11:22:33:44:55"
    esxi_connection.get_all_vms.return_value = []
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = MagicMock()

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
            mac_range=("00:50:56:00:10:00", "00:50:56:00:10:ff"),
        )

    esxi_connection.set_vm_mac_address.assert_called_once()
    args = esxi_connection.set_vm_mac_address.call_args.args
    assert args[1] != "00:11:22:33:44:55"
    assert args[1].startswith("00:50:56:00:10:")


@allure.title("deploy_fresh_gns3_vm vermeidet MAC-Adressen anderer VMs auf dem Host")
@allure.description(
    "Überprüft, dass deploy_fresh_gns3_vm die MAC-Adressen aller "
    "anderen VMs auf dem Host abfragt und beim Würfeln aus mac_range "
    "ausschließt, statt versehentlich eine bereits verwendete MAC "
    "erneut zu vergeben"
)
@allure.tag("positiv-test", "gns3_vm_deploy")
@allure.feature("gns3_vm_deploy")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_deploy_010() -> None:
    esxi_connection = MagicMock()
    esxi_connection.get_vm.return_value = None
    other_vm = MagicMock()
    esxi_connection.get_all_vms.return_value = [other_vm]
    # Stubbed to always return this MAC regardless of which VM is
    # passed in, simplest way to simulate "the only other VM on the
    # host already has the range's first address" without needing a
    # second distinct mock identity.
    esxi_connection.get_vm_mac_address.return_value = "00:50:56:00:10:00"
    esxi_connection.get_vm_ip_address.return_value = "10.20.20.233"

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls:
        importer_cls.return_value.import_ova.return_value = MagicMock()

        deploy_fresh_gns3_vm(
            esxi_connection,
            "GNS-VM-1",
            "/mnt/nfs/gns3.ova",
            "datastore1",
            "PG-MGMT",
            "PG_GNS3_TRUNK",
            # A two-address range whose first address is already "used"
            # by the other VM - if the exclusion is wired up, the new
            # VM must always get the second address instead.
            mac_range=("00:50:56:00:10:00", "00:50:56:00:10:01"),
        )

    esxi_connection.get_all_vms.assert_called_once()
    esxi_connection.set_vm_mac_address.assert_called_once()
    args = esxi_connection.set_vm_mac_address.call_args.args
    assert args[1] == "00:50:56:00:10:01"
