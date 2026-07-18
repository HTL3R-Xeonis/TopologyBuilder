import allure
import pytest

from config_file_handler import ConfigFileHandler

TEST_FILE_FOLDER = "./tests/files"


def add_folder_path(path: str) -> str:
    """
    Inserts the TEST_FILE_FOLDER path before given path
    :param path: to be modified
    :return: new path
    """
    return TEST_FILE_FOLDER + path


@allure.id("CONF-FILE_001")
@allure.title("Richtiges Format validieren")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() die richtige Configurations Datei richtig validiert"
)
@allure.tag("user-input", "positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def CONF_FILE_001() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_001.yml"))
    c.validate_file()


@allure.id("CONF-FILE_002")
@allure.title("'nodes' key fehlt")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() erkennt, ob der Dictionary Key 'nodes' fehlt"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def CONF_FILE_002() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_002.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()


@allure.id("CONF-FILE_003")
@allure.title("'edges' key fehlt")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() erkennt, ob der Dictionary Key 'edges' fehlt"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def CONF_FILE_003() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_003.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()
