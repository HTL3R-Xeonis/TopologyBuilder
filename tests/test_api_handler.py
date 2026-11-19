"""
Tests to validate functionality of src/connections/api_handler.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest

from src.connections.api_handler import APIHandler
from src.settings import Settings


def _tpl(name: str, file: str, source_dir: str | None = "ova") -> dict:
    template = {"name": name, "file": file}
    if source_dir is not None:
        template["_source_dir"] = source_dir
    return template


@allure.title("find_esxi_template_url findet die OVA-URL für ein passendes Template")
@allure.description(
    "Überprüft, dass find_esxi_template_url das Template-Verzeichnis abruft, "
    "per normalisiertem Namen matcht und aus OVA_BASE_URL, _source_dir und "
    "file die URL baut, die der ESXi-Host selbst herunterlädt"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_000() -> None:
    data = {
        "templates": [
            _tpl("Ubuntu-Server", "ubuntu-server.ova", "linux/ubuntu"),
            _tpl("pfSense", "pfsense.ova"),
        ]
    }

    with (
        patch.object(Settings.API, "OVA_BASE_URL", "http://ova.example:80"),
        patch.object(APIHandler, "get", return_value=data) as mock_get,
    ):
        result = APIHandler.find_esxi_template_url("ubuntu-server")

    mock_get.assert_called_once_with(
        f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/templates"
    )
    assert result == "http://ova.example:80/linux/ubuntu/ubuntu-server.ova"


@allure.title("find_esxi_template_url wirft ValueError, wenn kein Template passt")
@allure.description(
    "Überprüft, dass find_esxi_template_url einen ValueError wirft, wenn "
    "kein Template-Name mit dem gesuchten Image übereinstimmt"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_001() -> None:
    data = {"templates": [_tpl("pfSense", "pfsense.ova")]}

    with patch.object(APIHandler, "get", return_value=data), pytest.raises(ValueError):
        APIHandler.find_esxi_template_url("Ubuntu-Server")


@allure.title("find_esxi_template_url kommt ohne _source_dir aus")
@allure.description(
    "Fehlt _source_dir oder ist es leer, liegt die OVA direkt unter OVA_BASE_URL"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_002() -> None:
    for source_dir in (None, ""):
        data = {"templates": [_tpl("pfSense", "pfsense.ova", source_dir)]}
        with (
            patch.object(Settings.API, "OVA_BASE_URL", "http://ova.example:80"),
            patch.object(APIHandler, "get", return_value=data),
        ):
            assert (
                APIHandler.find_esxi_template_url("pfsense")
                == "http://ova.example:80/pfsense.ova"
            )


@allure.title("find_esxi_template_url kodiert Leerzeichen und Sonderzeichen")
@allure.description(
    "Dateiname und Verzeichnis werden pro Pfadteil prozentkodiert, die '/' des "
    "Verzeichnisses bleiben Trenner"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_003() -> None:
    data = {"templates": [_tpl("Kali", "Kali Linux 2024.ova", "my dir/sub")]}
    with (
        patch.object(Settings.API, "OVA_BASE_URL", "http://ova.example:80"),
        patch.object(APIHandler, "get", return_value=data),
    ):
        url = APIHandler.find_esxi_template_url("kali")

    assert url == "http://ova.example:80/my%20dir/sub/Kali%20Linux%202024.ova"


@allure.title("find_esxi_template_url_by_file löst den exakten Dateinamen auf")
@allure.description(
    "Überprüft, dass der exakte file-Wert eines Templates (nicht der Name) in die "
    "OVA-URL aufgelöst wird"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_004() -> None:
    data = {
        "templates": [
            _tpl("GNS3 VM", "gns3vm.ova", "gns3"),
            _tpl("pfSense", "pfsense.ova"),
        ]
    }
    with (
        patch.object(Settings.API, "OVA_BASE_URL", "http://ova.example:80"),
        patch.object(APIHandler, "get", return_value=data),
    ):
        assert (
            APIHandler.find_esxi_template_url_by_file("gns3vm.ova")
            == "http://ova.example:80/gns3/gns3vm.ova"
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


@allure.title("find_esxi_template_url_by_file wirft ValueError bei unbekannter Datei")
@allure.description(
    "Es wird nicht unscharf nach Namen gesucht: nur ein exakt gleiches file-Feld trifft"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_010() -> None:
    data = {"templates": [_tpl("pfSense", "pfsense.ova")]}

    with patch.object(APIHandler, "get", return_value=data):
        with pytest.raises(ValueError, match="pfsense"):
            APIHandler.find_esxi_template_url_by_file("pfsense")
        with pytest.raises(ValueError, match="other.ova"):
            APIHandler.find_esxi_template_url_by_file("other.ova")


@allure.title("find_esxi_template_url reicht Fehler der Template-API durch")
@allure.description(
    "Ein Timeout der Template-API wird nicht verschluckt, damit der Deploy vor dem "
    "Löschen abbricht"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.NORMAL)
def api_handler_011() -> None:
    with (
        patch.object(APIHandler, "get", side_effect=TimeoutError("slow")),
        pytest.raises(TimeoutError),
    ):
        APIHandler.find_esxi_template_url("x")
    with (
        patch.object(APIHandler, "get", side_effect=TimeoutError("slow")),
        pytest.raises(TimeoutError),
    ):
        APIHandler.find_esxi_template_url_by_file("x.ova")
