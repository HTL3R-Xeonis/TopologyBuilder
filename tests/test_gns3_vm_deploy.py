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
    esxi_connection.set_vm_mac_address.assert_called_once_with(new_vm, "00:11:22:33:44:55")


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

    with patch("src.gns3_vm_deploy.OVAImporter") as importer_cls, patch(
        "src.gns3_vm_deploy.time.sleep"
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
