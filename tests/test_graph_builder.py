"""
Tests to validate functionality of graph_builder.py
"""

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import allure

from src import logger_adapter
from src.config_file_handler import ConfigFileHandler
from src.factories import PC, VM, Switch, Router, Firewall
from src.graph_builder import GraphBuilder


logger_adapter.LoggerAdapter.is_test_run = True
TEST_FILE_FOLDER = "./tests/files/"
PATH = "./config_file_example.yml"


@allure.title("Nodes sind angelegt")
@allure.description("Überprüft, ob der Graph Builder jede Node anlegt")
@allure.tag("positiv-test", "graph-builder")
@allure.feature("graph-builder")
@allure.severity(allure.severity_level.CRITICAL)
def graph_builder_000() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    g = GraphBuilder(cfh.nodes, cfh.edges)
    nodes = g.build()

    assert sorted(nodes.keys()) == [
        "FW-C1-1",
        "FW-C1-2",
        "FW-C2",
        "FW-C3",
        "ISP1-BB1",
        "ISP1-BB2",
        "ISP1-BB3",
        "ISP2",
        "ISP3",
        "PC1",
        "PC2",
        "PC3",
        "PC4",
        "PC5",
        "POP-ISP1-1",
        "POP-ISP1-2",
        "SW-C1",
    ]


