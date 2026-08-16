"""
Tests to validate functionality of factories.py
"""

__license__ = "GNU GPLv3"

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
    Environment,
    normalize_template_name,
    compute_esxi_vlan_assignments,
    _sanitize_ifname,
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

    node = nf.create_node("VPCS", "SWITCH", "Test-SWITCH")
    assert (
        node.__class__ == Switch and node.name == "Test-SWITCH" and node.image == "VPCS"
    )
    node = nf.create_node("VPCS", "PC", "Test-PC")
    assert node.__class__ == PC and node.name == "Test-PC" and node.image == "VPCS"
    node = nf.create_node("VPCS", "VM", "Test-VM")
    assert node.__class__ == VM and node.name == "Test-VM" and node.image == "VPCS"
    node = nf.create_node("VPCS", "ROUTER", "Test-ROUTER")
    assert (
        node.__class__ == Router and node.name == "Test-ROUTER" and node.image == "VPCS"
    )
    node = nf.create_node("VPCS", "FW", "Test-FW")
    assert (
        node.__class__ == Firewall and node.name == "Test-FW" and node.image == "VPCS"
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
        nf.create_node("VPCS", "Test-Role", "Test-Test")


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
    nodes["PC"] = nf.create_node("VPCS", "PC", "PC")
    nodes["SWITCH"] = nf.create_node("VPCS", "SWITCH", "SWITCH")

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
    node = nf.create_node("VPCS", "PC", "PC")
    intf = Interface("gi0/0", node)

    assert intf.name == "gi0/0"
    assert intf.node == node
    assert intf.edge is None
    assert intf.ip is None
    assert str(intf) == "gi0/0"
    cp = eval(repr(intf))
    assert cp.name == intf.name and cp.node.image == intf.node.image


@allure.title("Interface IP-Adresse setzen")
@allure.description(
    "Überprüft, dass Interface.ip standardmäßig None ist und über den Setter "
    "gesetzt werden kann"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_024() -> None:
    node = GenericNode("VPCS", "PC")
    intf = Interface("gi0/0", node)
    assert intf.ip is None
    intf.ip = "10.0.0.1/24"
    assert intf.ip == "10.0.0.1/24"


@allure.title("Edge Klasse testen")
@allure.description(
    "Überprüft, ob man eine Edge entsprechend der Angaben erstellen kann"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_006() -> None:
    nf = NodeFactory()
    node = nf.create_node("VPCS", "PC", "PC")
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
    node = nf.create_node("VPCS", "PC", "PC")
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
    node = GenericNode("VPCS", "PC")
    assert node.name == "PC" and node.image == "VPCS"
    assert node.interfaces == {}
    assert repr(node) == "GenericNode('VPCS', 'PC')"
    assert str(node) == "PC"


@allure.title("GenericNode.env spiegelt die erkannte Umgebung des Images wider")
@allure.description(
    "Überprüft, dass GenericNode beim Anlegen self.env passend zum Image "
    "setzt - ON_GNS3 für ein GNS3-Template, ON_ESXI für ein ESXi-Template"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_022() -> None:
    gns3_node = GenericNode("VPCS", "PC")
    assert gns3_node.env == Environment.ON_GNS3

    esxi_node = GenericNode("Ubuntu-Server", "VM1")
    assert esxi_node.env == Environment.ON_ESXI


@allure.title("GenericNode lehnt ein Image ab, das auf keinem System existiert")
@allure.description(
    "Überprüft, dass GenericNode.__init__ einen ValueError wirft, statt eine "
    "Node mit env=ON_NOTHING anzulegen, wenn das Image weder als GNS3- noch "
    "als ESXi-Template bekannt ist"
)
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_023() -> None:
    with pytest.raises(
        ValueError, match=r"Image Nonexistent-Image not found on ESXi or GNS3"
    ):
        GenericNode("Nonexistent-Image", "PC")


@allure.title("Interfaces zu Node hinzufügen")
@allure.description(
    "Überprüft, ob mehrere Interfaces an einer Node angelegt werden können"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_009() -> None:
    node = GenericNode("VPCS", "PC")
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
    node = GenericNode("VPCS", "PC")
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
    node_1 = GenericNode("VPCS", "PC1")
    node_2 = GenericNode("VPCS", "PC2")

    NodeFactory.create_edge(
        node_1.add_interface("gi0/0"), node_2.add_interface("gi0/0")
    )
    assert node_1.get_neighbour("gi0/0") is node_2
    assert node_2.get_neighbour("gi0/0") is node_1


@allure.title("Template-Namen mit Leerzeichen- und Groß-/Kleinschreibungs-Unterschied")
@allure.description(
    "Überprüft, dass normalize_template_name Namen gleichsetzt, die sich nur "
    "durch Groß-/Kleinschreibung oder ob an einer Stelle überhaupt ein "
    "Leerzeichen existiert unterscheiden - reines Zusammenfassen mehrfacher "
    "Leerzeichen würde das nicht lösen"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_012() -> None:
    assert normalize_template_name("Cisco IOSv 15.6(1)T") == normalize_template_name(
        "cisco iosv 15.6(1) t"
    )


@allure.title("Template-Namen mit unterschiedlichem Inhalt bleiben unterschiedlich")
@allure.description(
    "Überprüft, dass normalize_template_name inhaltlich unterschiedliche Namen "
    "nicht fälschlich gleichsetzt"
)
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_013() -> None:
    assert normalize_template_name("Cisco IOSv 15.6(1)T") != normalize_template_name(
        "Cisco IOSvL2 15.2.1"
    )


@allure.title("Interface-Namen bis zur Maximallänge bleiben unverändert")
@allure.description(
    "Überprüft, dass _sanitize_ifname kurze, bereits gültige Namen unverändert "
    "zurückgibt und ungültige Zeichen durch '-' ersetzt"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_014() -> None:
    assert _sanitize_ifname("PC4_gi0-0") == "PC4_gi0-0"
    assert _sanitize_ifname("PC4_gi0/0") == "PC4_gi0-0"


@allure.title("Zu lange Interface-Namen werden gekürzt und bleiben eindeutig")
@allure.description(
    "Überprüft, dass _sanitize_ifname Namen über der Maximallänge kürzt und "
    "einen Hash-Suffix anhängt, sodass zwei unterschiedliche Namen, die nach "
    "einfachem Abschneiden kollidieren würden, trotzdem unterschiedlich bleiben"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_015() -> None:
    name_1 = _sanitize_ifname("Very-Long-Node-Name-A_GigabitEthernet0/0")
    name_2 = _sanitize_ifname("Very-Long-Node-Name-B_GigabitEthernet0/0")

    assert len(name_1) <= 15
    assert len(name_2) <= 15
    assert name_1 != name_2


@allure.title("VLAN-Zuweisung ist fortlaufend für unabhängige ESXi-Interfaces")
@allure.description(
    "Überprüft, dass compute_esxi_vlan_assignments unabhängigen ESXi-Interfaces "
    "fortlaufende VLAN-IDs ab 2 zuweist und GNS3-gehostete Nodes ignoriert"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_016() -> None:
    nf = NodeFactory()
    vm = nf.create_node("Ubuntu-Server", "VM", "VM1")
    router = nf.create_node("VPCS", "ROUTER", "R1")
    vm.add_interface("ens160")
    vm.add_interface("ens192")
    router.add_interface("Ethernet0")

    assignments = compute_esxi_vlan_assignments({"VM1": vm, "R1": router})

    assert assignments == {
        vm.interfaces["ens160"].esxi_vlan: 2,
        vm.interfaces["ens192"].esxi_vlan: 3,
    }


@allure.title("Direkt verbundene ESXi-Nodes teilen sich ein VLAN")
@allure.description(
    "Überprüft, dass zwei ESXi-gehostete Nodes, die direkt (ohne GNS3-Node "
    "dazwischen) verbunden sind, dieselbe VLAN-ID zugewiesen bekommen, da es "
    "keine Bridge gibt, die zwischen zwei unterschiedlichen VLANs übersetzen "
    "könnte - Regressionstest für den per-Edge-VLAN-Bug"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_017() -> None:
    nf = NodeFactory()
    vm_1 = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm_2 = nf.create_node("Rocky 9.2", "VM", "VM2")
    NodeFactory.create_edge(vm_1.add_interface("ens160"), vm_2.add_interface("ens160"))

    assignments = compute_esxi_vlan_assignments({"VM1": vm_1, "VM2": vm_2})

    assert (
        assignments[vm_1.interfaces["ens160"].esxi_vlan]
        == assignments[vm_2.interfaces["ens160"].esxi_vlan]
    )


@allure.title("Über GNS3 gebrückte ESXi-Interfaces behalten ihr eigenes VLAN")
@allure.description(
    "Überprüft, dass eine Edge zwischen einer ESXi- und einer GNS3-gehosteten "
    "Node weiterhin eine eigene VLAN-ID für das ESXi-Interface erhält, statt "
    "sich fälschlich ein VLAN mit einem anderen, direkt verbundenen ESXi-"
    "Interface zu teilen"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_018() -> None:
    nf = NodeFactory()
    vm_1 = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm_2 = nf.create_node("Rocky 9.2", "VM", "VM2")
    router = nf.create_node("VPCS", "ROUTER", "R1")
    NodeFactory.create_edge(vm_1.add_interface("ens160"), vm_2.add_interface("ens160"))
    NodeFactory.create_edge(
        vm_1.add_interface("ens192"), router.add_interface("Ethernet0")
    )

    assignments = compute_esxi_vlan_assignments(
        {"VM1": vm_1, "VM2": vm_2, "R1": router}
    )

    assert (
        assignments[vm_1.interfaces["ens192"].esxi_vlan]
        != assignments[vm_1.interfaces["ens160"].esxi_vlan]
    )


@allure.title("Environment erkennt GNS3-Templates trotz Namens-Rauschen")
@allure.description(
    "Überprüft, dass Environment.get_environment ein Image einem GNS3-Template "
    "zuordnet, auch wenn sich Groß-/Kleinschreibung oder Leerzeichen vom "
    "konfigurierten Template-Namen unterscheiden"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_019() -> None:
    assert Environment.get_environment("vpcs") == Environment.ON_GNS3


@allure.title("Environment erkennt ESXi-Templates")
@allure.description(
    "Überprüft, dass Environment.get_environment ein Image, das nur auf ESXi "
    "existiert, als ON_ESXI einstuft"
)
@allure.tag("positiv-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.CRITICAL)
def factories_020() -> None:
    assert Environment.get_environment("Ubuntu-Server") == Environment.ON_ESXI


@allure.title("Environment stuft unbekannte Images als ON_NOTHING ein")
@allure.description(
    "Überprüft, dass Environment.get_environment ON_NOTHING zurückgibt, wenn "
    "das Image auf keinem der beiden Systeme als Template existiert"
)
@allure.tag("negativ-test", "factory")
@allure.feature("factory")
@allure.severity(allure.severity_level.NORMAL)
def factories_021() -> None:
    assert Environment.get_environment("Nonexistent-Image") == Environment.ON_NOTHING
