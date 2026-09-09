"""
Tests to validate functionality of config_file_handler.py
"""

__autor__ = "Leon Eiböck"
__date__ = "19/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import allure
import pytest
from src.topology_file_validation import TopologyFileValidation

TEST_FILE_FOLDER = "./tests/files/"


def add_folder_path(path: str) -> str:
    """
    Inserts the TEST_FILE_FOLDER path before given path
    :param path: to be modified
    :return: new path
    """
    return TEST_FILE_FOLDER + path


@allure.title("Falscher Pfad Datentyp")
@allure.description(
    "Überprüft, ob TopologyFileValidation() erkennt, path von typ str ist"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_000() -> None:
    with pytest.raises(
        TypeError,
        match=r"Path must be a string. Current type: .+",
    ):
        TopologyFileValidation(5)


@allure.title("Datei exestiert nicht")
@allure.description(
    "Überprüft, ob TopologyFileValidation() erkennt, ob Datei überhaupt exestiert"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_001() -> None:
    with pytest.raises(
        FileNotFoundError,
        match=r"File does not exists. Current path: ./not_existing_file",
    ):
        TopologyFileValidation("./not_existing_file")


@allure.title("Pfad zu Directory angeben")
@allure.description(
    "Überprüft, ob TopologyFileValidation() erkennt, ob der Pfad nicht auf eine Datei zeigt."
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_002() -> None:
    with pytest.raises(
        ValueError,
        match=r"Path does not link to \*\.yaml or \*\.yml file\. Current path: .*",
    ):
        TopologyFileValidation("./tests")


@allure.title("Richtiges Format validieren")
@allure.description(
    "Überprüft, ob TopologyFileValidation.validate_file() die richtige Configurations Datei richtig validiert"
)
@allure.tag("user-input", "positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_003() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()


@allure.title("'nodes' key fehlt")
@allure.description(
    "Überprüft, ob TopologyFileValidation.validate_file() erkennt, ob der Dictionary Key 'nodes' fehlt"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_004() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_004.yml"))
    with pytest.raises(
        KeyError,
        match=r"Key .+ or .+ not found in configuration file. Current keys: .+",
    ):
        c.validate_file()


@allure.title("'edges' key fehlt")
@allure.description(
    "Überprüft, ob TopologyFileValidation.validate_file() erkennt, ob der Dictionary Key 'edges' fehlt"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_005() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_005.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_006.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_007.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_008.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_009.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_010.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_011.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_012.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_013.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_014.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_015.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_016.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_017.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_018.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_019.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_020.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_021.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_022.yml"))
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
    c = TopologyFileValidation(add_folder_path("config_file_023.yml"))
    c.validate_file()


@allure.title("edge node name typ ist falsch")
@allure.description(
    "Testet ob erkannt wird, ob in edge, die node namen nicht den richtigen typ haben"
)
@allure.tag("user-input", "negativ-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_024() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_024.yml"))
    with pytest.raises(
        ValueError,
        match=r"Contents of .edge. must be of type str: ",
    ):
        c.validate_file()


@allure.title("Doppelte node_groups vorhanden")
@allure.description(
    "Testet ob es funktioniert, dass man zwei gleiche Node Groups in der file angibt, mit verschiedenen Namen"
)
@allure.tag("user-input", "positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.MINOR)
def conf_file_025() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_025.yml"))
    c.validate_file()


@allure.title("add_node fügt zu bestehender Node-Group mit gleicher Rolle und Image hinzu")
@allure.description(
    "Überprüft, dass add_node() einen neuen Namen an eine bestehende "
    "Node-Group anhängt, wenn Rolle und Image exakt übereinstimmen, "
    "statt eine neue Gruppe anzulegen"
)
@allure.tag("positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_026() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()
    group_count_before = len(c.nodes)

    c.add_node("PC99", "PC", "VPCS")

    assert len(c.nodes) == group_count_before
    pc_group = next(g for g in c.nodes if g["role"] == "PC" and g["image"] == "VPCS")
    assert "PC99" in pc_group["names"]


@allure.title("add_node legt eine neue Node-Group an, wenn keine passende existiert")
@allure.description(
    "Überprüft, dass add_node() eine neue {names, role, image}-Gruppe "
    "anlegt, wenn keine bestehende Gruppe Rolle und Image exakt trifft"
)
@allure.tag("positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_027() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()
    group_count_before = len(c.nodes)

    c.add_node("NEW-VM", "VM", "pfSense")

    assert len(c.nodes) == group_count_before + 1
    new_group = next(g for g in c.nodes if "NEW-VM" in g["names"])
    assert new_group == {"names": ["NEW-VM"], "role": "VM", "image": "pfSense"}


@allure.title("remove_node entfernt den Namen, die leere Gruppe und referenzierende Edges")
@allure.description(
    "Überprüft, dass remove_node() den Namen aus seiner Gruppe entfernt, "
    "die Gruppe komplett fallen lässt, wenn sie dadurch leer wird, und "
    "jede Edge entfernt, die den Namen auf irgendeiner Seite referenziert"
)
@allure.tag("positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_028() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()
    assert any(e[0] == "PC4" or e[2] == "PC4" for e in c.edges)

    c.remove_node("PC4")

    assert not any("PC4" in g["names"] for g in c.nodes)
    assert not any(g["role"] == "VM" and g["image"] == "Ubuntu-Server" for g in c.nodes)
    assert not any(e[0] == "PC4" or e[2] == "PC4" for e in c.edges)


@allure.title("remove_node lässt die Gruppe bestehen, wenn noch andere Namen übrig sind")
@allure.description(
    "Überprüft, dass remove_node() eine Node-Group nicht fallen lässt, "
    "solange nach dem Entfernen noch mindestens ein anderer Name übrig ist"
)
@allure.tag("positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.NORMAL)
def conf_file_029() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()

    c.remove_node("PC1")

    pc_group = next(g for g in c.nodes if g["role"] == "PC" and g["image"] == "VPCS")
    assert "PC1" not in pc_group["names"]
    assert "PC2" in pc_group["names"]


@allure.title("add_edge und remove_edge fügen hinzu bzw. entfernen unabhängig von der Seite")
@allure.description(
    "Überprüft, dass add_edge() eine neue Edge anhängt, und dass "
    "remove_edge() jede Edge zwischen zwei Knoten entfernt, unabhängig "
    "davon, welcher Knoten als erster oder zweiter angegeben ist"
)
@allure.tag("positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_030() -> None:
    c = TopologyFileValidation(add_folder_path("config_file_003.yml"))
    c.validate_file()

    c.add_edge("PC1", "gi0/1", "PC2", "gi0/1")
    assert ["PC1", "gi0/1", "PC2", "gi0/1"] in c.edges

    c.remove_edge("PC2", "PC1")  # reversed order on purpose
    assert ["PC1", "gi0/1", "PC2", "gi0/1"] not in c.edges


@allure.title("save schreibt nodes/edges so, dass eine neue Validierung dieselben Daten liefert")
@allure.description(
    "Überprüft den vollen Round-Trip: add_node()/add_edge() gefolgt von "
    "save(), dann eine frische TopologyFileValidation auf derselben "
    "Datei - die neu gelesenen nodes/edges müssen inhaltlich identisch "
    "mit dem Stand vor dem Schreiben sein"
)
@allure.tag("positiv-test", "config-file")
@allure.feature("config_file")
@allure.severity(allure.severity_level.CRITICAL)
def conf_file_031(tmp_path) -> None:
    import shutil

    target = tmp_path / "topology.yaml"
    shutil.copy(add_folder_path("config_file_003.yml"), target)

    c = TopologyFileValidation(str(target))
    c.validate_file()
    c.add_node("PC99", "PC", "VPCS")
    c.add_edge("PC99", "gi0/0", "SW-C1", "gi0/9")
    c.save()

    reloaded = TopologyFileValidation(str(target))
    reloaded.validate_file()
    assert reloaded.nodes == c.nodes
    assert reloaded.edges == c.edges
    pc_group = next(g for g in reloaded.nodes if g["role"] == "PC" and g["image"] == "VPCS")
    assert "PC99" in pc_group["names"]
    assert ["PC99", "gi0/0", "SW-C1", "gi0/9"] in reloaded.edges
