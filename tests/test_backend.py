"""
Tests to validate functionality of src/backend.py
"""

__license__ = "GNU GPLv3"

import shutil
from unittest.mock import MagicMock, patch

import allure
import pytest

from src.backend import TopologyBackend
from src.settings import Settings

TEST_FILE_FOLDER = "./tests/files/"


def add_folder_path(path: str) -> str:
    return TEST_FILE_FOLDER + path


def _reset_settings() -> None:
    Settings.IS_DRY_RUN = False
    Settings.GNS3.PROJECT_NAME = None


def _make_backend() -> tuple[TopologyBackend, MagicMock]:
    with patch("src.backend.VMOrchestrator") as orchestrator_cls:
        orchestrator = orchestrator_cls.return_value
        orchestrator.gns3_vm_ip = "10.20.20.231"
        backend = TopologyBackend(
            "10.20.20.202", 443, "root", "pw", "GNS3", "gns3user", "gns3pw"
        )
    return backend, orchestrator


def _copy_topology(tmp_path) -> str:
    target = tmp_path / "topology.yaml"
    shutil.copy(add_folder_path("config_file_003.yml"), target)
    return str(target)


@allure.title("add_node schreibt die YAML-Datei und deployt inkrementell")
@allure.description(
    "Überprüft, dass add_node() den neuen Knoten in die Topology-YAML "
    "schreibt, Settings.GNS3.PROJECT_NAME passend zum Dateinamen setzt, "
    "und VMOrchestrator.deploy_graph mit incremental=True für den "
    "vollständigen (neuen) Graphen aufruft"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_000(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    node = backend.add_node(topology_file, "PC99", "PC", "VPCS")

    assert node.name == "PC99"
    orchestrator.deploy_graph.assert_called_once()
    call_args = orchestrator.deploy_graph.call_args
    deployed_graph = call_args[0][0]
    assert "PC99" in deployed_graph.nodes
    assert call_args.kwargs["incremental"] is True
    assert Settings.GNS3.PROJECT_NAME == "topology"


@allure.title("add_node wirft ValueError, wenn der Knotenname schon existiert")
@allure.description(
    "Überprüft, dass add_node() ohne jede Deploy-Aktion abbricht, wenn "
    "der angegebene Name bereits ein Knoten im aktuellen Graphen ist"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_001(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    with pytest.raises(ValueError, match="PC1"):
        backend.add_node(topology_file, "PC1", "PC", "VPCS")

    orchestrator.deploy_graph.assert_not_called()


@allure.title("add_link schreibt die neue Edge und deployt inkrementell")
@allure.description(
    "Überprüft, dass add_link() eine neue Edge in die Topology-YAML "
    "schreibt und VMOrchestrator.deploy_graph mit incremental=True aufruft"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_002(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    backend.add_link(topology_file, "PC1", "gi0/1", "PC2", "gi0/1")

    orchestrator.deploy_graph.assert_called_once()
    deployed_graph = orchestrator.deploy_graph.call_args[0][0]
    assert deployed_graph.nodes["PC1"].get_interface(deployed_graph.nodes["PC2"]) is not None


@allure.title("remove_node löscht den GNS3-Node und die ESXi-VM, dann die YAML-Zeilen")
@allure.description(
    "Überprüft, dass remove_node() zuerst den passenden live GNS3-Node "
    "sowie (für ON_ESXI-Knoten) die zugehörige VM löscht, und erst danach "
    "den Knoten und seine Edges aus der Topology-YAML entfernt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_003(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    live_vm = MagicMock()
    orchestrator.esxi_connection.get_vm.return_value = live_vm

    with (
        patch(
            "src.backend.GNS3Connection.list_all_projects",
            return_value=[{"name": "topology", "project_id": "proj-1"}],
        ),
        patch(
            "src.backend.GNS3Connection.list_project_nodes",
            return_value=[{"name": "PC4", "node_id": "n-pc4"}],
        ),
        patch("src.backend.GNS3Connection.delete_node") as mock_delete_node,
    ):
        backend.remove_node(topology_file, "PC4")

    mock_delete_node.assert_called_once_with("10.20.20.231", 80, "proj-1", "n-pc4")
    orchestrator.esxi_connection.get_vm.assert_called_once_with("PC4")
    orchestrator.esxi_connection.delete_vm.assert_called_once_with(live_vm)

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert not any("PC4" in g["names"] for g in reloaded.nodes)


@allure.title("remove_node wirft ValueError für einen unbekannten Knotennamen")
@allure.description(
    "Überprüft, dass remove_node() ohne jede Löschaktion abbricht, wenn "
    "kein Knoten mit dem angegebenen Namen im aktuellen Graphen existiert"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.NORMAL)
def backend_004(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, _orchestrator = _make_backend()

    with pytest.raises(ValueError, match="GHOST"):
        backend.remove_node(topology_file, "GHOST")


@allure.title("remove_node überspringt die Live-Löschung, wenn kein GNS3-Projekt existiert")
@allure.description(
    "Überprüft, dass remove_node() weiterhin die Topology-YAML "
    "aktualisiert, auch wenn (noch) kein passendes GNS3-Projekt live "
    "existiert - kein Fehler nur wegen fehlendem Deploy"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.NORMAL)
def backend_005(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.esxi_connection.get_vm.return_value = None

    with patch("src.backend.GNS3Connection.list_all_projects", return_value=[]):
        backend.remove_node(topology_file, "PC4")

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert not any("PC4" in g["names"] for g in reloaded.nodes)


@allure.title("remove_link löscht den passenden live Link, dann die Edge in der YAML")
@allure.description(
    "Überprüft, dass remove_link() den GNS3-Link findet, dessen beide "
    "Endpunkte genau den zwei angegebenen Knoten entsprechen, ihn live "
    "löscht, und danach die entsprechende Edge aus der Topology-YAML "
    "entfernt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_006(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    live_nodes = [
        {"name": "PC1", "node_id": "n-pc1"},
        {"name": "SW-C1", "node_id": "n-sw"},
    ]
    live_links = [
        {
            "link_id": "link-1",
            "nodes": [{"node_id": "n-pc1"}, {"node_id": "n-sw"}],
        }
    ]

    with (
        patch(
            "src.backend.GNS3Connection.list_all_projects",
            return_value=[{"name": "topology", "project_id": "proj-1"}],
        ),
        patch("src.backend.GNS3Connection.list_project_nodes", return_value=live_nodes),
        patch("src.backend.GNS3Connection.list_project_links", return_value=live_links),
        patch("src.backend.GNS3Connection.delete_link") as mock_delete_link,
    ):
        backend.remove_link(topology_file, "PC1", "SW-C1")

    mock_delete_link.assert_called_once_with("10.20.20.231", 80, "proj-1", "link-1")

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert not any({e[0], e[2]} == {"PC1", "SW-C1"} for e in reloaded.edges)


@allure.title("add_node lässt die YAML-Datei unverändert, wenn das Deployment fehlschlägt")
@allure.description(
    "Überprüft, dass add_node() den neuen Knoten NICHT in die "
    "Topology-YAML schreibt, wenn VMOrchestrator.deploy_graph "
    "fehlschlägt - verhindert, dass die Datei einen Knoten behauptet, "
    "der nie live deployt wurde"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_007(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.deploy_graph.side_effect = RuntimeError("deploy failed")

    with pytest.raises(RuntimeError, match="deploy failed"):
        backend.add_node(topology_file, "PC99", "PC", "VPCS")

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert not any("PC99" in g["names"] for g in reloaded.nodes)


@allure.title("add_link lässt die YAML-Datei unverändert, wenn das Deployment fehlschlägt")
@allure.description(
    "Überprüft, dass add_link() die neue Edge NICHT in die "
    "Topology-YAML schreibt, wenn VMOrchestrator.deploy_graph "
    "fehlschlägt - verhindert, dass die Datei eine Edge behauptet, "
    "die nie live deployt wurde"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_008(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.deploy_graph.side_effect = RuntimeError("deploy failed")

    with pytest.raises(RuntimeError, match="deploy failed"):
        backend.add_link(topology_file, "PC1", "gi0/1", "PC2", "gi0/1")

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert not any({e[0], e[2]} == {"PC1", "PC2"} for e in reloaded.edges)


@allure.title("add_node schreibt den neuen Knoten erst NACH einem erfolgreichen Deployment in die YAML-Datei")
@allure.description(
    "Überprüft, dass die reale Topology-YAML-Datei nach einem "
    "erfolgreichen add_node()-Aufruf tatsächlich den neuen Knoten "
    "enthält - bisher wurde nur der in-memory deployed_graph geprüft"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_009(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, _orchestrator = _make_backend()

    backend.add_node(topology_file, "PC99", "PC", "VPCS")

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert any("PC99" in g["names"] for g in reloaded.nodes)


@allure.title("add_link schreibt die neue Edge erst NACH einem erfolgreichen Deployment in die YAML-Datei")
@allure.description(
    "Überprüft, dass die reale Topology-YAML-Datei nach einem "
    "erfolgreichen add_link()-Aufruf tatsächlich die neue Edge enthält"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_010(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, _orchestrator = _make_backend()

    backend.add_link(topology_file, "PC1", "gi0/1", "PC2", "gi0/1")

    from src.topology_file_validation import TopologyFileValidation

    reloaded = TopologyFileValidation(topology_file)
    reloaded.validate_file()
    assert any({e[0], e[2]} == {"PC1", "PC2"} for e in reloaded.edges)
