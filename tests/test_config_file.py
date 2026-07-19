import allure
import pytest
import logger_adapter
from config_file_handler import ConfigFileHandler

logger_adapter.LoggerAdapter.is_test_run = True
TEST_FILE_FOLDER = "./tests/files/"


def add_folder_path(path: str) -> str:
    """
    Inserts the TEST_FILE_FOLDER path before given path
    :param path: to be modified
    :return: new path
    """
    return TEST_FILE_FOLDER + path


@allure.title("Falscher Pfad Datentyp")
@allure.description("Überprüft, ob ConfigFileHandler() erkennt, path von typ str ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_000() -> None:
    with pytest.raises(
        TypeError,
        match=r"Path must be a string. Current type: .+",
    ):
        ConfigFileHandler(5)


@allure.title("Datei exestiert nicht")
@allure.description(
    "Überprüft, ob ConfigFileHandler() erkennt, ob Datei überhaupt exestiert"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_001() -> None:
    with pytest.raises(
        FileNotFoundError,
        match=r"File does not exists. Current path: ./not_existing_file",
    ):
        ConfigFileHandler("./not_existing_file")


@allure.title("Pfad zu Directory angeben")
@allure.description(
    "Überprüft, ob ConfigFileHandler() erkennt, ob der Pfad nicht auf eine Datei zeigt."
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_002() -> None:
    with pytest.raises(
        ValueError,
        match=r"Path does not link to \*\.yaml or \*\.yml file\. Current path: .*",
    ):
        ConfigFileHandler("./tests")


@allure.title("Richtiges Format validieren")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() die richtige Configurations Datei richtig validiert"
)
@allure.tag("user-input", "positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_003() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_003.yml"))
    c.validate_file()


@allure.title("'nodes' key fehlt")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() erkennt, ob der Dictionary Key 'nodes' fehlt"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_004() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_004.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()


@allure.title("'edges' key fehlt")
@allure.description(
    "Überprüft, ob ConfigFileHandler.validate_file() erkennt, ob der Dictionary Key 'edges' fehlt"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_005() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_005.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()


@allure.title("'nodes' value typ falsch")
@allure.description("Testet ob erkannt wird, dass 'nodes' keine Liste als Value hat")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_006() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_006.yml"))
    with pytest.raises(
        TypeError,
        match=r".nodes. must be of type list. Current type: ",
    ):
        c.validate_file()


@allure.title("'edges' value typ falsch")
@allure.description("Testet ob erkannt wird, dass 'edges' keine Liste als Value hat")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_007() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_007.yml"))
    with pytest.raises(
        TypeError,
        match=r".edges. must be of type list. Current type: ",
    ):
        c.validate_file()


@allure.title("node_group typ falsch")
@allure.description("Testet ob erkannt wird, ob node_group den falschen typ hat")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_008() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_008.yml"))
    with pytest.raises(
        TypeError,
        match=r"Node group must be of type dict. Current type:",
    ):
        c.validate_file()


@allure.title("'image' key nicht in node_group")
@allure.description(
    "Testet ob erkannt wird, dass der 'image' key nicht  in node_group ist"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_009() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_009.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .image., .role. or .names. not found in configuration file under .nodes.. Current keys: .*",
    ):
        c.validate_file()


@allure.title("'role' key nicht in node_group")
@allure.description(
    "Testet ob erkannt wird, dass der 'role' key nicht  in node_group ist"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_010() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_010.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .image., .role. or .names. not found in configuration file under .nodes.. Current keys: .*",
    ):
        c.validate_file()


@allure.title("'names' key nicht in node_group")
@allure.description(
    "Testet ob erkannt wird, dass der 'names' key nicht  in node_group ist"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_011() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_011.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .image., .role. or .names. not found in configuration file under .nodes.. Current keys: .*",
    ):
        c.validate_file()


@allure.title("'image' value typ falsch")
@allure.description("Testet ob erkannt wird, ob der 'image' value typ falsch ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_012() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_012.yml"))
    with pytest.raises(
        TypeError,
        match=r"Image must be of type string. Current type: ",
    ):
        c.validate_file()


@allure.title("'role' value typ ist falsch")
@allure.description("Testet ob erkannt wird, ob der 'role' value typ falsch ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_013() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_013.yml"))
    with pytest.raises(
        TypeError,
        match=r" ",
    ):
        c.validate_file()


@allure.title("'role' value ungültig")
@allure.description("Testet ob erkannt wird, ob der 'role' value ungültig ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_014() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_014.yml"))
    with pytest.raises(
        ValueError,
        match=r" is not a valid role. Valid roles: ",
    ):
        c.validate_file()


@allure.title("'names' value typ falsch")
@allure.description("Testet ob erkannt wird, ob der 'names' value typ falsch ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_015() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_015.yml"))
    with pytest.raises(
        TypeError,
        match=r"Names must be of type list or None. Current type: ",
    ):
        c.validate_file()


@allure.title("name value ist None")
@allure.description("Testet ob erkannt wird, ob ein 'names' value von typ None ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_016() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_016.yml"))
    with pytest.raises(
        TypeError,
        match=r"Entries of .names. must be of type str. Current type: ",
    ):
        c.validate_file()


@allure.title("'names' doppelte namen")
@allure.description("Testet ob erkannt wird, ob in 'names' ein value doppelt vorkommt")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_017() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_017.yml"))
    with pytest.raises(
        ValueError,
        match=r"Node names must be distinct. Not unique names: .*PC3",
    ):
        c.validate_file()


@allure.title("doppelte Namen")
@allure.description("Testet ob erkannt wird, ob insgesamt doppelte Namen vorkommen")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_018() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_018.yml"))
    with pytest.raises(
        ValueError,
        match=r"Node names must be distinct. Not unique names: .*PC4",
    ):
        c.validate_file()


@allure.title("edges node namen nicht initialisiert")
@allure.description(
    "Testet ob erkannt wird, ob in edges namen vorkommen, welche nicht initialisiert wurden"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_019() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_019.yml"))
    with pytest.raises(
        ValueError,
        match=r"Name not defined in .nodes.: PC-TEST, SW-C1",
    ):
        c.validate_file()


@allure.title("zu wenige values in edge")
@allure.description("Testet ob erkannt wird, ob genug Values in edge vorkommen")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_020() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_020.yml"))
    with pytest.raises(
        ValueError,
        match=r"List of .edges. must be of length 4",
    ):
        c.validate_file()


@allure.title("Interface besetzung")
@allure.description("Testet ob erkannt wird, ob Interfaces doppelt besetzt werden")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_021() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_021.yml"))
    with pytest.raises(
        ValueError,
        match=r"Interface gi0/3 is used twice in edges of SW-C1 node",
    ):
        c.validate_file()


@allure.title("Interface namen typ falsch")
@allure.description("Testet ob erkannt wird, ob Interface namen vom falsch typ sind")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_022() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_022.yml"))
    with pytest.raises(
        ValueError,
        match=r"Contents of .edge. must be of type str: ",
    ):
        c.validate_file()


@allure.title("'names' typ ist None")
@allure.description("Testet ob es gültig ist, wenn der value von 'names', None ist")
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_023() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_023.yml"))
    c.validate_file()


@allure.title("edge node name typ ist falsch")
@allure.description(
    "Testet ob erkannt wird, ob in edge, die node namen nicht den richtigen typ haben"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_024() -> None:
    c = ConfigFileHandler(add_folder_path("config_file_024.yml"))
    with pytest.raises(
        ValueError,
        match=r"Contents of .edge. must be of type str: ",
    ):
        c.validate_file()
