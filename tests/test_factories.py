"""
Tests to validate functionality of factories.py
"""

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import allure
import pytest

from src import logger_adapter
from src.config_file_handler import ConfigFileHandler
from src.factories import (
    NodeFactory,
    Edge,
    Interface,
    Switch,
    PC,
    VM,
    Router,
    Firewall,
    GenericNode,
)

logger_adapter.LoggerAdapter.is_test_run = True
PATH = "./config_file_example.yml"


@allure.title("Rolle neu anlegen")
@allure.description("Überprüft, ob der Decorator 'register_role' neu rollen einträgt")
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_000() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()

    @NodeFactory.register_role("TEST-ROLE")
    class Cls:
        pass

    assert NodeFactory._registry["TEST-ROLE"] == Cls
    del NodeFactory._registry["TEST-ROLE"]


@allure.title("Rolle neu anlegen")
@allure.description("Überprüft, ob der Decorator 'register_role' neu rollen einträgt")
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_001() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()

    @NodeFactory.register_role("TEST-ROLE")
    class Cls1:
        pass

    with pytest.raises(
        KeyError,
        match=r"TEST-ROLE already defined for Cls1",
    ):

        @NodeFactory.register_role("TEST-ROLE")
        class Cls2:
            pass

    del NodeFactory._registry["TEST-ROLE"]


@allure.title("Rolle neu anlegen")
@allure.description("Überprüft, ob alle Nodes entsprechend der Daten erstellt werden")
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_002() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    nf = NodeFactory()

    node = nf.create_node("SWITCH-Image", "SWITCH", "Test-SWITCH")
    assert (
        node.__class__ == Switch
        and node.name == "Test-SWITCH"
        and node.image == "SWITCH-Image"
    )
    node = nf.create_node("PC-Image", "PC", "Test-PC")
    assert node.__class__ == PC and node.name == "Test-PC" and node.image == "PC-Image"
    node = nf.create_node("VM-Image", "VM", "Test-VM")
    assert node.__class__ == VM and node.name == "Test-VM" and node.image == "VM-Image"
    node = nf.create_node("ROUTER-Image", "ROUTER", "Test-ROUTER")
    assert (
        node.__class__ == Router
        and node.name == "Test-ROUTER"
        and node.image == "ROUTER-Image"
    )
    node = nf.create_node("FW-Image", "FW", "Test-FW")
    assert (
        node.__class__ == Firewall
        and node.name == "Test-FW"
        and node.image == "FW-Image"
    )


@allure.title("Unregistrierte Rolle angeben")
@allure.description(
    "Überprüft, ob ein Fehler erkannt wird, wenn eine nicht registrierte Rolle beim erstellen von einer Node angegeben wird"
)
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_003() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    nf = NodeFactory()
    with pytest.raises(
        ValueError,
        match=r"Role Test-Role registered",
    ):
        nf.create_node("Test-Image", "Test-Role", "Test-Test")


@allure.title("Edge erstellen")
@allure.description(
    "Überprüft, ob beidseitig die Edge mit den Interfaces verbunden wird, und alle Felder gesetzt sind"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_004() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    nf = NodeFactory()
    nodes = {}
    nodes["PC"] = nf.create_node("PC-Image", "PC", "PC")
    nodes["SWITCH"] = nf.create_node("SWITCH-Image", "SWITCH", "SWITCH")

    edge: Edge = NodeFactory.create_edge(
        nodes["PC"].add_interface("ens160"), nodes["SWITCH"].add_interface("gi0/0")
    )

    assert list(nodes["PC"].interfaces) == ["ens160"]
    assert list(nodes["SWITCH"].interfaces) == ["gi0/0"]
    intf_1: Interface = nodes["PC"].interfaces["ens160"]
    intf_2: Interface = nodes["SWITCH"].interfaces["gi0/0"]
    assert intf_1.name == "ens160"
    assert intf_2.name == "gi0/0"

    assert intf_1.node == nodes["PC"]
    assert intf_2.node == nodes["SWITCH"]

    assert intf_1.edge == edge
    assert intf_2.edge == edge

    assert edge.incidence_1 == intf_1
    assert edge.incidence_2 == intf_2


@allure.title("Interface Klass testen")
@allure.description(
    "Überprüft, ob man ein Interface entsprechend der Angaben erstellen kann und ob die Properties das richtige zurückgeben"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_005() -> None:
    nf = NodeFactory()
    node = nf.create_node("PC-Image", "PC", "PC")
    intf = Interface("gi0/0", node)

    assert intf.name == "gi0/0"
    assert intf.node == node
    assert intf.edge is None
    assert str(intf) == "gi0/0"
    cp = eval(repr(intf))
    assert cp.name == intf.name and cp.node.image == intf.node.image


@allure.title("Edge Klasse testen")
@allure.description(
    "Überprüft, ob man eine Edge entsprechend der Angaben erstellen kann"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_006() -> None:
    nf = NodeFactory()
    node = nf.create_node("PC-Image", "PC", "PC")
    intf_1 = Interface("gi0/0", node)
    intf_2 = Interface("gi0/1", node)
    edge = Edge(intf_1, intf_2)
    assert edge.incidence_1 == intf_1 and edge.incidence_2 == intf_2
    assert str(edge) == "PC <--> PC"
    cp = eval(repr(edge))
    assert cp.incidence_1.name == intf_1.name and cp.incidence_2.name == intf_2.name


@allure.title("Edge mit identischen Interfaces")
@allure.description(
    "Überprüft, ob man einer Edge zwei identische Interfaces hinzufügen kann (selbes objekt)"
)
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_007() -> None:
    nf = NodeFactory()
    node = nf.create_node("PC-Image", "PC", "PC")
    intf_1 = Interface("gi0/0", node)
    with pytest.raises(
        ValueError,
        match=r"Cannot create Edge with identical Interfaces",
    ):
        Edge(intf_1, intf_1)


@allure.title("GenericNode Klasse testen")
@allure.description(
    "Überprüft, ob man eine Node anlegen kann, und deren Properties nutzen kann"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_008() -> None:
    node = GenericNode("IMAGE", "PC")
    assert node.name == "PC" and node.image == "IMAGE"
    assert node.interfaces == {}
    assert repr(node) == "GenericNode('IMAGE', 'PC')"
    assert str(node) == "PC"


@allure.title("Interfaces zu Node hinzufügen")
@allure.description(
    "Überprüft, ob mehrere Interfaces an einer Node angelegt werden können"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_009() -> None:
    node = GenericNode("IMAGE", "PC")
    node.add_interface("gi0/0")
    node.add_interface("gi0/1")
    node.add_interface("gi0/2")
    node.add_interface("gi0/3")


@allure.title("Doppelte Interfaces zu Node hinzufügen")
@allure.description("Überprüft, ob erkannt wird, ob das Interface schon vorhanden ist")
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_010() -> None:
    node = GenericNode("IMAGE", "PC")
    node.add_interface("gi0/0")
    with pytest.raises(
        ValueError,
        match=r"Interface gi0/0 already exists on node PC",
    ):
        node.add_interface("gi0/0")


@allure.title("Nachbarn von Node bekommen")
@allure.description(
    "Überprüft, ob man den richtigen Nachbarn vom angegebenen Interface bekommt"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_011() -> None:
    node_1 = GenericNode("IMAGE", "PC1")
    node_2 = GenericNode("IMAGE", "PC2")

    NodeFactory.create_edge(
        node_1.add_interface("gi0/0"), node_2.add_interface("gi0/0")
    )
    assert node_1.get_neighbour("gi0/0") is node_2
    assert node_2.get_neighbour("gi0/0") is node_1
