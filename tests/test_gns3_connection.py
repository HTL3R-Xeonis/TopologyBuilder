"""
Tests to validate functionality of src/connections/gns3_connection.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import patch

import allure

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
