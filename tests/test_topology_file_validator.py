"""
Tests to validate functionality of config_file_handler.py
"""

__autor__ = "Leon Eiböck"
__date__ = "19/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import pytest

from src.settings import Settings
from src.topology_file_validation import TopologyFileValidation

Settings.initialise_settings()
TEST_FILE_FOLDER = "./tests/files/"


def add_folder_path(path: str) -> str:
    """
    Inserts the TEST_FILE_FOLDER path before given path
    :param path: to be modified
    :return: new path
    """
    return TEST_FILE_FOLDER + path


@pytest.mark.testlink(
    title="Falscher Pfad Datentyp",
    description="Überprüft, ob TopologyFileValidation() erkennt, path von typ str ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_000() -> None:
    with pytest.raises(
        TypeError,
        match=r"Path must be a string. Current type: .+",
    ):
        TopologyFileValidation(5)


@pytest.mark.testlink(
    title="Datei exestiert nicht",
    description="Überprüft, ob TopologyFileValidation() erkennt, ob Datei überhaupt exestiert",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_001() -> None:
    with pytest.raises(
        FileNotFoundError,
        match=r"File does not exists. Current path: ./not_existing_file",
    ):
        TopologyFileValidation("./not_existing_file")


@pytest.mark.testlink(
    title="Pfad zu Directory angeben",
    description="Überprüft, ob TopologyFileValidation() erkennt, ob der Pfad nicht auf eine Datei zeigt.",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_002() -> None:
    with pytest.raises(
        ValueError,
        match=r"Path does not link to \*\.yaml or \*\.yml file\. Current path: .*",
    ):
        TopologyFileValidation("./tests")


@pytest.mark.testlink(
    title="Richtiges Format validieren",
    description="Überprüft, ob TopologyFileValidation.validate_file() die richtige Configurations Datei richtig validiert",
    tag=["user-input", "positiv-test", "config-file"],
    feature="config_file",
    severity="CRITICAL",
)
def conf_file_003() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()


@pytest.mark.testlink(
    title="'nodes' key fehlt",
    description="Überprüft, ob TopologyFileValidation.validate_file() erkennt, ob der Dictionary Key 'nodes' fehlt",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_004() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_004.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'edges' key fehlt",
    description="Überprüft, ob TopologyFileValidation.validate_file() erkennt, ob der Dictionary Key 'edges' fehlt",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_005() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_005.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'nodes' value typ falsch",
    description="Testet ob erkannt wird, dass 'nodes' keine Liste als Value hat",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_006() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_006.yml"))
    with pytest.raises(
        TypeError,
        match=r".nodes. must be of type list. Current type: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'edges' value typ falsch",
    description="Testet ob erkannt wird, dass 'edges' keine Liste als Value hat",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_007() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_007.yml"))
    with pytest.raises(
        TypeError,
        match=r".edges. must be of type list. Current type: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="node_group typ falsch",
    description="Testet ob erkannt wird, ob node_group den falschen typ hat",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_008() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_008.yml"))
    with pytest.raises(
        TypeError,
        match=r"Node group must be of type dict. Current type:",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'image' key nicht in node_group",
    description="Testet ob erkannt wird, dass der 'image' key nicht  in node_group ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_009() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_009.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .image., .role. or .names. not found in configuration file under .nodes.. Current keys: .*",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'role' key nicht in node_group",
    description="Testet ob erkannt wird, dass der 'role' key nicht  in node_group ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_010() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_010.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .image., .role. or .names. not found in configuration file under .nodes.. Current keys: .*",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'names' key nicht in node_group",
    description="Testet ob erkannt wird, dass der 'names' key nicht  in node_group ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_011() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_011.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .image., .role. or .names. not found in configuration file under .nodes.. Current keys: .*",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'image' value typ falsch",
    description="Testet ob erkannt wird, ob der 'image' value typ falsch ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_012() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_012.yml"))
    with pytest.raises(
        TypeError,
        match=r"Image must be of type string. Current type: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'role' value typ ist falsch",
    description="Testet ob erkannt wird, ob der 'role' value typ falsch ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_013() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_013.yml"))
    with pytest.raises(
        TypeError,
        match=r" ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'role' value ungültig",
    description="Testet ob erkannt wird, ob der 'role' value ungültig ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_014() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_014.yml"))
    with pytest.raises(
        ValueError,
        match=r" is not a valid role. Valid roles: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'names' value typ falsch",
    description="Testet ob erkannt wird, ob der 'names' value typ falsch ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_015() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_015.yml"))
    with pytest.raises(
        TypeError,
        match=r"Names must be of type list or None. Current type: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="name value ist None",
    description="Testet ob erkannt wird, ob ein 'names' value von typ None ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_016() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_016.yml"))
    with pytest.raises(
        TypeError,
        match=r"Entries of .names. must be of type str. Current type: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'names' doppelte namen",
    description="Testet ob erkannt wird, ob in 'names' ein value doppelt vorkommt",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_017() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_017.yml"))
    with pytest.raises(
        ValueError,
        match=r"Node names must be distinct. Not unique names: .*PC3",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="doppelte Namen",
    description="Testet ob erkannt wird, ob insgesamt doppelte Namen vorkommen",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_018() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_018.yml"))
    with pytest.raises(
        ValueError,
        match=r"Node names must be distinct. Not unique names: .*PC4",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="edges node namen nicht initialisiert",
    description="Testet ob erkannt wird, ob in edges namen vorkommen, welche nicht initialisiert wurden",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_019() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_019.yml"))
    with pytest.raises(
        ValueError,
        match=r"Name not defined in .nodes.: PC-TEST, SW-C1",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="zu wenige values in edge",
    description="Testet ob erkannt wird, ob genug Values in edge vorkommen",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_020() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_020.yml"))
    with pytest.raises(
        ValueError,
        match=r"List of .edges. must be of length 4",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="Interface besetzung",
    description="Testet ob erkannt wird, ob Interfaces doppelt besetzt werden",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_021() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_021.yml"))
    with pytest.raises(
        ValueError,
        match=r"Interface gi0/3 is used twice in edges of SW-C1 node",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="Interface namen typ falsch",
    description="Testet ob erkannt wird, ob Interface namen vom falsch typ sind",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_022() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_022.yml"))
    with pytest.raises(
        ValueError,
        match=r"Contents of .edge. must be of type str: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="'names' typ ist None",
    description="Testet ob es gültig ist, wenn der value von 'names', None ist",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_023() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_023.yml"))
    c.validate_file()


@pytest.mark.testlink(
    title="edge node name typ ist falsch",
    description="Testet ob erkannt wird, ob in edge, die node namen nicht den richtigen typ haben",
    tag=["user-input", "negativ-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_024() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_024.yml"))
    with pytest.raises(
        ValueError,
        match=r"Contents of .edge. must be of type str: ",
    ):
        c.validate_file()


@pytest.mark.testlink(
    title="Doppelte node_groups vorhanden",
    description="Testet ob es funktioniert, dass man zwei gleiche Node Groups in der file angibt, mit verschiedenen Namen",
    tag=["user-input", "positiv-test", "config-file"],
    feature="config_file",
    severity="MINOR",
)
def conf_file_025() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_025.yml"))
    c.validate_file()
