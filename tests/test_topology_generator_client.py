"""
Tests to validate functionality of topology_generator_client.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest
import requests

from src import logger_adapter
from src.topology_generator_client import generate_topology

logger_adapter.LoggerAdapter.is_test_run = True


@allure.title("generate_topology sendet den Prompt und liefert die geparste Antwort")
@allure.description(
    "Überprüft, dass generate_topology POST /api/generate-topology mit dem "
    "gegebenen Prompt als JSON-Body aufruft und die geparste JSON-Antwort "
    "unverändert zurückgibt"
)
@allure.tag("positiv-test", "topology_generator_client")
@allure.feature("topology_generator_client")
@allure.severity(allure.severity_level.CRITICAL)
def topology_generator_client_000() -> None:
    response = MagicMock()
    response.json.return_value = {
        "yaml": "nodes: []\nedges: []\n",
        "valid": True,
        "warnings": [],
    }

    with patch(
        "src.topology_generator_client.requests.post", return_value=response
    ) as mock_post:
        result = generate_topology(
            "a small lab", base_url="http://generator.example:8002"
        )

    mock_post.assert_called_once_with(
        "http://generator.example:8002/api/generate-topology",
        json={"prompt": "a small lab"},
        timeout=1800,
    )
    response.raise_for_status.assert_called_once()
    assert result == {"yaml": "nodes: []\nedges: []\n", "valid": True, "warnings": []}


@allure.title("generate_topology verwendet den gegebenen Timeout")
@allure.description(
    "Überprüft, dass generate_topology einen explizit angegebenen "
    "timeout_seconds-Wert statt des Standardwerts an den Request übergibt"
)
@allure.tag("positiv-test", "topology_generator_client")
@allure.feature("topology_generator_client")
@allure.severity(allure.severity_level.NORMAL)
def topology_generator_client_001() -> None:
    response = MagicMock()
    response.json.return_value = {}

    with patch(
        "src.topology_generator_client.requests.post", return_value=response
    ) as mock_post:
        generate_topology("a small lab", timeout_seconds=60)

    assert mock_post.call_args.kwargs["timeout"] == 60


@allure.title("generate_topology lässt einen HTTP-Fehler durchschlagen")
@allure.description(
    "Überprüft, dass generate_topology eine von raise_for_status() geworfene "
    "HTTPError nicht abfängt, sondern an den Aufrufer weiterreicht"
)
@allure.tag("negativ-test", "topology_generator_client")
@allure.feature("topology_generator_client")
@allure.severity(allure.severity_level.CRITICAL)
def topology_generator_client_002() -> None:
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("500 error")

    with patch("src.topology_generator_client.requests.post", return_value=response):
        with pytest.raises(requests.HTTPError):
            generate_topology("a small lab")
