__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import json
import re

import yaml
from loguru import logger

from src.connections import SSHConnection
from src.graph import Graph
from src.settings import Settings, Verbosity


class GNS3VMInterfaceSetup:
    """Manages persistent VLAN subinterfaces on the GNS3 VM."""

    NETPLAN_FILE = "/etc/netplan/95-topologybuilder-vlans.yaml"
    NETPLAN_MARKER = "# Managed by TopologyBuilder\n"

    def __init__(self, gns3_ssh_connection: SSHConnection, parent_interface: str) -> None:
        """
        Initializes the VLAN configuration.
        :param gns3_ssh_connection: SSH connection to the GNS3 VM.
        :param parent_interface: Parent network interface for VLANs.
        """
        self.gns3_ssh_connection = gns3_ssh_connection
        self.parent_interface = parent_interface
        self.vlans: dict[str, int] = {}
        self.netplan_yaml = ""

    def _run_command(self, command: str, input_data: str | None = None) -> str:
        """
        Runs a command on the GNS3 VM.
        :param command: Remote shell command.
        :param input_data: Optional text sent to the command via stdin.
        :return: Standard output of the command.
        :raises RuntimeError: If the command fails.
        """
        stdin, stdout, stderr = self.gns3_ssh_connection.connection.exec_command(command)
        if input_data is not None:
            stdin.write(input_data)
            stdin.flush()
        stdin.channel.shutdown_write()

        output = stdout.read().decode()
        errors = stderr.read().decode()
        if stdout.channel.recv_exit_status() != 0:
            logger.error(msg := f"GNS3 VM command failed: {command}")
            raise RuntimeError(f"{msg}\n{errors}")
        return output

    def _get_existing_subinterfaces(self) -> dict[str, tuple[int, bool]]:
        """
        Gets the current VLAN interfaces on the parent interface.
        :return: Interface names mapped to VLAN IDs and UP states.
        """
        devices = json.loads(self._run_command("ip -d -j link show"))
        names_by_index = {device["ifindex"]: device["ifname"].split("@")[0] for device in devices}
        existing: dict[str, tuple[int, bool]] = {}

        for device in devices:
            info = device.get("linkinfo") or {}
            if info.get("info_kind") != "vlan":
                continue
            parent = device.get("link") or device.get("link_index")
            if isinstance(parent, int):
                parent = names_by_index.get(parent)
            if parent != self.parent_interface:
                continue
            name = device["ifname"].split("@")[0]
            existing[name] = (info["info_data"]["id"], "UP" in device.get("flags", []))

        return existing

    def _create_subinterface_deletion_commands(self, existing: dict[str, tuple[int, bool]]) -> list[str]:
        """
        Identifies obsolete or incorrectly configured VLAN interfaces.
        :param existing: Current VLAN interfaces and their states.
        :return: Interface names to remove.
        """
        return sorted(name for name, (vlan_id, _) in existing.items() if self.vlans.get(name) != vlan_id)

    def _create_subinterface_creation_commands(self, graph: Graph) -> None:
        """
        Builds the Netplan configuration from the topology.
        :param graph: Topology containing the required VLANs.
        :raises ValueError: If VLAN names or IDs are invalid or conflicting.
        """
        vlans: dict[str, int] = {}
        used_ids: dict[int, str] = {}

        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None:
                    continue
                if not isinstance(vlan.name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", vlan.name):
                    raise ValueError(f"Invalid VLAN interface name: {vlan.name!r}")
                if vlan.name == self.parent_interface:
                    raise ValueError("A VLAN interface cannot be its own parent.")
                if type(vlan.id) is not int or not 1 <= vlan.id <= 4094:
                    raise ValueError(f"Invalid VLAN ID: {vlan.id!r}")
                if (vlan.name in vlans and vlans[vlan.name] != vlan.id) or (
                    vlan.id in used_ids and used_ids[vlan.id] != vlan.name
                ):
                    raise ValueError(f"Conflicting VLAN definition: {vlan.name!r} ({vlan.id})")
                vlans[vlan.name] = vlan.id
                used_ids[vlan.id] = vlan.name

        self.vlans = dict(sorted(vlans.items()))
        network: dict = {"version": 2, "renderer": "networkd"}
        if self.vlans:
            network["vlans"] = {
                name: {"id": vlan_id, "link": self.parent_interface, "dhcp4": False, "dhcp6": False, "optional": True}
                for name, vlan_id in self.vlans.items()
            }
        self.netplan_yaml = self.NETPLAN_MARKER + yaml.safe_dump({"network": network}, sort_keys=False)

    def initialize_yaml(self, graph: Graph) -> None:
        """
        Prepares the required VLAN configuration.
        :param graph: Topology containing the VLAN assignments.
        :raises ValueError: If the parent interface is invalid.
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", self.parent_interface):
            raise ValueError(f"Invalid parent interface: {self.parent_interface!r}")
        self._create_subinterface_creation_commands(graph)

        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"Dry run: {len(self.vlans)} VLAN interfaces requested; no changes applied.",
            )

    def apply_yaml(self) -> tuple[int, str, str]:
        """
        Synchronizes the Netplan file and VLAN interfaces on the GNS3 VM.
        :return: Exit code, status message and error output.
        :raises RuntimeError: If remote configuration fails.
        """
        if Settings.IS_DRY_RUN:
            return 0, "", ""
        if not self.netplan_yaml:
            raise RuntimeError("The VLAN configuration has not been initialized.")

        path = self.NETPLAN_FILE
        previous = self._run_command(f"sudo sh -c 'if [ -f {path} ]; then cat {path}; fi'")
        if previous and not previous.startswith(self.NETPLAN_MARKER):
            raise RuntimeError(f"Refusing to overwrite an unmanaged Netplan file: {path}")

        existing = self._get_existing_subinterfaces()
        obsolete = self._create_subinterface_deletion_commands(existing)
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", name) for name in obsolete):
            raise RuntimeError("An obsolete VLAN interface has an invalid name.")

        changed = previous != self.netplan_yaml
        added = [name for name in self.vlans if name not in existing]
        recreated = [name for name in obsolete if name in self.vlans]
        removed = [name for name in obsolete if name not in self.vlans]
        activated = [
            name
            for name, (vlan_id, is_up) in existing.items()
            if name in self.vlans and self.vlans[name] == vlan_id and not is_up
        ]
        missing = bool(added or recreated)
        down = bool(activated)

        if not (changed or obsolete or missing or down):
            message = f"VLAN configuration already up to date ({len(self.vlans)} interfaces)."
            Verbosity.volumatic_print(Verbosity.NORMAL, message)
            return 0, message, ""

        if missing:
            devices = json.loads(self._run_command("ip -j link show"))
            names = {device["ifname"].split("@")[0] for device in devices}
            conflicts = sorted((set(self.vlans) - set(existing)) & names)
            if conflicts:
                raise RuntimeError("Interface name already in use outside the expected VLANs: " + ", ".join(conflicts))

        if changed:
            self._run_command(f"sudo tee {path} > /dev/null", self.netplan_yaml)
            self._run_command(f"sudo chmod 600 {path}")
            self._run_command("sudo netplan generate")

        for name in obsolete:
            self._run_command(f"sudo ip link delete dev {name}")

        if changed or missing:
            self._run_command("sudo netplan apply")

        current = self._get_existing_subinterfaces()
        for name, vlan_id in self.vlans.items():
            if name not in current or current[name][0] != vlan_id:
                raise RuntimeError(f"VLAN interface {name!r} was not configured correctly.")
            if not current[name][1]:
                self._run_command(f"sudo ip link set dev {name} up")

        changes = []
        if changed:
            changes.append("Netplan YAML updated")
        if added:
            changes.append(f"{len(added)} added")
        if recreated:
            changes.append(f"{len(recreated)} recreated")
        if removed:
            changes.append(f"{len(removed)} removed")
        if activated:
            changes.append(f"{len(activated)} activated")

        message = "VLAN configuration updated: " + ", ".join(changes) + "."
        Verbosity.volumatic_print(Verbosity.NORMAL, message)
        return 0, message, ""
