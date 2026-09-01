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

    with patch.object(APIHandler, "get", return_value=data):
        with pytest.raises(ValueError):
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
    with patch(
        "src.connections.api_handler.requests.post",
        side_effect=requests.Timeout(),
    ):
        with pytest.raises(TimeoutError):
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

    with patch("src.connections.api_handler.requests.post", return_value=response):
        with pytest.raises(RuntimeError):
            APIHandler.deploy_ova(
                "10.20.20.202", 443, "PC1", "ubuntu-server.ova", "datastore1", {}
            )
