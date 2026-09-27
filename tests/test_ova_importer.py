"""
Tests to validate functionality of src/ova_importer.py
"""

__license__ = "GNU GPLv3"

import io
import tarfile
from unittest.mock import MagicMock, patch

import allure
import pytest

from src.ova_importer import OVAImporter, vim


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
    network = MagicMock()
    network.__class__ = vim.Network
    esxi_connection.find_network.return_value = network
    importer.esxi_connection = esxi_connection

    host_system = MagicMock()
    esxi_connection.get_host_system.return_value = host_system
    esxi_connection.content.rootFolder.childEntity = [MagicMock()]
    esxi_connection.find_datastore.return_value = MagicMock()

    declared_networks = []
    for name in declared_network_names:
        declared_network = MagicMock()
        declared_network.name = name
        declared_networks.append(declared_network)
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
    lease.state = vim.HttpNfcLease.State.ready
    vm = MagicMock()
    lease.info.entity = vm
    host_system.parent.resourcePool.ImportVApp.return_value = lease

    return importer, esxi_connection


@allure.title("import_ova mit weniger deklarierten Netzwerken als übergebenen Namen")
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

    with (
        patch(
            "src.ova_importer.tarfile.open",
            return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
        ),
        patch.object(importer, "_upload_disks"),
    ):
        vm = importer.import_ova(
            "/fake/path.ova", "GNS3-VM", "datastore1", ["PG-MGMT", "PG_GNS3_TRUNK"]
        )

    create_spec_call = esxi_connection.content.ovfManager.CreateImportSpec.call_args
    mapping = create_spec_call.args[3].networkMapping
    assert len(mapping) == 1
    assert mapping[0].name == "pvn"
    esxi_connection.add_vm_network_adapters.assert_called_once_with(
        vm, ["PG_GNS3_TRUNK"]
    )


@allure.title(
    "import_ova mit mehr deklarierten Netzwerken als übergebenen Namen wirft Fehler"
)
@allure.description(
    "Überprüft, dass import_ova einen ValueError wirft, wenn die OVF mehr "
    "Netzwerke deklariert als ESXi-Port-Group-Namen übergeben wurden, da "
    "dann nicht eindeutig ist, welches Netzwerk unzugeordnet bleiben soll"
)
@allure.tag("negativ-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.CRITICAL)
def ova_importer_001() -> None:
    importer, _ = _make_importer(["net1", "net2"])
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with pytest.raises(ValueError, match=r"OVF declares 2 network\(s\)"):
            importer.import_ova("/fake/path.ova", "GNS3-VM", "datastore1", ["PG-MGMT"])


@allure.title("import_ova wirft einen Fehler, wenn CreateImportSpec fehlschlägt")
@allure.description(
    "Überprüft, dass import_ova einen RuntimeError wirft, wenn "
    "CreateImportSpec Fehler im Ergebnis zurückgibt"
)
@allure.tag("negativ-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.CRITICAL)
def ova_importer_002() -> None:
    importer, esxi_connection = _make_importer([])
    error = MagicMock()
    error.msg = "invalid disk format"
    esxi_connection.content.ovfManager.CreateImportSpec.return_value = MagicMock(
        error=[error]
    )
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with pytest.raises(RuntimeError, match="Failed to create import spec"):
            importer.import_ova("/fake/path.ova", "GNS3-VM", "datastore1", [])


@allure.title("import_ova wirft einen Fehler, wenn der Lease nicht bereit wird")
@allure.description(
    "Überprüft, dass import_ova einen RuntimeError wirft, wenn der "
    "HttpNfcLease nie den Zustand 'ready' erreicht"
)
@allure.tag("negativ-test", "ova_importer")
@allure.feature("ova_importer")
@allure.severity(allure.severity_level.NORMAL)
def ova_importer_003() -> None:
    importer, esxi_connection = _make_importer([])
    lease = MagicMock()
    lease.state = vim.HttpNfcLease.State.error
    esxi_connection.content.rootFolder.childEntity[0].vmFolder = MagicMock()
    host_system = esxi_connection.get_host_system.return_value
    host_system.parent.resourcePool.ImportVApp.return_value = lease
    ova_bytes = _make_ova_bytes()

    with patch(
        "src.ova_importer.tarfile.open",
        return_value=tarfile.open(fileobj=io.BytesIO(ova_bytes), mode="r"),
    ):
        with pytest.raises(RuntimeError, match="HTTP NFC lease failed to become ready"):
            importer.import_ova("/fake/path.ova", "GNS3-VM", "datastore1", [])
