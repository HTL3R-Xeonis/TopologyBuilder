"""
Tests to validate functionality of src/connections/ova_importer.py
"""

__license__ = "GNU GPLv3"

import io
import tarfile
from unittest.mock import MagicMock, patch

import allure
import pytest

from src.connections.ova_importer import OVAImporter, vim


def _make_ova_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        ovf = b"<Envelope/>"
        info = tarfile.TarInfo(name="vm.ovf")
        info.size = len(ovf)
        tf.addfile(info, io.BytesIO(ovf))
    return buf.getvalue()


def _make_importer(declared_network_names: list[str]) -> tuple[OVAImporter, MagicMock]:
    importer = OVAImporter.__new__(OVAImporter)
    esxi_connection = MagicMock()
    esxi_connection.ip = "10.20.20.202"
    esxi_connection.find_network.return_value = vim.Network("network-1")
    importer.esxi_connection = esxi_connection

    host_system = MagicMock()
    esxi_connection.get_host_system.return_value = host_system
    esxi_connection.content.rootFolder.childEntity = [MagicMock()]
    esxi_connection.find_datastore.return_value = MagicMock()

    declared_networks = []
    for name in declared_network_names:
        network = MagicMock()
        network.name = name
        declared_networks.append(network)
    esxi_connection.content.ovfManager.ParseDescriptor.return_value = MagicMock(
        network=declared_networks
    )

    import_spec_result = MagicMock()
    import_spec_result.error = []
    import_spec_result.warning = []
    import_spec_result.fileItem = []
    esxi_connection.content.ovfManager.CreateImportSpec.return_value = (
        import_spec_result
    )

    lease = MagicMock()
    lease.state = "ready"
    vm = MagicMock()
    lease.info.entity = vm
    host_system.parent.resourcePool.ImportVApp.return_value = lease

    return importer, esxi_connection


@allure.title("OVA mit weniger deklarierten Netzwerken als angegeben")
@allure.description(
    "Überprüft, dass import_ova bei einer OVF mit weniger deklarierten "
    "Netzwerken als übergebenen Port-Group-Namen nur die deklarierten "
    "Netzwerke beim Import mappt und die restlichen Namen danach als neue "
    "Netzwerkadapter hinzufügt (z.B. eine Single-NIC-OVA, die trotzdem eine "
    "zweite, Trunk-NIC braucht)"
)
@allure.tag("positiv-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.CRITICAL)
def ova_importer_000() -> None:
    importer, esxi_connection = _make_importer(["pvn"])
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.connections.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with patch.object(importer, "_upload_disks"):
            vm = importer.import_ova(
                "/fake/path.ova", "GNS3-VM", "datastore1", ["PG-MGMT", "PG-GNS3-TRUNK"]
            )

    create_spec_call = esxi_connection.content.ovfManager.CreateImportSpec.call_args
    mapping = create_spec_call.args[3].networkMapping
    assert len(mapping) == 1
    assert mapping[0].name == "pvn"
    esxi_connection.add_vm_network_adapters.assert_called_once_with(
        vm, ["PG-GNS3-TRUNK"]
    )


@allure.title(
    "OVA mit mehr deklarierten Netzwerken als angegeben entfernt die Extra-NICs"
)
@allure.description(
    "Überprüft, dass import_ova bei einer OVF mit mehr deklarierten "
    "Netzwerken als übergebenen Port-Group-Namen (z.B. eine Appliance-OVA "
    "mit eingebauter zweiter WAN/LAN-NIC, die die Topologie nie verkabelt "
    "hat) den letzten übergebenen Namen nur nutzt, damit der Import selbst "
    "gelingt, und danach die dadurch entstandenen Extra-NIC(s) wieder "
    "entfernt - die VM soll am Ende genau so viele Adapter haben wie die "
    "Topologie vorgibt, keine redundante NIC an einer bereits genutzten "
    "Port-Group"
)
@allure.tag("positiv-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.CRITICAL)
def ova_importer_001() -> None:
    importer, esxi_connection = _make_importer(["net1", "net2"])
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.connections.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with patch.object(importer, "_upload_disks"):
            vm = importer.import_ova(
                "/fake/path.ova", "GNS3-VM", "datastore1", ["PG-MGMT"]
            )

    create_spec_call = esxi_connection.content.ovfManager.CreateImportSpec.call_args
    mapping = create_spec_call.args[3].networkMapping
    assert len(mapping) == 2
    assert mapping[0].name == "net1"
    assert mapping[1].name == "net2"
    esxi_connection.find_network.assert_any_call("PG-MGMT")
    esxi_connection.remove_vm_network_adapters.assert_called_once_with(vm, 1)


@allure.title("OVA mit deklarierten Netzwerken aber ganz ohne Interfaces wirft Fehler")
@allure.description(
    "Überprüft, dass import_ova einen ValueError wirft, wenn die OVF "
    "mindestens ein Netzwerk deklariert, aber gar keine Port-Group-Namen "
    "übergeben wurden - dann gibt es keinen Namen, der wiederverwendet "
    "werden könnte"
)
@allure.tag("negativ-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.CRITICAL)
def ova_importer_002() -> None:
    importer, esxi_connection = _make_importer(["net1"])
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.connections.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with pytest.raises(ValueError, match=r"OVF declares 1 network\(s\)"):
            importer.import_ova("/fake/path.ova", "GNS3-VM", "datastore1", [])


@allure.title(
    "import_ova wirft einen Fehler, wenn die Erstellung des Import-Specs fehlschlägt"
)
@allure.description(
    "Überprüft, dass import_ova einen RuntimeError wirft, wenn "
    "CreateImportSpec Fehler in import_spec_result.error zurückgibt"
)
@allure.tag("negativ-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.CRITICAL)
def ova_importer_003() -> None:
    importer, esxi_connection = _make_importer([])
    esxi_connection.content.ovfManager.CreateImportSpec.return_value.error = [
        MagicMock(msg="something bad")
    ]
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.connections.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with pytest.raises(RuntimeError, match=r"Failed to create import spec"):
            importer.import_ova("/fake/path.ova", "GNS3-VM", "datastore1", [])
