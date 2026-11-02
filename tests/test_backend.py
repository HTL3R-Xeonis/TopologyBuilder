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
    Settings.INCREMENTAL_DEPLOY = True


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
    assert (
        deployed_graph.nodes["PC1"].get_interface(deployed_graph.nodes["PC2"])
        is not None
    )


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


@allure.title(
    "remove_node überspringt die Live-Löschung, wenn kein GNS3-Projekt existiert"
)
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
    backend, _orchestrator = _make_backend()

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


@allure.title(
    "add_node lässt die YAML-Datei unverändert, wenn das Deployment fehlschlägt"
)
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


@allure.title(
    "add_link lässt die YAML-Datei unverändert, wenn das Deployment fehlschlägt"
)
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


@allure.title(
    "add_node schreibt den neuen Knoten erst NACH einem erfolgreichen Deployment in die YAML-Datei"
)
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


@allure.title(
    "add_link schreibt die neue Edge erst NACH einem erfolgreichen Deployment in die YAML-Datei"
)
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


_NEW_TOPOLOGY_YAML = """\
nodes:
  - image: VPCS
    role: PC
    names:
      - BUNDLE-PC1
      - BUNDLE-PC2
edges:
  - [ BUNDLE-PC1, Ethernet0, BUNDLE-PC2, Ethernet0 ]
"""


