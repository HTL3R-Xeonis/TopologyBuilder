"""
Tests to validate functionality of gns3_vm_interface_setup.py
"""

__license__ = "GNU GPLv3"

from pathlib import Path
from unittest.mock import MagicMock

import allure
import pytest

from src import logger_adapter
from src.factories import GenericNode, NodeFactory
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup

logger_adapter.LoggerAdapter.is_test_run = True


def _exec_result(exit_status: int, stdout_lines: list[str] | None = None):
    stdout = MagicMock()
    stdout.channel.recv_exit_status.return_value = exit_status
    stdout.readlines.return_value = [f"{line}\n" for line in (stdout_lines or [])]
    stderr = MagicMock()
    stderr.read.return_value = b""
    return (MagicMock(), stdout, stderr)


def _make_setup(command_responses: dict) -> GNS3VMInterfaceSetup:
    """
    :param command_responses: maps a command (or command prefix) to the
        (exit_status, stdout_lines) to fake for it - matched by 'in' against
        the actual command string, so a short distinguishing substring works.
    """
    connection = MagicMock()
    connection.ip_address = "10.20.20.231"

    def exec_command(command: str):
        for key, (exit_status, stdout_lines) in command_responses.items():
            if key in command:
                return _exec_result(exit_status, stdout_lines)
        raise AssertionError(f"Unexpected command: {command}")

    connection.exec_command.side_effect = exec_command
    return GNS3VMInterfaceSetup(connection)