@allure.title("Nodes sind die richtigen Namen, Rollen und Images zugeordnet")
@allure.description(
    "Überprüft, ob der Graph Builder jeder Node die richtigen Daten zuordnet"
)
@allure.tag("positiv-test", "graph-builder")
@allure.feature("graph-builder")
@allure.severity(allure.severity_level.CRITICAL)
def graph_builder_001() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    g = GraphBuilder(cfh.nodes, cfh.edges)
    nodes = g.build()

    assert (
        (cn := nodes["PC1"]).__class__ == PC and cn.image == "VPC" and cn.name == "PC1"
    )
    assert (
        (cn := nodes["PC2"]).__class__ == PC and cn.image == "VPC" and cn.name == "PC2"
    )
    assert (
        (cn := nodes["PC3"]).__class__ == PC and cn.image == "VPC" and cn.name == "PC3"
    )

    assert (
        (cn := nodes["PC4"]).__class__ == VM
        and cn.image == "Ubuntu 22.04.4 Live Server"
        and cn.name == "PC4"
    )
    assert (
        (cn := nodes["PC5"]).__class__ == VM
        and cn.image == "Rocky Linux 8.10"
        and cn.name == "PC5"
    )

    assert (
        (cn := nodes["SW-C1"]).__class__ == Switch
        and cn.image == "Cisco IOSvL2 15.2(20200924:215240)"
        and cn.name == "SW-C1"
    )

    assert (
        (cn := nodes["POP-ISP1-1"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "POP-ISP1-1"
    )
    assert (
        (cn := nodes["POP-ISP1-2"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "POP-ISP1-2"
    )
    assert (
        (cn := nodes["ISP1-BB1"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "ISP1-BB1"
    )
    assert (
        (cn := nodes["ISP1-BB2"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "ISP1-BB2"
    )
    assert (
        (cn := nodes["ISP1-BB3"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "ISP1-BB3"
    )
    assert (
        (cn := nodes["ISP2"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "ISP2"
    )
    assert (
        (cn := nodes["ISP3"]).__class__ == Router
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "ISP3"
    )

    assert (
        (cn := nodes["FW-C3"]).__class__ == Firewall
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "FW-C3"
    )
    assert (
        (cn := nodes["FW-C2"]).__class__ == Firewall
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "FW-C2"
    )
    assert (
        (cn := nodes["FW-C1-1"]).__class__ == Firewall
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "FW-C1-1"
    )
    assert (
        (cn := nodes["FW-C1-2"]).__class__ == Firewall
        and cn.image == "Cisco IOSv 15.7(3)M3"
        and cn.name == "FW-C1-2"
    )


@allure.title("Interface den Nodes zugeordnet")
@allure.description(
    "Überprüft, ob der Graph Builder jeder Node die richtigen Interfaces zuordnet"
)
@allure.tag("positiv-test", "graph-builder")
@allure.feature("graph-builder")
@allure.severity(allure.severity_level.CRITICAL)
def graph_builder_002() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    g = GraphBuilder(cfh.nodes, cfh.edges)
    nodes = g.build()

    assert sorted(nodes["PC1"].interfaces.keys()) == ["gi0/0"]
    assert sorted(nodes["PC2"].interfaces.keys()) == ["gi0/0"]
    assert sorted(nodes["PC3"].interfaces.keys()) == ["gi0/0"]

    assert sorted(nodes["PC4"].interfaces.keys()) == ["gi0/0"]
    assert sorted(nodes["PC5"].interfaces.keys()) == ["gi0/0"]

    assert sorted(nodes["SW-C1"].interfaces.keys()) == [
        "gi0/0",
        "gi0/1",
        "gi0/2",
        "gi0/3",
    ]

    assert sorted(nodes["POP-ISP1-1"].interfaces.keys()) == [
        "gi0/0",
        "gi0/1",
        "gi0/2",
        "gi0/3",
    ]
    assert sorted(nodes["POP-ISP1-2"].interfaces.keys()) == [
        "gi0/0",
        "gi0/1",
        "gi0/2",
        "gi0/3",
    ]
    assert sorted(nodes["ISP1-BB1"].interfaces.keys()) == ["gi0/0", "gi0/2"]
    assert sorted(nodes["ISP1-BB2"].interfaces.keys()) == ["gi0/0", "gi0/1"]
    assert sorted(nodes["ISP1-BB3"].interfaces.keys()) == ["gi0/0", "gi0/1"]
    assert sorted(nodes["ISP2"].interfaces.keys()) == ["gi0/0", "gi0/1", "gi0/2"]
    assert sorted(nodes["ISP3"].interfaces.keys()) == ["gi0/0", "gi0/1"]

    assert sorted(nodes["FW-C3"].interfaces.keys()) == ["gi0/0", "gi0/1"]
    assert sorted(nodes["FW-C2"].interfaces.keys()) == ["gi0/0", "gi0/2"]
    assert sorted(nodes["FW-C1-1"].interfaces.keys()) == ["gi0/0", "gi0/1"]
    assert sorted(nodes["FW-C1-2"].interfaces.keys()) == ["gi0/0", "gi0/1"]


@allure.title("Node Nachbarn überprüfen")
@allure.description(
    "Überprüft, ob der Graph Builder jede Node mit jeder Anderen richtig verbindet"
)
@allure.tag("positiv-test", "graph-builder")
@allure.feature("graph-builder")
@allure.severity(allure.severity_level.CRITICAL)
def graph_builder_003() -> None:
    cfh = ConfigFileHandler(PATH)
    cfh.validate_file()
    g = GraphBuilder(cfh.nodes, cfh.edges)
    nodes = g.build()

    assert nodes["PC1"].get_neighbour("gi0/0") == nodes["SW-C1"]
    assert nodes["PC2"].get_neighbour("gi0/0") == nodes["SW-C1"]
    assert nodes["PC3"].get_neighbour("gi0/0") == nodes["FW-C2"]
    assert nodes["PC4"].get_neighbour("gi0/0") == nodes["FW-C3"]
    assert nodes["PC5"].get_neighbour("gi0/0") == nodes["POP-ISP1-2"]

    assert nodes["SW-C1"].get_neighbour("gi0/0") == nodes["FW-C1-1"]
    assert nodes["SW-C1"].get_neighbour("gi0/1") == nodes["FW-C1-2"]
    assert nodes["SW-C1"].get_neighbour("gi0/2") == nodes["PC1"]
    assert nodes["SW-C1"].get_neighbour("gi0/3") == nodes["PC2"]

    assert nodes["POP-ISP1-1"].get_neighbour("gi0/0") == nodes["FW-C1-2"]
    assert nodes["POP-ISP1-1"].get_neighbour("gi0/1") == nodes["FW-C1-1"]
    assert nodes["POP-ISP1-1"].get_neighbour("gi0/2") == nodes["ISP1-BB1"]
    assert nodes["POP-ISP1-1"].get_neighbour("gi0/3") == nodes["ISP2"]

    assert nodes["POP-ISP1-2"].get_neighbour("gi0/0") == nodes["ISP1-BB3"]
    assert nodes["POP-ISP1-2"].get_neighbour("gi0/1") == nodes["ISP3"]
    assert nodes["POP-ISP1-2"].get_neighbour("gi0/2") == nodes["ISP2"]
    assert nodes["POP-ISP1-2"].get_neighbour("gi0/3") == nodes["PC5"]

    assert nodes["ISP1-BB1"].get_neighbour("gi0/0") == nodes["ISP1-BB2"]
    assert nodes["ISP1-BB1"].get_neighbour("gi0/2") == nodes["POP-ISP1-1"]

    assert nodes["ISP1-BB2"].get_neighbour("gi0/0") == nodes["ISP1-BB1"]
    assert nodes["ISP1-BB2"].get_neighbour("gi0/1") == nodes["ISP1-BB3"]

    assert nodes["ISP1-BB3"].get_neighbour("gi0/0") == nodes["POP-ISP1-2"]
    assert nodes["ISP1-BB3"].get_neighbour("gi0/1") == nodes["ISP1-BB2"]

    assert nodes["ISP2"].get_neighbour("gi0/0") == nodes["POP-ISP1-2"]
    assert nodes["ISP2"].get_neighbour("gi0/1") == nodes["POP-ISP1-1"]
    assert nodes["ISP2"].get_neighbour("gi0/2") == nodes["FW-C2"]

    assert nodes["ISP3"].get_neighbour("gi0/0") == nodes["POP-ISP1-2"]
    assert nodes["ISP3"].get_neighbour("gi0/1") == nodes["FW-C3"]

    assert nodes["FW-C3"].get_neighbour("gi0/0") == nodes["PC4"]
    assert nodes["FW-C3"].get_neighbour("gi0/1") == nodes["ISP3"]

    assert nodes["FW-C2"].get_neighbour("gi0/0") == nodes["PC3"]
    assert nodes["FW-C2"].get_neighbour("gi0/2") == nodes["ISP2"]

    assert nodes["FW-C1-1"].get_neighbour("gi0/0") == nodes["SW-C1"]
    assert nodes["FW-C1-1"].get_neighbour("gi0/1") == nodes["POP-ISP1-1"]

    assert nodes["FW-C1-2"].get_neighbour("gi0/0") == nodes["POP-ISP1-1"]
    assert nodes["FW-C1-2"].get_neighbour("gi0/1") == nodes["SW-C1"]
