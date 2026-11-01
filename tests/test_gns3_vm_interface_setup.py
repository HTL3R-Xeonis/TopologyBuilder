"""
Tests to validate functionality of src/vm_orchestrator/gns3_vm_interface_setup.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock

import allure

from src.graph.blocks.generic_node import GenericNode
from src.graph.blocks.vlan import VirtualLan
from src.settings import Settings
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup


def _reset_settings() -> None:
    Settings.IS_DRY_RUN = False
    Settings.API.LITERAL_API_VALUES = True


@allure.title(
    "_create_subinterface_creation_commands dedupliziert geteilte VLAN-Objekte"
)
@allure.description(
    "Überprüft, dass _create_subinterface_creation_commands nur ein "
    "'ip link add' pro eindeutiger VLAN-ID erzeugt - ein direkter "
    "ESXi-zu-ESXi-Link teilt sich dasselbe VirtualLan-Objekt zwischen "
    "beiden Interfaces (siehe Graph._assign_vlans), und ohne diese "
    "Deduplizierung würde der zweite 'ip link add' mit demselben Namen "
    "fehlschlagen und wegen 'set -e' das gesamte restliche Skript abbrechen"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_000() -> None:
    _reset_settings()

    node_a = GenericNode("Ubuntu-Server", "VM", "VM_A")
    interface_a = node_a.add_interface("ens160")
    shared_vlan = VirtualLan("VM_A", "ens160")
    interface_a.vlan = shared_vlan

    node_b = GenericNode("Ubuntu-Server", "VM", "VM_B")
    interface_b = node_b.add_interface("ens160")
    interface_b.vlan = shared_vlan

    graph = MagicMock()
    graph.nodes = {"VM_A": node_a, "VM_B": node_b}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert setup.script.count(f"name {shared_vlan.subinterface_name} type vlan") == 1


@allure.title(
    "_create_subinterface_creation_commands erzeugt einen Befehl pro eigener VLAN-ID"
)
@allure.description(
    "Überprüft, dass zwei Interfaces mit unterschiedlichen VirtualLan-"
    "Objekten (kein geteilter direkter ESXi-ESXi-Link) jeweils ihren "
    "eigenen 'ip link add'-Befehl bekommen"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_001() -> None:
    _reset_settings()
    VirtualLan.reset()

    node_a = GenericNode("Ubuntu-Server", "VM", "PC4")
    interface_a = node_a.add_interface("gi0/0")
    interface_a.vlan = VirtualLan("PC4", "gi0/0")

    node_b = GenericNode("Ubuntu-Server", "VM", "PC5")
    interface_b = node_b.add_interface("gi0/0")
    interface_b.vlan = VirtualLan("PC5", "gi0/0")

    graph = MagicMock()
    graph.nodes = {"PC4": node_a, "PC5": node_b}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert setup.script.count("type vlan") == 2
    assert f"name {interface_a.vlan.subinterface_name} type vlan" in setup.script
    assert f"name {interface_b.vlan.subinterface_name} type vlan" in setup.script


@allure.title("_create_subinterface_creation_commands überspringt Interfaces ohne VLAN")
@allure.description(
    "Überprüft, dass ein Interface ohne zugewiesenes VLAN (z.B. ein rein "
    "GNS3-gehostetes Node) keinen 'ip link add'-Befehl erzeugt"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_002() -> None:
    _reset_settings()

    node = GenericNode("VPCS", "PC", "PC1")
    node.add_interface("Ethernet0")

    graph = MagicMock()
    graph.nodes = {"PC1": node}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert "type vlan" not in setup.script


@allure.title(
    "_create_subinterface_creation_commands erzeugt gar keinen Befehl für einen direkten ESXi-ESXi-Link"
)
@allure.description(
    "Überprüft, dass ein direkter ESXi-zu-ESXi-Link (beide Interfaces via "
    "connect_to auf den jeweils anderen Node verweisend, beide Nodes mit "
    "einem ESXi-Image) überhaupt kein 'ip link add' erzeugt - die VLAN "
    "existiert rein an der ESXi-Seite, es gibt nichts, das über die GNS3-VM "
    "geroutet werden müsste"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_003() -> None:
    _reset_settings()

    node_a = GenericNode("Ubuntu-Server", "VM", "VM_A")
    interface_a = node_a.add_interface("ens160")
    shared_vlan = VirtualLan("VM_A", "ens160")
    interface_a.vlan = shared_vlan

    node_b = GenericNode("Ubuntu-Server", "VM", "VM_B")
    interface_b = node_b.add_interface("ens160")
    interface_b.vlan = shared_vlan

    interface_a.connect_to(node_b)
    interface_b.connect_to(node_a)

    graph = MagicMock()
    graph.nodes = {"VM_A": node_a, "VM_B": node_b}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert "type vlan" not in setup.script


@allure.title(
    "_create_subinterface_creation_commands bleibt unter dem Linux-ifname-Limit"
)
@allure.description(
    "Überprüft, dass ein langer Node-/Interface-Name (z.B. 'SERVER-VM1' + "
    "'gi0/1', zusammen 16 Zeichen als 'SERVER-VM1_gi0-1' - länger als "
    "Linux' 15-Zeichen-IFNAMSIZ-Limit) keinen zu langen Subinterface-Namen "
    "erzeugt. Reale 'ip link add' schlug live mit 'not a valid ifname' "
    "fehl, bevor VirtualLan.subinterface_name eingeführt wurde"
)
@allure.tag("negativ-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_004() -> None:
    _reset_settings()
    VirtualLan.reset()

    node = GenericNode("Ubuntu-Server", "VM", "SERVER-VM1")
    interface = node.add_interface("gi0/1")
    vlan = VirtualLan("SERVER-VM1", "gi0/1")
    interface.vlan = vlan

    assert len(vlan.name) > 15, "test setup should reproduce a too-long name"
    assert len(vlan.subinterface_name) <= 15

    graph = MagicMock()
    graph.nodes = {"SERVER-VM1": node}

    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._create_subinterface_creation_commands(graph)

    assert f"name {vlan.subinterface_name} type vlan" in setup.script
    assert vlan.name not in setup.script


def _graph_with_two_gns3_bridges():
    VirtualLan.reset()
    node_a = GenericNode("Ubuntu-Server", "VM", "PC_A")
    node_a.add_interface("ens160").vlan = VirtualLan("PC_A", "ens160")
    node_b = GenericNode("Ubuntu-Server", "VM", "PC_B")
    node_b.add_interface("ens160").vlan = VirtualLan("PC_B", "ens160")
    graph = MagicMock()
    graph.nodes = {"PC_A": node_a, "PC_B": node_b}
    return graph, node_a, node_b


def _setup_with_existing(existing):
    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    setup._get_existing_subinterfaces = lambda: list(existing)
    return setup


@allure.title("missing_subinterfaces nennt nur die fehlenden Subinterfaces")
@allure.description(
    "Überprüft, dass missing_subinterfaces die vom Graphen benötigten, auf der "
    "GNS3-VM aber nicht vorhandenen Subinterfaces liefert (sie gehen bei einem "
    "Neustart der VM verloren)"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_005() -> None:
    _reset_settings()
    graph, node_a, node_b = _graph_with_two_gns3_bridges()
    name_a = node_a.interfaces["ens160"].vlan.subinterface_name
    name_b = node_b.interfaces["ens160"].vlan.subinterface_name

    assert set(_setup_with_existing([]).missing_subinterfaces(graph)) == {
        name_a,
        name_b,
    }
    assert set(_setup_with_existing([name_a]).missing_subinterfaces(graph)) == {name_b}
    assert _setup_with_existing([name_a, name_b]).missing_subinterfaces(graph) == {}


@allure.title("create_missing_subinterfaces legt nur Fehlendes an und löscht nichts")
@allure.description(
    "Überprüft, dass create_missing_subinterfaces nur die fehlenden Subinterfaces "
    "per 'ip link add' anlegt, kein 'ip link delete' ausführt und nichts tut, "
    "wenn alles vorhanden ist"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_006() -> None:
    _reset_settings()
    graph, node_a, node_b = _graph_with_two_gns3_bridges()
    name_a = node_a.interfaces["ens160"].vlan.subinterface_name
    name_b = node_b.interfaces["ens160"].vlan.subinterface_name
    scripts = []

    setup = _setup_with_existing([name_a])
    setup.execute_script = lambda: scripts.append(setup.script) or (0, "", "")

    assert setup.create_missing_subinterfaces(graph) == [name_b]
    assert f"name {name_b} type vlan" in scripts[0]
    assert f"name {name_a} type vlan" not in scripts[0]
    assert "delete" not in scripts[0]

    scripts.clear()
    complete = _setup_with_existing([name_a, name_b])
    complete.execute_script = lambda: scripts.append("ran") or (0, "", "")
    assert complete.create_missing_subinterfaces(graph) == []
    assert scripts == []


def _setup_with_remote_files(files: dict[str, tuple[int, str]]) -> GNS3VMInterfaceSetup:
    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")

    def run(command: str) -> tuple[int, str]:
        for needle, answer in files.items():
            if needle in command:
                return answer
        return 1, ""

    setup._run_remote = run
    return setup


@allure.title("Das Boot-Skript beschreibt genau die VLANs der Topologie")
@allure.description(
    "Überprüft, dass das verwaltete Boot-Skript für jedes benötigte Subinterface "
    "nur anlegt, was fehlt, nichts löscht, auf die Eltern-Schnittstelle wartet "
    "und sich bei einer anderen Topologie komplett ändert (alte VLANs verschwinden)"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_007() -> None:
    _reset_settings()
    graph, node_a, node_b = _graph_with_two_gns3_bridges()
    name_a = node_a.interfaces["ens160"].vlan.subinterface_name
    name_b = node_b.interfaces["ens160"].vlan.subinterface_name
    setup = GNS3VMInterfaceSetup(MagicMock(), "eth1")

    text = setup.persistent_script_text(graph)
    assert (
        f"ip link show {name_a} >/dev/null 2>&1 || ip link add link eth1 name {name_a} type vlan id"
        in text
    )
    assert f"name {name_b} type vlan" in text
    assert (
        "ip link show eth1" in text
        and "delete" not in text
        and text.endswith("exit $rc\n")
    )

    other = MagicMock()
    other.nodes = {"PC_A": node_a}
    assert name_b not in setup.persistent_script_text(other)


@allure.title(
    "persistent_config_problem erkennt fehlende, veraltete und nicht aktivierte Dateien"
)
@allure.description(
    "Überprüft alle Zustände der verwalteten Dateien auf der GNS3-VM: nicht "
    "installiert, Skript passt nicht zur Topologie, Dienstdatei falsch, Dienst "
    "nicht aktiviert und der Gutfall"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_008() -> None:
    _reset_settings()
    graph, _, _ = _graph_with_two_gns3_bridges()
    reference = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    script, unit = (
        reference.persistent_script_text(graph),
        reference.persistent_unit_text(),
    )
    script_path = GNS3VMInterfaceSetup.PERSISTENT_SCRIPT_PATH
    unit_path = GNS3VMInterfaceSetup.PERSISTENT_UNIT_PATH
    good = {
        script_path: (0, script),
        unit_path: (0, unit),
        "is-enabled": (0, "enabled\n"),
    }

    assert (
        _setup_with_remote_files({}).persistent_config_problem(graph) == "not installed"
    )
    assert "outdated" in _setup_with_remote_files(
        {**good, script_path: (0, "old\n")}
    ).persistent_config_problem(graph)
    assert "service file" in _setup_with_remote_files(
        {**good, unit_path: (1, "")}
    ).persistent_config_problem(graph)
    assert "not enabled" in _setup_with_remote_files(
        {**good, "is-enabled": (1, "disabled\n")}
    ).persistent_config_problem(graph)
    assert _setup_with_remote_files(good).persistent_config_problem(graph) is None


@allure.title("install_persistent_config schreibt nur bei Bedarf und startet nichts")
@allure.description(
    "Überprüft, dass install_persistent_config nichts tut, wenn die Dateien aktuell "
    "sind, sonst Skript und Dienst schreibt, daemon-reload und enable ausführt, aber "
    "weder start noch restart noch ip link delete, und dass initialize_commands "
    "(Deploy) dieselben Schreibbefehle enthält"
)
@allure.tag("positiv-test", "gns3-vm-interface-setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_009() -> None:
    _reset_settings()
    graph, _, _ = _graph_with_two_gns3_bridges()
    scripts = []

    stale = _setup_with_remote_files({})
    stale.execute_script = lambda: scripts.append(stale.script) or (0, "", "")
    assert stale.install_persistent_config(graph) is True
    written = scripts[0]
    assert "base64 -d >" in written and "systemctl daemon-reload" in written
    assert f"systemctl enable {GNS3VMInterfaceSetup.PERSISTENT_NAME}.service" in written
    assert (
        "start" not in written.replace("systemctl", "")
        and "restart" not in written
        and "delete" not in written
    )

    reference = GNS3VMInterfaceSetup(MagicMock(), "eth1")
    current = _setup_with_remote_files(
        {
            GNS3VMInterfaceSetup.PERSISTENT_SCRIPT_PATH: (
                0,
                reference.persistent_script_text(graph),
            ),
            GNS3VMInterfaceSetup.PERSISTENT_UNIT_PATH: (
                0,
                reference.persistent_unit_text(),
            ),
            "is-enabled": (0, "enabled\n"),
        }
    )
    current.execute_script = lambda: scripts.append("ran") or (0, "", "")
    scripts.clear()
    assert current.install_persistent_config(graph) is False
    assert scripts == []

    deploy = _setup_with_existing([])
    deploy.initialize_commands(graph)
    assert "base64 -d >" in deploy.script and "systemctl enable" in deploy.script