@allure.title(
    "deploy_topology deployt inkrementell und schreibt die YAML-Datei erst danach"
)
@allure.description(
    "Überprüft, dass deploy_topology() den übergebenen YAML-Text live "
    "deployt (incremental=True) und die reale Topology-YAML-Datei "
    "danach vollständig durch diesen Text ersetzt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_011(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    graph = backend.deploy_topology(topology_file, _NEW_TOPOLOGY_YAML)

    assert "BUNDLE-PC1" in graph.nodes
    orchestrator.deploy_graph.assert_called_once()
    call_args = orchestrator.deploy_graph.call_args
    assert "BUNDLE-PC1" in call_args[0][0].nodes
    assert call_args.kwargs["incremental"] is True

    with open(topology_file) as file:
        assert file.read() == _NEW_TOPOLOGY_YAML


@allure.title(
    "deploy_topology lässt die YAML-Datei unverändert, wenn das Deployment fehlschlägt"
)
@allure.description(
    "Überprüft, dass deploy_topology() die reale Topology-YAML-Datei "
    "NICHT überschreibt, wenn VMOrchestrator.deploy_graph fehlschlägt"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_012(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.deploy_graph.side_effect = RuntimeError("deploy failed")

    with open(topology_file) as file:
        original_content = file.read()

    with pytest.raises(RuntimeError, match="deploy failed"):
        backend.deploy_topology(topology_file, _NEW_TOPOLOGY_YAML)

    with open(topology_file) as file:
        assert file.read() == original_content


@allure.title("deploy_topology passt incremental an Settings.INCREMENTAL_DEPLOY an")
@allure.description(
    "Überprüft, dass deploy_topology() bei Settings.INCREMENTAL_DEPLOY "
    "= False ein incremental=False an VMOrchestrator.deploy_graph "
    "übergibt, statt fest incremental=True zu verwenden"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_013(tmp_path) -> None:
    _reset_settings()
    Settings.INCREMENTAL_DEPLOY = False
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()

    try:
        backend.deploy_topology(topology_file, _NEW_TOPOLOGY_YAML)

        call_args = orchestrator.deploy_graph.call_args
        assert call_args.kwargs["incremental"] is False
    finally:
        _reset_settings()


@allure.title("verify ohne fix ruft nur verify_graph auf")
@allure.description(
    "Überprüft, dass verify(fix=False) VMOrchestrator.verify_graph mit dem "
    "aus der Datei gebauten Graphen und dem Projektnamen aufruft, "
    "repair_graph nicht anfasst und eine leere Aktionsliste zurückgibt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_014(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.verify_graph.return_value = [(True, "ok")]
    orchestrator.verify_vlan_subinterfaces.return_value = (True, "subinterfaces ok")
    orchestrator.verify_persistent_vlan_config.return_value = (True, "boot service ok")
    orchestrator.install_persistent_vlan_config.return_value = []

    actions, results = backend.verify(topology_file)

    assert actions == []
    assert results == [
        (True, "ok"),
        (True, "subinterfaces ok"),
        (True, "boot service ok"),
    ]
    orchestrator.repair_graph.assert_not_called()
    orchestrator.repair_vlan_subinterfaces.assert_not_called()
    assert orchestrator.verify_graph.call_args.args[1] == "topology"


@allure.title("verify mit fix repariert zuerst und prüft danach")
@allure.description(
    "Überprüft, dass verify(fix=True) erst repair_graph und danach "
    "verify_graph aufruft und beide Ergebnisse zurückgibt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_015(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    calls = []
    orchestrator.repair_graph.side_effect = lambda *a: (
        calls.append("repair") or ["Started GNS3 node 'R1'"]
    )
    orchestrator.repair_vlan_subinterfaces.side_effect = lambda *a: (
        calls.append("subinterfaces") or ["Re-created VLAN subinterface eth1.7"]
    )
    orchestrator.verify_graph.side_effect = lambda *a: (
        calls.append("verify") or [(True, "ok")]
    )
    orchestrator.verify_vlan_subinterfaces.return_value = (True, "subinterfaces ok")
    orchestrator.verify_persistent_vlan_config.return_value = (True, "boot service ok")
    orchestrator.install_persistent_vlan_config.return_value = []

    actions, results = backend.verify(
        topology_file, fix=True, fix_vlan_subinterfaces=True
    )

    assert calls == ["repair", "subinterfaces", "verify"]
    assert actions == [
        "Started GNS3 node 'R1'",
        "Re-created VLAN subinterface eth1.7",
    ]
    assert results == [
        (True, "ok"),
        (True, "subinterfaces ok"),
        (True, "boot service ok"),
    ]


@allure.title("find_orphans und delete_orphans reichen Graph bzw. Projektnamen durch")
@allure.description(
    "Überprüft, dass find_orphans den Graphen und Projektnamen an "
    "VMOrchestrator.find_orphans übergibt und dessen Liste zurückgibt, und "
    "delete_orphans die Liste samt Projektnamen an "
    "VMOrchestrator.delete_orphans weiterreicht"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_016(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orphan = {"type": "gns3_node", "name": "LEFTOVER", "reason": "..."}
    orchestrator.find_orphans.return_value = [orphan]

    assert backend.find_orphans(topology_file) == [orphan]
    assert orchestrator.find_orphans.call_args.args[1] == "topology"

    backend.delete_orphans(topology_file, [orphan])
    orchestrator.delete_orphans.assert_called_once_with([orphan], "topology")


@allure.title("Ein Fehler beim Reparieren der Subinterfaces bricht verify nicht ab")
@allure.description(
    "Überprüft, dass verify(fix=True) weiterläuft und weiterhin prüft, wenn "
    "das Wiederanlegen der VLAN-Subinterfaces (z. B. SSH) fehlschlägt"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.NORMAL)
def backend_017(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.repair_graph.return_value = []
    orchestrator.repair_vlan_subinterfaces.side_effect = RuntimeError("ssh down")
    orchestrator.verify_graph.return_value = []
    orchestrator.verify_vlan_subinterfaces.return_value = (False, "missing")
    orchestrator.verify_persistent_vlan_config.return_value = (True, "boot service ok")
    orchestrator.install_persistent_vlan_config.return_value = []

    actions, results = backend.verify(
        topology_file, fix=True, fix_vlan_subinterfaces=True
    )

    assert actions == []
    assert results == [(False, "missing"), (True, "boot service ok")]


@allure.title("verify(fix=True) legt die VLAN-Subinterfaces nicht von selbst an")
@allure.description(
    "Überprüft, dass verify(fix=True) die Subinterfaces nicht repariert (diese "
    "Reparatur hat im Lab zweimal den ESXi-Host vom Netz getrennt) und dass nur "
    "fix_vlan_subinterfaces=True sie auslöst"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_018(tmp_path) -> None:
    _reset_settings()
    topology_file = _copy_topology(tmp_path)
    backend, orchestrator = _make_backend()
    orchestrator.repair_graph.return_value = []
    orchestrator.verify_graph.return_value = []
    orchestrator.verify_vlan_subinterfaces.return_value = (False, "9 of 9 missing")
    orchestrator.verify_persistent_vlan_config.return_value = (True, "boot service ok")
    orchestrator.install_persistent_vlan_config.return_value = []

    backend.verify(topology_file, fix=True)

    orchestrator.repair_vlan_subinterfaces.assert_not_called()


def _parallel_live_setup():
    live_nodes = [
        {
            "name": "R1",
            "node_id": "n-r1",
            "ports": [
                {"name": "Gi0/0", "adapter_number": 0, "port_number": 0},
                {"name": "Gi0/1", "adapter_number": 1, "port_number": 0},
            ],
        },
        {
            "name": "R2",
            "node_id": "n-r2",
            "ports": [
                {"name": "Gi0/0", "adapter_number": 0, "port_number": 0},
                {"name": "Gi0/1", "adapter_number": 1, "port_number": 0},
            ],
        },
    ]
    live_links = [
        {
            "link_id": "link-a",
            "nodes": [
                {"node_id": "n-r1", "adapter_number": 0, "port_number": 0},
                {"node_id": "n-r2", "adapter_number": 0, "port_number": 0},
            ],
        },
        {
            "link_id": "link-b",
            "nodes": [
                {"node_id": "n-r1", "adapter_number": 1, "port_number": 0},
                {"node_id": "n-r2", "adapter_number": 1, "port_number": 0},
            ],
        },
    ]
    return live_nodes, live_links


def _remove_parallel(tmp_path, live_nodes, live_links, **interfaces):
    topology_file = _copy_topology(tmp_path)
    backend, _ = _make_backend()
    with (
        patch(
            "src.backend.GNS3Connection.list_all_projects",
            return_value=[{"name": "topology", "project_id": "proj-1"}],
        ),
        patch("src.backend.GNS3Connection.list_project_nodes", return_value=live_nodes),
        patch("src.backend.GNS3Connection.list_project_links", return_value=live_links),
        patch("src.backend.GNS3Connection.delete_link") as mock_delete_link,
    ):
        backend.remove_link(topology_file, "R1", "R2", **interfaces)
    return mock_delete_link


@allure.title(
    "remove_link löscht von mehreren parallelen Links nur den mit den angegebenen Interfaces"
)
@allure.description(
    "Überprüft, dass remove_link() mit if1/if2 aus zwei live Links zwischen denselben "
    "Knoten genau den mit den passenden GNS3-Portnamen löscht, auch bei vertauschten "
    "Endpunkten, und bei mehrdeutigen Angaben nichts rät"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_019(tmp_path) -> None:
    _reset_settings()
    nodes, links = _parallel_live_setup()

    deleted = _remove_parallel(tmp_path, nodes, links, if1="Gi0/1", if2="Gi0/1")
    deleted.assert_called_once_with("10.20.20.231", 80, "proj-1", "link-b")

    links[0]["nodes"].reverse()  # endpoint order in GNS3's link must not matter
    deleted = _remove_parallel(tmp_path, nodes, links, if1="Gi0/0", if2="Gi0/0")
    deleted.assert_called_once_with("10.20.20.231", 80, "proj-1", "link-a")

    with pytest.raises(ValueError, match="cannot tell which one|no live link"):
        _remove_parallel(tmp_path, nodes, links, if1="Gi9/9", if2="Gi9/9")


@allure.title(
    "remove_link nimmt bei nur einem Link immer diesen, auch bei abweichendem Interface-Namen"
)
@allure.description(
    "Überprüft, dass bei genau einem Link zwischen zwei Knoten dieser gelöscht wird, auch wenn "
    "der Interface-Name der YAML nicht zum Portnamen des Cloud-Knotens passt (VM-Interface "
    "ens160 gegen Port eth0), und dass ohne Interface-Angaben wie früher der erste Link gilt"
)
@allure.tag("positiv-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_020(tmp_path) -> None:
    _reset_settings()
    nodes, links = _parallel_live_setup()
    nodes[1]["node_type"] = (
        "cloud"  # the GNS3 side of an ESXi VM: its port is named after the host NIC
    )
    nodes[1]["ports"] = [{"name": "eth0", "adapter_number": 0, "port_number": 0}]

    deleted = _remove_parallel(tmp_path, nodes, links[:1], if1="Gi0/0", if2="ens160")
    deleted.assert_called_once_with("10.20.20.231", 80, "proj-1", "link-a")

    deleted = _remove_parallel(
        tmp_path, nodes, links
    )  # no interfaces: first link, like before
    deleted.assert_called_once_with("10.20.20.231", 80, "proj-1", "link-a")


@allure.title(
    "remove_link löscht keinen anderen Link, wenn der gemeinte live gar nicht existiert"
)
@allure.description(
    "Überprüft, dass remove_link() bei genau einem live Link zwischen zwei GNS3-Nodes nichts live löscht, "
    "wenn die angegebenen Interfaces nicht zu seinen Ports passen (die YAML führt einen zweiten Link, den "
    "GNS3 nie bekommen hat), die Kante aber trotzdem aus der YAML entfernt wird"
)
@allure.tag("negativ-test", "backend")
@allure.feature("backend")
@allure.severity(allure.severity_level.CRITICAL)
def backend_021(tmp_path) -> None:
    _reset_settings()
    nodes, links = _parallel_live_setup()

    deleted = _remove_parallel(tmp_path, nodes, links[:1], if1="Gi0/1", if2="Gi0/1")

    deleted.assert_not_called()
