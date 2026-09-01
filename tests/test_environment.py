"""
Tests to validate functionality of src/graph/environment.py
"""

__license__ = "GNU GPLv3"

from src.graph.environment import Environment, normalize_template_name
from src.settings import Settings

import allure


@allure.title("Template-Namen mit Leerzeichen-Unterschied werden gleichgesetzt")
@allure.description(
    "Überprüft, dass normalize_template_name Namen gleichsetzt, die sich nur "
    "durch ein zusätzliches Leerzeichen unterscheiden"
)
@allure.tag("positiv-test", "environment")
@allure.feature("environment")
@allure.severity(allure.severity_level.CRITICAL)
def environment_000() -> None:
    assert normalize_template_name("Cisco IOSv 15.6(1)T") == normalize_template_name(
        "Cisco IOSv 15.6(1) T"
    )


@allure.title(
    "Template-Namen mit Groß-/Kleinschreibungs-Unterschied werden gleichgesetzt"
)
@allure.description(
    "Überprüft, dass normalize_template_name Namen unabhängig von "
    "Groß-/Kleinschreibung gleichsetzt"
)
@allure.tag("positiv-test", "environment")
@allure.feature("environment")
@allure.severity(allure.severity_level.CRITICAL)
def environment_001() -> None:
    assert normalize_template_name("VPCS") == normalize_template_name("vpcs")


@allure.title("Inhaltlich unterschiedliche Template-Namen bleiben unterschiedlich")
@allure.description(
    "Überprüft, dass normalize_template_name inhaltlich unterschiedliche "
    "Namen nicht fälschlich gleichsetzt"
)
@allure.tag("negativ-test", "environment")
@allure.feature("environment")
@allure.severity(allure.severity_level.NORMAL)
def environment_002() -> None:
    assert normalize_template_name("VPCS") != normalize_template_name("Cloud")


@allure.title("get_environment erkennt GNS3-Templates trotz Leerzeichen-Rauschen")
@allure.description(
    "Überprüft, dass get_environment ein Image einem GNS3-Template zuordnet, "
    "obwohl sich Groß-/Kleinschreibung oder Leerzeichen vom konfigurierten "
    "Template-Namen unterscheiden"
)
@allure.tag("positiv-test", "environment")
@allure.feature("environment")
@allure.severity(allure.severity_level.CRITICAL)
def environment_003() -> None:
    Environment._get_templates.cache_clear()
    Settings.API.LITERAL_API_VALUES = True
    try:
        assert Environment.get_environment("vpcs") == Environment.ON_GNS3
        assert Environment.get_environment(" VPCS") == Environment.ON_GNS3
    finally:
        Environment._get_templates.cache_clear()


@allure.title("get_environment erkennt ESXi-Templates trotz Leerzeichen-Rauschen")
@allure.description(
    "Überprüft, dass get_environment ein Image einem ESXi-Template zuordnet, "
    "obwohl sich Groß-/Kleinschreibung oder Leerzeichen vom konfigurierten "
    "Template-Namen unterscheiden"
)
@allure.tag("positiv-test", "environment")
@allure.feature("environment")
@allure.severity(allure.severity_level.CRITICAL)
def environment_004() -> None:
    Environment._get_templates.cache_clear()
    Settings.API.LITERAL_API_VALUES = True
    try:
        assert Environment.get_environment("ubuntu-server") == Environment.ON_ESXI
        assert Environment.get_environment("Ubuntu- Server") == Environment.ON_ESXI
    finally:
        Environment._get_templates.cache_clear()
