"""
Tests to validate functionality of src/connections/topology_generator_client.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest
import requests

from src.connections.topology_generator_client import TopologyGeneratorClient
from src.settings import Settings


@allure.title("generate_topology postet den Prompt und gibt die Antwort zurück")
@allure.description(
    "Überprüft, dass generate_topology einen POST an "
    "{TOPOLOGY_GENERATOR_URL}/api/generate-topology mit dem Prompt im "
    "JSON-Body schickt und die geparste Antwort zurückgibt"
)
@allure.tag("positiv-test", "topology-generator-client")
@allure.feature("topology_generator_client")
@allure.severity(allure.severity_level.CRITICAL)
def topology_generator_client_000() -> None:
    response = MagicMock()
    response.json.return_value = {"yaml": "nodes: []", "valid": True, "warnings": []}

    with patch(
        "src.connections.topology_generator_client.requests.post",
        return_value=response,
    ) as mock_post:
        result = TopologyGeneratorClient.generate_topology("a small lab")

    mock_post.assert_called_once_with(
        f"{Settings.API.TOPOLOGY_GENERATOR_URL}/api/generate-topology",
        json={"prompt": "a small lab"},
        timeout=Settings.API.TOPOLOGY_GENERATOR_TIMEOUT_SECONDS,
    )
    assert result == {"yaml": "nodes: []", "valid": True, "warnings": []}


@allure.title("generate_topology wirft TimeoutError bei einem Timeout")
@allure.description(
    "Überprüft, dass generate_topology einen TimeoutError wirft, wenn "
    "der Request in ein requests.Timeout läuft"
)
@allure.tag("negativ-test", "topology-generator-client")
@allure.feature("topology_generator_client")
@allure.severity(allure.severity_level.CRITICAL)
def topology_generator_client_001() -> None:
    with patch(
        "src.connections.topology_generator_client.requests.post",
        side_effect=requests.Timeout(),
    ):
        with pytest.raises(TimeoutError):
            TopologyGeneratorClient.generate_topology("a small lab")


@allure.title("generate_topology wirft RuntimeError bei einem HTTP-Fehler")
@allure.description(
    "Überprüft, dass generate_topology einen RuntimeError wirft, wenn "
    "der Request mit einem anderen requests.RequestException fehlschlägt "
    "(z.B. ein HTTPError durch raise_for_status)"
)
@allure.tag("negativ-test", "topology-generator-client")
@allure.feature("topology_generator_client")
@allure.severity(allure.severity_level.CRITICAL)
def topology_generator_client_002() -> None:
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("500 server error")

    with patch(
        "src.connections.topology_generator_client.requests.post",
        return_value=response,
    ):
        with pytest.raises(RuntimeError):
            TopologyGeneratorClient.generate_topology("a small lab")
