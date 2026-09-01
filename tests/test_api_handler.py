"""
Tests to validate functionality of src/connections/api_handler.py
"""

__license__ = "GNU GPLv3"

import io
import tarfile
from unittest.mock import MagicMock, patch

import allure
import pytest
import requests

from src.connections.api_handler import APIHandler


def _make_ova_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        ovf = b"<Envelope/>"
        info = tarfile.TarInfo(name="vm.ovf")
        info.size = len(ovf)
        tf.addfile(info, io.BytesIO(ovf))
    return buf.getvalue()


def _make_response(body: bytes) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.iter_content = MagicMock(return_value=[body])
    return response


@allure.title("download_ova speichert eine vollständige OVA beim ersten Versuch")
@allure.description(
    "Überprüft, dass download_ova die heruntergeladene Datei akzeptiert, "
    "wenn sie ein strukturell vollständiges Tar-Archiv ist"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_000(tmp_path) -> None:
    ova_bytes = _make_ova_bytes()
    dest_path = str(tmp_path / "template.ova")

    with patch(
        "src.connections.api_handler.requests.get",
        return_value=_make_response(ova_bytes),
    ) as mock_get:
        APIHandler.download_ova("Ubuntu-Server", dest_path)

    mock_get.assert_called_once()
    with tarfile.open(dest_path) as archive:
        assert archive.getnames() == ["vm.ovf"]


@allure.title("download_ova wiederholt den Download bei einer abgeschnittenen Datei")
@allure.description(
    "Überprüft, dass download_ova einen erneuten Versuch startet, wenn die "
    "heruntergeladene Datei kein vollständiges Tar-Archiv ist, und die "
    "zweite, vollständige Antwort akzeptiert"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_001(tmp_path) -> None:
    ova_bytes = _make_ova_bytes()
    dest_path = str(tmp_path / "template.ova")
    responses = [_make_response(b"truncated-garbage"), _make_response(ova_bytes)]

    with patch(
        "src.connections.api_handler.requests.get", side_effect=responses
    ) as mock_get:
        APIHandler.download_ova("Ubuntu-Server", dest_path)

    assert mock_get.call_count == 2
    with tarfile.open(dest_path) as archive:
        assert archive.getnames() == ["vm.ovf"]


@allure.title("download_ova gibt nach wiederholt unvollständigen Downloads auf")
@allure.description(
    "Überprüft, dass download_ova einen RuntimeError wirft, wenn jeder "
    "Versuch eine unvollständige Datei liefert"
)
@allure.tag("negativ-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_002(tmp_path) -> None:
    dest_path = str(tmp_path / "template.ova")

    with patch(
        "src.connections.api_handler.requests.get",
        return_value=_make_response(b"still-garbage"),
    ) as mock_get:
        with pytest.raises(
            RuntimeError, match=r"Failed to download a complete OVA for 'Ubuntu-Server'"
        ):
            APIHandler.download_ova("Ubuntu-Server", dest_path)

    assert mock_get.call_count == 3


@allure.title("download_ova wiederholt den Download bei einem Verbindungsfehler")
@allure.description(
    "Überprüft, dass download_ova einen erneuten Versuch startet, wenn "
    "der Request selbst fehlschlägt (z.B. ConnectionError/Timeout, nicht "
    "nur eine abgeschnittene Datei), statt den Fehler unbehandelt und "
    "ungeloggt bis zum Aufrufer durchzureichen"
)
@allure.tag("positiv-test", "api-handler")
@allure.feature("api_handler")
@allure.severity(allure.severity_level.CRITICAL)
def api_handler_003(tmp_path) -> None:
    ova_bytes = _make_ova_bytes()
    dest_path = str(tmp_path / "template.ova")
    responses = [
        requests.exceptions.ConnectionError("connection reset"),
        _make_response(ova_bytes),
    ]

    with patch(
        "src.connections.api_handler.requests.get", side_effect=responses
    ) as mock_get:
        APIHandler.download_ova("Ubuntu-Server", dest_path)

    assert mock_get.call_count == 2
    with tarfile.open(dest_path) as archive:
        assert archive.getnames() == ["vm.ovf"]
