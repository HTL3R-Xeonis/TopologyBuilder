"""
Tests to validate functionality of src/connections/gns3_connection.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest

from src.connections.gns3_connection import GNS3Connection
from src.settings import Settings


def _reset_settings() -> None:
    Settings.ONLY_ON_GNS3 = False
    Settings.ONLY_ON_ESXI = False
    Settings.IS_DRY_RUN = False


@allure.title("_init_project löscht und erstellt das Projekt im Normalbetrieb neu")
@allure.description(
    "Überprüft, dass _init_project ein bestehendes Projekt löscht und neu "
    "erstellt, wenn Settings.IS_DRY_RUN nicht gesetzt ist"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_000() -> None:
    _reset_settings()
    with (
        patch.object(
            GNS3Connection,
            "get",
            return_value=[{"name": "lab", "project_id": "old-id"}],
        ),
        patch.object(GNS3Connection, "delete") as mock_delete,
        patch.object(
            GNS3Connection, "post", return_value={"name": "lab", "project_id": "new-id"}
        ) as mock_post,
    ):
        conn = GNS3Connection("10.20.20.231", 80, "lab")

    mock_delete.assert_called_once_with(f"{conn.url}/v2/projects/old-id")
    mock_post.assert_called_once()
    assert conn.project == {"name": "lab", "project_id": "new-id"}


@allure.title(
    "_init_project lässt ein bestehendes Projekt im Dry-Run-Modus unangetastet"
)
@allure.description(
    "Überprüft, dass _init_project im Dry-Run-Modus weder delete noch post "
    "aufruft, sondern das bestehende Projekt read-only zurückgibt"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_001() -> None:
    _reset_settings()
    Settings.IS_DRY_RUN = True
    try:
        with (
            patch.object(
                GNS3Connection,
                "get",
                return_value=[{"name": "lab", "project_id": "old-id"}],
            ),
            patch.object(GNS3Connection, "delete") as mock_delete,
            patch.object(GNS3Connection, "post") as mock_post,
        ):
            conn = GNS3Connection("10.20.20.231", 80, "lab")
    finally:
        _reset_settings()

    mock_delete.assert_not_called()
    mock_post.assert_not_called()
    assert conn.project == {"name": "lab", "project_id": "old-id"}


@allure.title(
    "_init_project erstellt nichts im Dry-Run-Modus, wenn kein Projekt existiert"
)
@allure.description(
    "Überprüft, dass _init_project im Dry-Run-Modus None zurückgibt, statt "
    "ein neues Projekt anzulegen, wenn noch keines mit dem Namen existiert"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.NORMAL)
def gns3_connection_002() -> None:
    _reset_settings()
    Settings.IS_DRY_RUN = True
    try:
        with (
            patch.object(GNS3Connection, "get", return_value=[]),
            patch.object(GNS3Connection, "post") as mock_post,
        ):
            conn = GNS3Connection("10.20.20.231", 80, "lab")
    finally:
        _reset_settings()

    mock_post.assert_not_called()
    assert conn.project is None


@allure.title("start_all_nodes startet jeden Node im Projekt")
@allure.description(
    "Überprüft, dass start_all_nodes für jeden Node im Projekt einen "
    "POST-Request an dessen /start Endpunkt schickt"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_003() -> None:
    _reset_settings()
    with (
        patch.object(GNS3Connection, "get", return_value=[]),
        patch.object(GNS3Connection, "post"),
    ):
        conn = GNS3Connection("10.20.20.231", 80, "lab")
        conn.project = {"project_id": "p1"}

    nodes = [
        {"node_id": "n1", "name": "R1"},
        {"node_id": "n2", "name": "R2"},
    ]
    with (
        patch.object(GNS3Connection, "get", return_value=nodes),
        patch.object(GNS3Connection, "post") as mock_post,
    ):
        conn.start_all_nodes()

    assert mock_post.call_count == 2
    called_urls = {call.args[0] for call in mock_post.call_args_list}
    assert called_urls == {
        f"{conn.url}/v2/projects/p1/nodes/n1/start",
        f"{conn.url}/v2/projects/p1/nodes/n2/start",
    }


@allure.title("start_all_nodes überspringt alles im Dry-Run-Modus")
@allure.description(
    "Überprüft, dass start_all_nodes im Dry-Run-Modus keine ESXi/GNS3-API aufruft"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.NORMAL)
def gns3_connection_004() -> None:
    _reset_settings()
    with (
        patch.object(GNS3Connection, "get", return_value=[]),
        patch.object(GNS3Connection, "post"),
    ):
        conn = GNS3Connection("10.20.20.231", 80, "lab")
        conn.project = {"project_id": "p1"}

    Settings.IS_DRY_RUN = True
    try:
        with patch.object(GNS3Connection, "get") as mock_get:
            conn.start_all_nodes()
    finally:
        _reset_settings()

    mock_get.assert_not_called()


@allure.title("get_version fragt die Versions-Info ohne Projekt-Kontext ab")
@allure.description(
    "Überprüft, dass get_version einen reinen Read-Only-GET an /v2/version "
    "sendet, ohne ein GNS3Connection-Objekt (und damit ohne dessen "
    "Projekt-Init-Nebeneffekt) zu benötigen"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_005() -> None:
    with patch.object(
        GNS3Connection, "get", return_value={"version": "2.2.61"}
    ) as mock_get:
        version = GNS3Connection.get_version("10.20.20.231", 80)

    mock_get.assert_called_once_with("http://10.20.20.231:80/v2/version")
    assert version == {"version": "2.2.61"}


@allure.title("list_all_projects listet alle Projekte ohne Projekt-Kontext")
@allure.description(
    "Überprüft, dass list_all_projects einen reinen Read-Only-GET an "
    "/v2/projects sendet"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_006() -> None:
    projects = [{"project_id": "p1", "name": "lab"}]
    with patch.object(GNS3Connection, "get", return_value=projects) as mock_get:
        result = GNS3Connection.list_all_projects("10.20.20.231", 80)

    mock_get.assert_called_once_with("http://10.20.20.231:80/v2/projects")
    assert result == projects


@allure.title("list_project_nodes listet die Nodes eines Projekts")
@allure.description(
    "Überprüft, dass list_project_nodes einen reinen Read-Only-GET an "
    "/v2/projects/{id}/nodes sendet"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_007() -> None:
    nodes = [{"node_id": "n1", "name": "R1", "status": "started"}]
    with patch.object(GNS3Connection, "get", return_value=nodes) as mock_get:
        result = GNS3Connection.list_project_nodes("10.20.20.231", 80, "p1")

    mock_get.assert_called_once_with("http://10.20.20.231:80/v2/projects/p1/nodes")
    assert result == nodes


@allure.title("list_project_links listet die Links eines Projekts")
@allure.description(
    "Überprüft, dass list_project_links einen reinen Read-Only-GET an "
    "/v2/projects/{id}/links sendet"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_008() -> None:
    links = [{"nodes": [{"node_id": "n1"}, {"node_id": "n2"}]}]
    with patch.object(GNS3Connection, "get", return_value=links) as mock_get:
        result = GNS3Connection.list_project_links("10.20.20.231", 80, "p1")

    mock_get.assert_called_once_with("http://10.20.20.231:80/v2/projects/p1/links")
    assert result == links


def _make_incremental_connection(
    existing_project, existing_nodes, existing_links
) -> GNS3Connection:
    """
    Constructs a real GNS3Connection in incremental mode, with 'get' mocked
    to serve the given existing project/nodes/links.
    """

    def fake_get(url: str, *args, **kwargs):
        if url.endswith("/v2/projects"):
            return [existing_project] if existing_project else []
        if url.endswith("/nodes"):
            return existing_nodes
        if url.endswith("/links"):
            return existing_links
        raise AssertionError(f"unexpected GET {url}")

    with patch.object(GNS3Connection, "get", side_effect=fake_get):
        return GNS3Connection("10.20.20.231", 80, "lab", incremental=True)


@allure.title(
    "Incremental GNS3Connection reused ein bestehendes Projekt ohne es zu löschen"
)
@allure.description(
    "Überprüft, dass ein im incremental-Modus konstruiertes GNS3Connection "
    "ein bestehendes, bereits geöffnetes Projekt unverändert übernimmt, "
    "ohne delete oder post aufzurufen"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_009() -> None:
    existing_project = {"project_id": "p1", "name": "lab", "status": "opened"}
    with (
        patch.object(GNS3Connection, "delete") as mock_delete,
        patch.object(GNS3Connection, "post") as mock_post,
    ):
        conn = _make_incremental_connection(existing_project, [], [])

    mock_delete.assert_not_called()
    mock_post.assert_not_called()
    assert conn.project == existing_project


@allure.title(
    "create_node reused einen bereits existierenden GNS3-Node im incremental-Modus"
)
@allure.description(
    "Überprüft, dass create_node im incremental-Modus einen bereits "
    "existierenden Node (gleicher Name) unverändert zurückgibt, statt "
    "einen zweiten, doppelten Node anzulegen"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_010() -> None:
    existing_project = {"project_id": "p1", "name": "lab", "status": "opened"}
    existing_node = {"node_id": "n1", "name": "R1", "status": "started"}
    with (
        patch.object(GNS3Connection, "delete"),
        patch.object(GNS3Connection, "post") as mock_post,
    ):
        conn = _make_incremental_connection(existing_project, [existing_node], [])

    node = MagicMock()
    node.name = "R1"

    result = conn.create_node(node)

    mock_post.assert_not_called()
    assert result == existing_node
    assert node.gns3_node_info == existing_node


@allure.title(
    "connect_nodes überspringt einen bereits bestehenden Link im incremental-Modus"
)
@allure.description(
    "Überprüft, dass connect_nodes im incremental-Modus keinen neuen Link "
    "anlegt, wenn zwischen den beiden Node-IDs bereits ein Link existiert"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_011() -> None:
    existing_project = {"project_id": "p1", "name": "lab", "status": "opened"}
    existing_link = {"nodes": [{"node_id": "n1"}, {"node_id": "n2"}]}
    with (
        patch.object(GNS3Connection, "delete"),
        patch.object(GNS3Connection, "post") as mock_post,
    ):
        conn = _make_incremental_connection(existing_project, [], [existing_link])

    node_1 = MagicMock()
    node_1.name = "R1"
    node_1.gns3_node_info = {"node_id": "n1"}
    node_2 = MagicMock()
    node_2.name = "R2"
    node_2.gns3_node_info = {"node_id": "n2"}
    node_1.get_interface.return_value = MagicMock(name="gi0/0")
    node_2.get_interface.return_value = MagicMock(name="gi0/0")

    result = conn.connect_nodes(node_1, node_2)

    mock_post.assert_not_called()
    assert result is None


@allure.title("set_node_positions gibt jedem Node im Graph eine eigene Position")
@allure.description(
    "Überprüft, dass set_node_positions für jeden Node im Graph eine "
    "eigene (x, y)-Position berechnet (über das Force-Directed-Layout aus "
    "src.graph.layout), statt dass alle Nodes im GNS3 Web UI übereinander "
    "landen, und dass _position_for diese Positionen danach zurückgibt"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_012() -> None:
    from src.graph import Graph

    Settings.API.LITERAL_API_VALUES = True
    graph = Graph(
        [{"image": "VPCS", "role": "ROUTER", "names": ["R1", "R2", "R3"]}],
        [["R1", "gi0/0", "R2", "gi0/0"], ["R2", "gi0/1", "R3", "gi0/0"]],
    )

    conn = GNS3Connection.__new__(GNS3Connection)
    conn.set_node_positions(graph)

    positions = [conn._position_for(name) for name in ("R1", "R2", "R3")]
    assert len(set(positions)) == 3


@allure.title(
    "_position_for fällt auf (0, 0) zurück, wenn keine Position berechnet wurde"
)
@allure.description(
    "Überprüft, dass _position_for (0, 0) zurückgibt, wenn "
    "set_node_positions nie aufgerufen wurde oder der Node nicht im "
    "verwendeten Graph war"
)
@allure.tag("negativ-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.NORMAL)
def gns3_connection_013() -> None:
    conn = GNS3Connection.__new__(GNS3Connection)
    assert conn._position_for("R1") == (0, 0)


def _make_node_info(name: str, port_names: list[str]) -> dict:
    return {
        "name": name,
        "ports": [{"name": port_name} for port_name in port_names],
    }


def _make_interface(name: str, parent_name: str = "R1") -> MagicMock:
    intf = MagicMock()
    intf.name = name
    intf.parent.name = parent_name
    return intf


@allure.title("_get_adapter findet einen exakten Namens-Match")
@allure.description(
    "Überprüft, dass _get_adapter bei einer Namensübereinstimmung "
    "(Groß-/Kleinschreibung egal) diesen Port zurückgibt"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_014() -> None:
    node_info = _make_node_info("R1", ["Gi0/0", "Gi0/1"])
    adapter = GNS3Connection._get_adapter(node_info, _make_interface("gi0/1"))
    assert adapter["name"] == "Gi0/1"


@allure.title("_get_adapter fällt auf den einzigen Port zurück")
@allure.description(
    "Überprüft, dass _get_adapter bei einem Node mit genau einem Port "
    "diesen zurückgibt, auch wenn sein Name nicht mit der Topology-"
    "Config übereinstimmt (z.B. VPCS' 'Ethernet0' vs. 'gi0/0')"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_015() -> None:
    node_info = _make_node_info("PC1", ["Ethernet0"])
    adapter = GNS3Connection._get_adapter(node_info, _make_interface("gi0/0", "PC1"))
    assert adapter["name"] == "Ethernet0"


@allure.title("_get_adapter fällt auf eine eindeutige Portnummer zurück")
@allure.description(
    "Überprüft, dass _get_adapter bei mehreren Ports ohne Namens-Match "
    "einen Port über die übereinstimmende, eindeutige Trailing-Portnummer "
    "findet (z.B. Config 'gi0/2' vs. Template-Port 'Ethernet2')"
)
@allure.tag("positiv-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_016() -> None:
    node_info = _make_node_info("R1", ["Ethernet0", "Ethernet1", "Ethernet2"])
    adapter = GNS3Connection._get_adapter(node_info, _make_interface("gi0/2"))
    assert adapter["name"] == "Ethernet2"


@allure.title("_get_adapter wirft einen Fehler, wenn kein Port zugeordnet werden kann")
@allure.description(
    "Überprüft, dass _get_adapter einen ValueError wirft, wenn weder ein "
    "Namens-Match noch ein eindeutiger Portnummer-Match möglich ist"
)
@allure.tag("negativ-test", "gns3-connection")
@allure.feature("gns3_connection")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_connection_017() -> None:
    node_info = _make_node_info("R1", ["Ethernet0", "Ethernet1"])
    with pytest.raises(ValueError, match="gi0/5"):
        GNS3Connection._get_adapter(node_info, _make_interface("gi0/5"))