@allure.title("Vorhandenes Interface wird akzeptiert")
@allure.description(
    "Überprüft, dass _verify_interface_exists keinen Fehler wirft, wenn das "
    "angegebene Interface auf der GNS3 VM existiert"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_000() -> None:
    setup = _make_setup({"ip -br link show eth1": (0, [])})
    setup._verify_interface_exists("eth1")


@allure.title("Fehlendes Interface listet die tatsächlich vorhandenen auf")
@allure.description(
    "Überprüft, dass _verify_interface_exists einen ValueError wirft, der "
    "die tatsächlich auf der GNS3 VM vorhandenen Interfaces auflistet "
    "(ohne 'lo'), wenn das angegebene Interface (z.B. das hart codierte "
    "'eth1') nicht existiert - z.B. weil eine per --fresh-gns3-vm "
    "importierte VM ihre Trunk-NIC anders benennt"
)
@allure.tag("negativ-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_001() -> None:
    setup = _make_setup(
        {
            "ip -br link show eth1": (1, []),
            # 'lo' is already excluded by the real command's own
            # "grep -v '^lo$'", so the fake response doesn't include it.
            "ip -br link show | awk": (0, ["eth0", "ens224"]),
        }
    )
    with pytest.raises(
        ValueError,
        match=r"GNS3 VM has no interface named 'eth1'.*\['eth0', 'ens224'\]",
    ):
        setup._verify_interface_exists("eth1")


@allure.title("write_config_file prüft, löscht alte und erstellt neue Subinterfaces")
@allure.description(
    "Überprüft, dass write_config_file zuerst das Trunk-Interface prüft, "
    "dann bestehende VLAN-Subinterfaces auf diesem Interface löscht und "
    "anschließend für jede zugewiesene VLAN eine neue Subinterface anlegt "
    "und hochfährt"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_002(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    setup = _make_setup(
        {
            "ip -br link show eth1": (0, []),
            "ip -br link show type vlan": (0, ["stale_vlan"]),
            "ip link delete stale_vlan": (0, []),
            "ip link add link eth1": (0, []),
            "ip link set": (0, []),
        }
    )

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}

    setup.write_config_file(nodes, trunk_interface="eth1")

    commands = [
        call.args[0] for call in setup.gns3_connection.exec_command.call_args_list
    ]
    assert any("ip link delete stale_vlan" in c for c in commands)
    assert any(
        f"ip link add link eth1 name {vm.interfaces['ens160'].esxi_vlan} type vlan id 2"
        in c
        for c in commands
    )
    assert any(
        f"ip link set {vm.interfaces['ens160'].esxi_vlan} up" in c for c in commands
    )


@allure.title("write_config_file bricht bei fehlendem Trunk-Interface sofort ab")
@allure.description(
    "Überprüft, dass write_config_file abbricht, bevor irgendein 'ip link "
    "add'-Befehl versucht wird, wenn das angegebene Trunk-Interface nicht "
    "existiert - statt erst mittendrin mit einer kryptischen Fehlermeldung "
    "zu scheitern"
)
@allure.tag("negativ-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_003(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    setup = _make_setup(
        {
            "ip -br link show eth1": (1, []),
            "ip -br link show | awk": (0, ["lo", "eth0"]),
        }
    )

    with pytest.raises(ValueError, match=r"GNS3 VM has no interface named 'eth1'"):
        setup.write_config_file({}, trunk_interface="eth1")

    # Both calls belong to _verify_interface_exists itself (existence check,
    # then listing available interfaces for the error) - nothing from
    # _reset_subinterfaces_commands/_create_subinterfaces_commands, which
    # never ran.
    assert setup.gns3_connection.exec_command.call_count == 2


@allure.title("Trunk-Interface wird automatisch erkannt")
@allure.description(
    "Überprüft, dass _detect_trunk_interface das Management-Interface (das "
    "die IP der SSH-Verbindung trägt) und virtuelle Interfaces ausschließt "
    "und das einzig verbleibende Interface als Trunk-NIC erkennt"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_004() -> None:
    setup = _make_setup(
        {
            "ip -br addr show": (
                0,
                [
                    "lo               UNKNOWN        127.0.0.1/8",
                    "eth0             UP             10.20.20.231/24",
                    "eth1             UP             10.20.20.240/24",
                ],
            ),
            "ip -br link show": (
                0,
                ["lo", "eth0", "eth1", "docker0", "virbr0"],
            ),
        }
    )
    assert setup._detect_trunk_interface() == "eth1"


@allure.title("Mehrdeutige Trunk-Interface-Erkennung wirft Fehler")
@allure.description(
    "Überprüft, dass _detect_trunk_interface einen ValueError wirft, statt "
    "zu raten, wenn nach Ausschluss des Management-Interfaces und "
    "virtueller Interfaces mehr als ein Kandidat übrig bleibt"
)
@allure.tag("negativ-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_005() -> None:
    setup = _make_setup(
        {
            "ip -br addr show": (
                0,
                ["eth0             UP             10.20.20.231/24"],
            ),
            "ip -br link show": (0, ["lo", "eth0", "eth1", "eth2"]),
        }
    )
    with pytest.raises(
        ValueError,
        match=r"Could not auto-detect.*management interface: 'eth0'.*\['eth1', 'eth2'\]",
    ):
        setup._detect_trunk_interface()


@allure.title("_get_subinterfaces liefert bereinigte Liste zurück")
@allure.description(
    "Überprüft, dass _get_subinterfaces die Ausgabe des ip-Befehls in eine "
    "Liste von Subinterface-Namen ohne Zeilenumbrüche umwandelt"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_007() -> None:
    setup = _make_setup(
        {
            "ip -br link show type vlan | grep @eth1": (
                0,
                ["PC4_gi0-0", "PC5_gi0-0"],
            ),
        }
    )
    assert setup._get_subinterfaces("eth1") == ["PC4_gi0-0", "PC5_gi0-0"]


@allure.title("_get_subinterfaces liefert leere Liste ohne Subinterfaces")
@allure.description(
    "Überprüft, dass _get_subinterfaces eine leere Liste zurückgibt, wenn "
    "das Interface keine VLAN-Subinterfaces hat"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_008() -> None:
    setup = _make_setup(
        {"ip -br link show type vlan | grep @eth1": (0, [])},
    )
    assert setup._get_subinterfaces("eth1") == []


@allure.title("_write_command hängt Befehl an die Konfigurationsdatei an")
@allure.description(
    "Überprüft, dass _write_command den gegebenen Befehl als neue Zeile an "
    "die bestehende Konfigurationsdatei anhängt, ohne vorhandene Zeilen zu "
    "überschreiben"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_009(tmp_path: Path) -> None:
    setup = _make_setup({})
    setup.configuration_file_path = tmp_path / "config.txt"
    setup.configuration_file_path.write_text("# existing\n")

    setup._write_command("ip link set eth1 up")

    assert (
        setup.configuration_file_path.read_text() == "# existing\nip link set eth1 up\n"
    )


@allure.title(
    "_write_command loggt einen Alert, wenn die Datei fehlt, schreibt aber trotzdem"
)
@allure.description(
    "Überprüft, dass _write_command einen FileNotFoundError-Alert loggt, "
    "wenn die Konfigurationsdatei noch nicht existiert, den Befehl aber "
    "trotzdem schreibt, da 'a'-Modus die Datei implizit anlegt - das Logging "
    "ist hier reine Diagnose, kein Abbruch"
)
@allure.tag("negativ-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_010(tmp_path: Path) -> None:
    setup = _make_setup({})
    setup.configuration_file_path = tmp_path / "does_not_exist_yet" / "config.txt"
    setup.configuration_file_path.parent.mkdir(parents=True)

    setup._write_command("ip link set eth1 up")

    assert setup.configuration_file_path.read_text() == "ip link set eth1 up\n"


@allure.title(
    "_apply_command führt den Befehl mit sudo -n aus und schreibt ihn in die Audit-Datei"
)
@allure.description(
    "Überprüft, dass _apply_command den Befehl per SSH mit 'sudo -n' "
    "voranstellt ausführt und ihn zuvor über _write_command protokolliert"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_011(tmp_path: Path) -> None:
    setup = _make_setup({"sudo -n ip link set eth1 up": (0, [])})
    setup.configuration_file_path = tmp_path / "config.txt"
    setup.configuration_file_path.write_text("")

    setup._apply_command("ip link set eth1 up")

    commands = [
        call.args[0] for call in setup.gns3_connection.exec_command.call_args_list
    ]
    assert commands == ["sudo -n ip link set eth1 up"]
    assert setup.configuration_file_path.read_text() == "ip link set eth1 up\n"


@allure.title("_apply_command wirft RuntimeError bei nicht-null Exit-Code")
@allure.description(
    "Überprüft, dass _apply_command einen RuntimeError mit Exit-Code und "
    "stderr-Inhalt wirft, wenn der Befehl auf der GNS3 VM fehlschlägt"
)
@allure.tag("negativ-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_012(tmp_path: Path) -> None:
    connection = MagicMock()
    connection.ip_address = "10.20.20.231"
    stdout = MagicMock()
    stdout.channel.recv_exit_status.return_value = 1
    stderr = MagicMock()
    stderr.read.return_value = b'Cannot find device "eth1"'
    connection.exec_command.side_effect = lambda command: (
        MagicMock(),
        stdout,
        stderr,
    )
    setup = GNS3VMInterfaceSetup(connection)
    setup.configuration_file_path = tmp_path / "config.txt"
    setup.configuration_file_path.write_text("")

    with pytest.raises(RuntimeError) as exc_info:
        setup._apply_command("ip link add link eth1 name PC4_gi0-0 type vlan id 2")
    assert "Command failed on GNS3 VM (exit 1)" in str(exc_info.value)
    assert "Cannot find device" in str(exc_info.value)


@allure.title("_reset_subinterfaces_commands löscht jede gefundene Subinterface")
@allure.description(
    "Überprüft, dass _reset_subinterfaces_commands für jede von "
    "_get_subinterfaces gemeldete Subinterface einen 'ip link delete'-Befehl "
    "anwendet, auch bei mehreren vorhandenen Subinterfaces"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_013(tmp_path: Path) -> None:
    setup = _make_setup(
        {
            "ip -br link show type vlan | grep @eth1": (
                0,
                ["PC4_gi0-0", "PC5_gi0-0"],
            ),
            "ip link delete PC4_gi0-0": (0, []),
            "ip link delete PC5_gi0-0": (0, []),
        }
    )
    setup.configuration_file_path = tmp_path / "config.txt"
    setup.configuration_file_path.write_text("")

    setup._reset_subinterfaces_commands("eth1")

    commands = [
        call.args[0] for call in setup.gns3_connection.exec_command.call_args_list
    ]
    assert "sudo -n ip link delete PC4_gi0-0" in commands
    assert "sudo -n ip link delete PC5_gi0-0" in commands


@allure.title("_reset_subinterfaces_commands tut nichts ohne vorhandene Subinterfaces")
@allure.description(
    "Überprüft, dass _reset_subinterfaces_commands keinen Befehl anwendet, "
    "wenn das Interface keine bestehenden VLAN-Subinterfaces hat"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.NORMAL)
def gns3_vm_interface_setup_014(tmp_path: Path) -> None:
    setup = _make_setup({"ip -br link show type vlan | grep @eth1": (0, [])})
    setup.configuration_file_path = tmp_path / "config.txt"
    setup.configuration_file_path.write_text("")

    setup._reset_subinterfaces_commands("eth1")

    assert setup.gns3_connection.exec_command.call_count == 1


@allure.title(
    "_create_subinterfaces_commands legt für jede zugewiesene VLAN eine Subinterface an"
)
@allure.description(
    "Überprüft, dass _create_subinterfaces_commands für jede von "
    "compute_esxi_vlan_assignments gelieferte VLAN-Zuweisung ein 'ip link "
    "add'- und ein 'ip link set ... up'-Kommando anwendet, auch bei "
    "mehreren Nodes/Interfaces"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_015(tmp_path: Path) -> None:
    setup = _make_setup(
        {
            "ip link add link eth1": (0, []),
            "ip link set": (0, []),
        }
    )
    setup.configuration_file_path = tmp_path / "config.txt"
    setup.configuration_file_path.write_text("")

    nf = NodeFactory()
    vm1: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm1.add_interface("ens160")
    vm2: GenericNode = nf.create_node("Rocky 9.2", "VM", "VM2")
    vm2.add_interface("ens160")
    nodes = {"VM1": vm1, "VM2": vm2}

    setup._create_subinterfaces_commands("eth1", nodes)

    commands = [
        call.args[0] for call in setup.gns3_connection.exec_command.call_args_list
    ]
    assert any(
        f"ip link add link eth1 name {vm1.interfaces['ens160'].esxi_vlan} type vlan id 2"
        in c
        for c in commands
    )
    assert any(
        f"ip link set {vm1.interfaces['ens160'].esxi_vlan} up" in c for c in commands
    )
    assert any(
        f"ip link add link eth1 name {vm2.interfaces['ens160'].esxi_vlan} type vlan id 3"
        in c
        for c in commands
    )
    assert any(
        f"ip link set {vm2.interfaces['ens160'].esxi_vlan} up" in c for c in commands
    )


@allure.title("write_config_file nutzt die automatische Erkennung ohne Angabe")
@allure.description(
    "Überprüft, dass write_config_file ohne angegebenes trunk_interface "
    "automatisch erkennt und die Subinterfaces auf dem erkannten Interface "
    "anlegt"
)
@allure.tag("positiv-test", "gns3_vm_interface_setup")
@allure.feature("gns3_vm_interface_setup")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_vm_interface_setup_006(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    setup = _make_setup(
        {
            "ip -br addr show": (
                0,
                [
                    "eth0             UP             10.20.20.231/24",
                    "ens224           UP             10.20.20.240/24",
                ],
            ),
            "ip -br link show type vlan": (0, []),
            "ip -br link show": (0, ["lo", "eth0", "ens224"]),
            "ip link add link ens224": (0, []),
            "ip link set": (0, []),
        }
    )

    nf = NodeFactory()
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160")
    nodes = {"VM1": vm}

    setup.write_config_file(nodes)

    commands = [
        call.args[0] for call in setup.gns3_connection.exec_command.call_args_list
    ]
    assert any(
        f"ip link add link ens224 name {vm.interfaces['ens160'].esxi_vlan}" in c
        for c in commands
    )
