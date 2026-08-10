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
