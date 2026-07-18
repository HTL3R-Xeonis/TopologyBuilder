import allure
from config_file_handler import ConfigFileHandler


@allure.id("CONF-FILE_001")
@allure.title("Richtiges Format validieren")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() die richtige Configurations Datei richtig validiert"
)
@allure.tag("User-Input", "positiv-test", "Config-File")
@allure.feature("tests")
@allure.severity(allure.severity_level.CRITICAL)
def CONF_FILE_001() -> None:
    c = ConfigFileHandler("./config_file_example.yml")
    assert c.validate_file() is None
