__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import base64
import shlex

from loguru import logger

from src.connections import SSHConnection
from src.graph import Graph
from src.settings import Settings, Verbosity


class GNS3VMInterfaceSetup:
    """
    Object to handle the interface configuration of the GNS3 VM to ensure, that only the dedicated GNS3 device can communicate with the VM on the ESXi host.
    This is done by subinterfaces with vlans on the GNS3 VM which correspond with the VLANs of the vSwitch on the ESXi host.
    """

    # The subinterfaces are plain ``ip link`` objects and vanish whenever the VM reboots. These two files
    # re-create them at boot, before GNS3 starts, so the Cloud nodes bind to them normally. They are
    # generated from the topology on every deploy (never edited by hand), so they always describe the
    # VLANs of the topology that was deployed last and stale ones disappear on their own.
    PERSISTENT_NAME = "topologybuilder-vlan-subinterfaces"
    PERSISTENT_SCRIPT_PATH = f"/usr/local/sbin/{PERSISTENT_NAME}.sh"
    PERSISTENT_UNIT_PATH = f"/etc/systemd/system/{PERSISTENT_NAME}.service"

    def __init__(
        self, gns3_ssh_connection: SSHConnection, parent_interface: str
    ) -> None:
        """
        :param gns3_ssh_connection: SSH connection to the GNS3 VM
        :param parent_interface: name of the interface on the GNS3 VM where the subinterfaces should be located.
        """
        self.gns3_ssh_connection = gns3_ssh_connection
        self.parent_interface = parent_interface
        self.script = "set -e\n"

    def _get_existing_subinterfaces(self) -> list[str]:
        """
        Get the existing subinterface names of the parent interface on the GNS3 VM.
        :return: A list of found subinterface-names as strings or an empty list
        :raises RuntimeError: Is thrown when an error occurs while trying to get subinterface information.
        """
        _stdin, stdout, stderr = self.gns3_ssh_connection.exec_command(
            f"ip -br link show type vlan | grep @{self.parent_interface} | awk '{{sub(/@.*/, \"\", $1); print $1}}'"
        )
        if stderr.channel.recv_exit_status() != 0:
            err = stderr.read().decode()
            logger.error(
                msg
                := "An error occurred while trying to receive subinterface information."
            )
            raise RuntimeError(msg + "\n" + err)

        lines = stdout.readlines()
        lines = [line.strip() for line in lines]
        return lines

    def _create_subinterface_deletion_commands(self) -> None:
        """
        Creates the commands for the deletion of existing subinterfaces on the ``self.parent_interface`` interface.
        :return:
        :raises RuntimeError: Is thrown when an error occurs while trying to get subinterface information.
        """
        for subinterface in self._get_existing_subinterfaces():
            # ----------------------------------------------------------------------------------------------------------
            if Settings.IS_DRY_RUN:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL, f"Would delete subinterface {subinterface}"
                )
                continue
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Deletes subinterface {subinterface}"
            )
            # ----------------------------------------------------------------------------------------------------------
            self.script += f"ip link delete {subinterface}\n"

    @staticmethod
    def expected_subinterfaces(graph: Graph) -> dict[str, int]:
        """
        The subinterfaces the graph needs on the GNS3 VM, as {name: vlan id}.
        A direct ESXi-to-ESXi link's two interfaces share the exact same
        VirtualLan object (see Graph._assign_vlans), so without deduping
        here, the same subinterface name would be created twice - the
        second ``ip link add`` fails since the name already exists, and
        since the script runs with ``set -e``, that aborts every
        remaining subinterface command in the whole script. Such a VLAN
        also needs no subinterface at all - both vNICs already share the
        port group directly at the ESXi layer, so nothing on this VLAN
        ever needs to reach the GNS3 VM's trunk NIC.
        :return: {subinterface name: vlan id}, in graph order
        """
        from src.graph import Environment

        expected: dict[str, int] = {}
        seen_vlan_ids: set[int] = set()
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None or vlan.id in seen_vlan_ids:
                    continue
                neighbour = interface.neighbour
                if neighbour is not None and neighbour.env == Environment.ON_ESXI:
                    continue
                seen_vlan_ids.add(vlan.id)
                expected[vlan.subinterface_name] = vlan.id
        return expected

    def missing_subinterfaces(self, graph: Graph) -> dict[str, int]:
        """
        The needed subinterfaces that do not exist on the GNS3 VM right now - they
        are plain ``ip link`` objects, lost whenever that VM reboots, which silently
        cuts every link between a GNS3 node and an ESXi VM.
        :raises RuntimeError: Is thrown when the existing subinterfaces cannot be read.
        """
        existing = set(self._get_existing_subinterfaces())
        return {
            name: vlan_id
            for name, vlan_id in self.expected_subinterfaces(graph).items()
            if name not in existing
        }

    def create_missing_subinterfaces(self, graph: Graph) -> list[str]:
        """
        Creates only the subinterfaces that are missing - nothing existing is deleted or
        touched, so running links stay up.
        :return: the names that were created
        :raises RuntimeError: Is thrown when the creation fails.
        """
        missing = self.missing_subinterfaces(graph)
        if not missing or Settings.IS_DRY_RUN:
            return list(missing) if Settings.IS_DRY_RUN else []
        self.script = "set -e\n"
        for name, vlan_id in missing.items():
            self.script += (
                f"ip link add link {self.parent_interface} name {name} type vlan id {vlan_id}\n"
                f"ip link set {name} up\n"
            )
        self.execute_script()
        return list(missing)

    def _create_subinterface_creation_commands(self, graph: Graph) -> None:
        """
        Creates the commands for the creation of subinterfaces, on the ``self.parent_interface`` interface.
        :return:
        """
        for name, vlan_id in self.expected_subinterfaces(graph).items():
            # ----------------------------------------------------------------------------------------------------------
            if Settings.IS_DRY_RUN:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL,
                    f"Would create subinterface {name} with vlan {vlan_id}",
                )
                continue
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"Creates subinterface {name} with vlan {vlan_id}",
            )
            # ----------------------------------------------------------------------------------------------------------

            self.script += (
                f"ip link add link {self.parent_interface} name {name} type vlan id {vlan_id}\n"
                + f"ip link set {name} up\n"
            )

    def persistent_script_text(self, graph: Graph) -> str:
        """
        The boot-time script: waits for the parent interface and creates the subinterfaces the graph
        needs that do not exist yet (running ones are left alone, so it is safe to run at any time).
        """
        parent = shlex.quote(self.parent_interface)
        lines = [
            "#!/bin/sh",
            "# Managed by TopologyBuilder: regenerated on every deploy, do not edit.",
            "# Re-creates the VLAN subinterfaces of the last deployed topology after a reboot.",
            "rc=0",
            f"for i in $(seq 1 60); do ip link show {parent} >/dev/null 2>&1 && break; sleep 1; done",
            f"ip link set {parent} up || rc=1",
        ]
        for name, vlan_id in self.expected_subinterfaces(graph).items():
            name = shlex.quote(name)
            lines.append(
                f"ip link show {name} >/dev/null 2>&1 || ip link add link {parent} name {name} type vlan id {int(vlan_id)} || rc=1"
            )
            lines.append(f"ip link set {name} up || rc=1")
        lines.append("exit $rc")
        return "\n".join(lines) + "\n"

    def persistent_unit_text(self) -> str:
        return (
            "[Unit]\n"
            "Description=VLAN subinterfaces of the last TopologyBuilder deployment (managed file)\n"
            "After=network.target\n"
            "Before=gns3.service gns3-server.service\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            "RemainAfterExit=yes\n"
            f"ExecStart={self.PERSISTENT_SCRIPT_PATH}\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )

    def _run_remote(self, command: str) -> tuple[int, str]:
        _stdin, stdout, _stderr = self.gns3_ssh_connection.exec_command(command)
        output = stdout.read().decode()
        return stdout.channel.recv_exit_status(), output

    def persistent_config_problem(self, graph: Graph) -> str | None:
        """
        Compares the managed files on the GNS3 VM with what the graph needs.
        :return: what is wrong (missing, outdated, not enabled), None when the VM brings the subinterfaces back by itself
        :raises RuntimeError: Is thrown when the files cannot be read.
        """
        code, script = self._run_remote(
            f"cat {self.PERSISTENT_SCRIPT_PATH} 2>/dev/null"
        )
        if code != 0:
            return "not installed"
        if script != self.persistent_script_text(graph):
            return "outdated (it does not match this topology's VLANs)"
        _, unit = self._run_remote(f"cat {self.PERSISTENT_UNIT_PATH} 2>/dev/null")
        if unit != self.persistent_unit_text():
            return "service file missing or outdated"
        _, enabled = self._run_remote(
            f"systemctl is-enabled {self.PERSISTENT_NAME}.service 2>/dev/null"
        )
        if enabled.strip() != "enabled":
            return "service not enabled"
        return None

    def _persistent_install_script(self, graph: Graph) -> str:
        def write(path: str, text: str, mode: str) -> str:
            encoded = base64.b64encode(text.encode()).decode()
            return f"echo {encoded} | base64 -d > {path}\nchmod {mode} {path}\n"

        return (
            write(
                self.PERSISTENT_SCRIPT_PATH, self.persistent_script_text(graph), "755"
            )
            + write(self.PERSISTENT_UNIT_PATH, self.persistent_unit_text(), "644")
            + "systemctl daemon-reload\n"
            + f"systemctl enable {self.PERSISTENT_NAME}.service\n"
        )

    def install_persistent_config(self, graph: Graph) -> bool:
        """
        Writes the managed script and unit and enables the service. Nothing is started or restarted
        and no running subinterface is touched, so this is safe while links are carrying traffic.
        :return: True when something was written, False when it was already up to date
        :raises RuntimeError: Is thrown when the files cannot be written.
        """
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, "Would write the boot-time VLAN subinterface service"
            )
            return False
        if self.persistent_config_problem(graph) is None:
            return False
        self.script = "set -e\n" + self._persistent_install_script(graph)
        self.execute_script()
        return True

    def initialize_commands(self, graph: Graph) -> None:
        """
        Initializes the commands for the creation and deletion of subinterfaces, on the GNS3 VM.
        :param graph: Create the commands based on given graph
        :return:
        :raises RuntimeError: Is thrown when an error occurs while trying to get subinterface information.
        """
        self._create_subinterface_deletion_commands()
        self._create_subinterface_creation_commands(graph)
        if not Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, "Writes the boot-time VLAN subinterface service"
            )
            self.script += self._persistent_install_script(graph)

    def execute_script(self) -> tuple[int, str, str]:
        """
        Executes the commands via a remote shell on the GNS3 VM.
        :return: Returns the exit code, output and error messages
        :raises RuntimeError: Is thrown when execution of the script fails.
        """
        if Settings.IS_DRY_RUN:
            return 0, "", ""

        stdin, stdout, stderr = self.gns3_ssh_connection.exec_command("sudo bash -s")
        stdin.write(self.script)
        stdin.flush()
        stdin.channel.shutdown_write()

        output = stdout.read().decode()
        errors = stderr.read().decode()
        exit_code = stdout.channel.recv_exit_status()
        if stderr.channel.recv_exit_status() != 0:
            logger.error(
                msg
                := "An error occurred while trying to execute the subinterface script."
            )
            raise RuntimeError(msg + "\n" + errors)

        return exit_code, output, errors
