"""
Tests to validate functionality of src/mac_range.py
"""

__license__ = "GNU GPLv3"

import allure
import pytest

from src.mac_range import int_to_mac, mac_in_range, mac_to_int, pick_mac_in_range


@allure.title("mac_to_int und int_to_mac sind zueinander invers")
@allure.description(
    "Überprüft, dass int_to_mac(mac_to_int(mac)) die ursprüngliche "
    "MAC-Adresse (kleingeschrieben) zurückgibt"
)
@allure.tag("positiv-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.CRITICAL)
def mac_range_000() -> None:
    assert mac_to_int("00:50:56:00:10:2a") == 0x0050_5600_102A
    assert int_to_mac(0x0050_5600_102A) == "00:50:56:00:10:2a"


@allure.title("mac_to_int wirft ValueError bei ungültigen MAC-Adressen")
@allure.description(
    "Überprüft, dass mac_to_int einen ValueError wirft, wenn die Eingabe "
    "keine sechs durch Doppelpunkt getrennten Hex-Oktette hat"
)
@allure.tag("negativ-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.CRITICAL)
def mac_range_001() -> None:
    with pytest.raises(ValueError, match="not a valid MAC address"):
        mac_to_int("not-a-mac")
    with pytest.raises(ValueError, match="not a valid MAC address"):
        mac_to_int("00:50:56:00:10")
    with pytest.raises(ValueError, match="not a valid MAC address"):
        mac_to_int("00:50:56:00:10:zz")


@allure.title("mac_in_range erkennt MACs innerhalb und außerhalb des Bereichs")
@allure.description(
    "Überprüft, dass mac_in_range True für eine MAC innerhalb des "
    "inklusiven Bereichs (inklusive der Grenzen selbst) und False für "
    "eine MAC außerhalb davon zurückgibt"
)
@allure.tag("positiv-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.CRITICAL)
def mac_range_002() -> None:
    start, end = "00:50:56:00:10:00", "00:50:56:00:10:ff"
    assert mac_in_range("00:50:56:00:10:00", start, end) is True
    assert mac_in_range("00:50:56:00:10:ff", start, end) is True
    assert mac_in_range("00:50:56:00:10:80", start, end) is True
    assert mac_in_range("00:50:56:00:11:00", start, end) is False
    assert mac_in_range("00:50:56:00:0f:ff", start, end) is False


@allure.title("pick_mac_in_range gibt eine MAC innerhalb des Bereichs zurück")
@allure.description(
    "Überprüft, dass pick_mac_in_range wiederholt eine MAC-Adresse "
    "liefert, die tatsächlich innerhalb des angegebenen Bereichs liegt"
)
@allure.tag("positiv-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.CRITICAL)
def mac_range_003() -> None:
    start, end = "00:50:56:00:10:00", "00:50:56:00:10:ff"
    for _ in range(20):
        picked = pick_mac_in_range(start, end)
        assert mac_in_range(picked, start, end)


@allure.title("pick_mac_in_range vermeidet ausgeschlossene MAC-Adressen")
@allure.description(
    "Überprüft, dass pick_mac_in_range bei einem Bereich mit genau zwei "
    "möglichen Adressen, von denen eine ausgeschlossen ist, immer die "
    "andere zurückgibt"
)
@allure.tag("positiv-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.CRITICAL)
def mac_range_004() -> None:
    start, end = "00:50:56:00:10:00", "00:50:56:00:10:01"
    excluded = {"00:50:56:00:10:00"}
    for _ in range(20):
        assert pick_mac_in_range(start, end, excluded) == "00:50:56:00:10:01"


@allure.title("pick_mac_in_range wirft ValueError, wenn start nach end liegt")
@allure.description(
    "Überprüft, dass pick_mac_in_range einen ValueError wirft, wenn die "
    "Start-MAC zahlenmäßig größer als die End-MAC ist"
)
@allure.tag("negativ-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.CRITICAL)
def mac_range_005() -> None:
    with pytest.raises(ValueError, match="is after end"):
        pick_mac_in_range("00:50:56:00:10:ff", "00:50:56:00:10:00")


@allure.title(
    "pick_mac_in_range wirft ValueError, wenn der gesamte Bereich ausgeschlossen ist"
)
@allure.description(
    "Überprüft, dass pick_mac_in_range einen ValueError wirft, wenn "
    "jede mögliche MAC im Bereich in excluded enthalten ist (Bereich "
    "erschöpft), statt endlos zu versuchen"
)
@allure.tag("negativ-test", "mac_range")
@allure.feature("mac_range")
@allure.severity(allure.severity_level.NORMAL)
def mac_range_006() -> None:
    with pytest.raises(ValueError, match="Could not find a free MAC"):
        pick_mac_in_range(
            "00:50:56:00:10:00", "00:50:56:00:10:00", {"00:50:56:00:10:00"}
        )
