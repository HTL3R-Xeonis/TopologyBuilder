"""
Tests to validate functionality of src/connections/api_handler.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest
import requests

from src.connections.api_handler import APIHandler
from src.settings import Settings


@allure.title("find_esxi_template_file findet die OVA-Datei für ein passendes Template")
@allure.description(
    "Überprüft, dass find_esxi_template_file das Template-Verzeichnis abruft, "
    "per normalisiertem Namen matcht und das 'file'-Feld des passenden "
    "Templates zurückgibt"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_000() -> None:
    data = {
        "templates": [
            {"name": "Ubuntu-Server", "file": "ubuntu-server.ova"},
            {"name": "pfSense", "file": "pfsense.ova"},
        ]
    }

    with patch.object(APIHandler, "get", return_value=data) as mock_get:
        result = APIHandler.find_esxi_template_file("ubuntu-server")

    mock_get.assert_called_once_with(
        f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/templates"
    )
    assert result == "ubuntu-server.ova"


@allure.title("find_esxi_template_file wirft ValueError, wenn kein Template passt")
@allure.description(
    "Überprüft, dass find_esxi_template_file einen ValueError wirft, wenn "
    "kein Template-Name mit dem gesuchten Image übereinstimmt"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_001() -> None:
    data = {"templates": [{"name": "pfSense", "file": "pfsense.ova"}]}

    with patch.object(APIHandler, "get", return_value=data), pytest.raises(ValueError):
        APIHandler.find_esxi_template_file("Ubuntu-Server")


@allure.title("deploy_ova postet die Deploy-Daten an die OVA-Deploy-API")
@allure.description(
    "Überprüft, dass deploy_ova einen POST an {OVA_DEPLOY_URL}/deploy/ova "
    "mit ip, port, vm_name, ova_filename, datastore und network im "
    "JSON-Body schickt"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_002() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch(
        "src.connections.api_handler.requests.post", return_value=response
    ) as mock_post:
        APIHandler.deploy_ova(
            "10.20.20.202",
            443,
            "PC1",
            "ubuntu-server.ova",
            "datastore1",
            {"gi0/0": "PG-VLAN-10"},
        )

    mock_post.assert_called_once_with(
        f"{Settings.API.OVA_DEPLOY_URL}/deploy/ova",
        json={
            "ip": "10.20.20.202",
            "port": 443,
            "vm_name": "PC1",
            "ova_filename": "ubuntu-server.ova",
            "datastore": "datastore1",
            "network": {"gi0/0": "PG-VLAN-10"},
        },
        timeout=Settings.API.OVA_DEPLOY_TIMEOUT_SECONDS,
    )


@allure.title("deploy_ova wirft TimeoutError bei einem Timeout")
@allure.description(
    "Überprüft, dass deploy_ova einen TimeoutError wirft, wenn der Request "
    "in ein requests.Timeout läuft"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_003() -> None:
    with (
        patch(
            "src.connections.api_handler.requests.post",
            side_effect=requests.Timeout(),
        ),
        pytest.raises(TimeoutError),
    ):
        APIHandler.deploy_ova(
            "10.20.20.202", 443, "PC1", "ubuntu-server.ova", "datastore1", {}
        )


@allure.title("deploy_ova wirft RuntimeError bei einem HTTP-Fehler")
@allure.description(
    "Überprüft, dass deploy_ova einen RuntimeError wirft, wenn der Request "
    "mit einem anderen requests.RequestException fehlschlägt (z.B. ein "
    "HTTPError durch raise_for_status)"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_004() -> None:
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("500 server error")

    with (
        patch("src.connections.api_handler.requests.post", return_value=response),
        pytest.raises(RuntimeError),
    ):
        APIHandler.deploy_ova(
            "10.20.20.202", 443, "PC1", "ubuntu-server.ova", "datastore1", {}
        )


@allure.title(
    "post verwendet einen Timeout von 30 Sekunden, wenn keiner angegeben wird"
)
@allure.description(
    "Überprüft, dass APIHandler.post standardmäßig mit timeout=30 an "
    "requests.post übergibt, statt ganz ohne Timeout zu laufen"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_005() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch(
        "src.connections.api_handler.requests.post", return_value=response
    ) as mock_post:
        APIHandler.post("http://example.com/thing")

    assert mock_post.call_args.kwargs["timeout"] == 30


@allure.title("post gibt einen expliziten Timeout an requests.post weiter")
@allure.description(
    "Überprüft, dass ein explizit übergebener timeout-Parameter den "
    "30-Sekunden-Standardwert von APIHandler.post überschreibt"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_006() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch(
        "src.connections.api_handler.requests.post", return_value=response
    ) as mock_post:
        APIHandler.post("http://example.com/thing", timeout=300)

    assert mock_post.call_args.kwargs["timeout"] == 300


@allure.title("delete verwendet standardmäßig einen 5-Sekunden-Timeout")
@allure.description(
    "Überprüft, dass APIHandler.delete() ohne expliziten timeout-"
    "Parameter weiterhin den bisherigen 5-Sekunden-Standardwert an "
    "requests.delete übergibt"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_007() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch(
        "src.connections.api_handler.requests.delete", return_value=response
    ) as mock_delete:
        APIHandler.delete("http://example.com/thing")

    assert mock_delete.call_args.kwargs["timeout"] == 5


@allure.title("delete gibt einen expliziten Timeout an requests.delete weiter")
@allure.description(
    "Überprüft, dass ein explizit übergebener timeout-Parameter den "
    "5-Sekunden-Standardwert von APIHandler.delete überschreibt - real "
    "gebraucht von GNS3Connection.delete_node, das ein Node löschen kann, "
    "dessen Prozess erst gestoppt werden muss (siehe HANDOFF.md)"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_008() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch(
        "src.connections.api_handler.requests.delete", return_value=response
    ) as mock_delete:
        APIHandler.delete("http://example.com/thing", timeout=300)

    assert mock_delete.call_args.kwargs["timeout"] == 300


@allure.title("get verwendet standardmäßig 5 Sekunden und lässt sich überschreiben")
@allure.description(
    "Überprüft, dass APIHandler.get() ohne timeout-Parameter weiterhin 5 "
    "Sekunden an requests.get übergibt und einen expliziten timeout "
    "durchreicht (vorher war der Wert fest eingebaut, wie bei delete früher)"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_009() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch(
        "src.connections.api_handler.requests.get", return_value=response
    ) as mock_get:
        APIHandler.get("http://example.com/thing")
        APIHandler.get("http://example.com/thing", timeout=60)

    assert [call.kwargs["timeout"] for call in mock_get.call_args_list] == [5, 60]


@allure.title(
    "check_ova_readable fragt die OVA-Deploy-API und akzeptiert eine lesbare OVA"
)
@allure.description(
    "Überprüft, dass check_ova_readable einen GET an {OVA_DEPLOY_URL}/ova/check "
    "mit dem Dateinamen schickt und bei 200 nichts wirft"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_010() -> None:
    response = MagicMock(status_code=200, ok=True)

    with patch(
        "src.connections.api_handler.requests.get", return_value=response
    ) as mock_get:
        APIHandler.check_ova_readable("ubuntu-server.ova")

    mock_get.assert_called_once_with(
        f"{Settings.API.OVA_DEPLOY_URL}/ova/check",
        params={"ova_filename": "ubuntu-server.ova"},
        timeout=Settings.API.OVA_CHECK_TIMEOUT_SECONDS,
    )


@allure.title(
    "check_ova_readable meldet eine nicht lesbare OVA mit dem Grund des Dienstes"
)
@allure.description(
    "Überprüft, dass check_ova_readable bei einem 503 einen RuntimeError mit dem "
    "'detail' der Antwort wirft"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_011() -> None:
    response = MagicMock(status_code=503, ok=False)
    response.json.return_value = {"detail": "OVA 'x.ova' can not be read: ENXIO"}

    with (
        patch("src.connections.api_handler.requests.get", return_value=response),
        pytest.raises(RuntimeError, match="can not be read: ENXIO"),
    ):
        APIHandler.check_ova_readable("x.ova")


@allure.title(
    "check_ova_readable überspringt den Check bei einem Dienst ohne /ova/check"
)
@allure.description(
    "Überprüft, dass ein 404 (älterer Dienst ohne diese Route) keinen Fehler auslöst"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_012() -> None:
    response = MagicMock(status_code=404, ok=False)

    with patch("src.connections.api_handler.requests.get", return_value=response):
        APIHandler.check_ova_readable("x.ova")


@allure.title(
    "check_ova_readable wirft RuntimeError, wenn der Dienst nicht erreichbar ist"
)
@allure.description(
    "Überprüft, dass ein Verbindungsfehler als RuntimeError gemeldet wird - vor dem "
    "Deploy, solange noch nichts gelöscht wurde"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_013() -> None:
    with (
        patch(
            "src.connections.api_handler.requests.get",
            side_effect=requests.exceptions.ConnectionError("down"),
        ),
        pytest.raises(RuntimeError, match="not reachable"),
    ):
        APIHandler.check_ova_readable("x.ova")
