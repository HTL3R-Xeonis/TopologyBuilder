"""
Provides a class for the creation of the configuration file for the subinterfaces of the GNS3 VM.
"""

__license__ = "GNU GPLv3"

from pathlib import Path

from src.connections_handler import SSHConnection
from src.factories import GenericNode, compute_esxi_vlan_assignments
from src.logger_adapter import get_logger

logger = get_logger(__name__)


class GNS3VMInterfaceSetup:
    """
    class to handle the interface configuration of the GNS3 VM to ensure, that only the dedicated GNS3 device can communicate with the VM on the ESXi host.
    This is done by subinterfaces with vlans on the GNS3 VM which correspond with the VLANs of the vSwitch on the ESXi host.
    """

    def __init__(self, gns3_connection: SSHConnection) -> None:
        """
        Initialize the GNS3 VM interface setup class
        :param gns3_connection: SSH connection to the GNS3 VM
        @TODO create pytest
        """
        self.gns3_connection = gns3_connection
        self.configuration_file_path = Path(
            f"./esxi_instances/config_i{gns3_connection.ip_address[-1]}_gns3.txt"
        )

    def _get_subinterfaces(self, interface: str) -> list[str]:
        """
        Gets the subinterface-names of given interface-name and returns them as a list.
        :param interface: the name of the interface to look on for subinterfaces
        :return: A list of found subinterface-names as strings or an empty list

        @TODO create pytest
        """
        lines = self.gns3_connection.exec_command(
            f"ip -br link show type vlan | grep @{interface} | awk '{{sub(/@.*/, \"\", $1); print $1}}'"
        )[1].readlines()
        lines = [line.strip() for line in lines]
        return lines

    def _write_command(self, command: str) -> None:
        """
        Appends the given command to the a file which is located in ./esxi_instances/,
        kept as a human-readable record of what was applied to the GNS3 VM.
        :param command: string to write
        :return:
        @TODO create pytest
        """
        if not self.configuration_file_path.exists():
            logger.alert(
                FileNotFoundError, f"File not found: {self.configuration_file_path}"
            )
        with open(self.configuration_file_path, "a") as f:
            f.write(f"{command}\n")

    def _apply_command(self, command: str) -> None:
        """
        Records the given command in the local audit file and executes it on the
        GNS3 VM over the existing SSH connection, with 'sudo -n' since the
        official GNS3 VM appliance grants its default user passwordless sudo.
        Raises if the remote command exits with a non-zero status.
        :param command: shell command to apply on the GNS3 VM
        :return:
        @TODO create pytest
        """
        self._write_command(command)

        _, stdout, stderr = self.gns3_connection.exec_command(f"sudo -n {command}")
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            raise logger.alert(
                RuntimeError,
                f"Command failed on GNS3 VM (exit {exit_status}): {command}\n"
                f"{stderr.read().decode().strip()}",
            )

    def _reset_subinterfaces_commands(self, interface: str) -> None:
        """
        Deletes the existing subinterfaces of given interface on the GNS3 VM.
        :param interface: name of interface, from which the subinterfaces are
        :return:
        @TODO create pytest
        """
        for si in self._get_subinterfaces(interface):
            self._apply_command(f"ip link delete {si}")

    def _create_subinterfaces_commands(
        self, interface_name: str, nodes: dict[str, GenericNode]
    ) -> None:
        """
        Creates and turns up the needed subinterfaces on the GNS3 VM, accordingly
        to the topology. VLAN IDs are assigned by compute_esxi_vlan_assignments,
        so they stay in sync with the matching ESXi vSwitch port groups.
        :param interface_name: name of interface to which to add the subinterfaces
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """
        for esxi_vlan_name, vlan_id in compute_esxi_vlan_assignments(nodes).items():
            self._apply_command(
                f"ip link add link {interface_name} name {esxi_vlan_name} type vlan id {vlan_id}"
            )
            self._apply_command(f"ip link set {esxi_vlan_name} up")

    def write_config_file(self, nodes: dict[str, GenericNode]) -> None:
        """
        Applies the VLAN subinterface configuration to the GNS3 VM: deletes the
        existing subinterfaces and creates the ones needed for the given
        topology. Also keeps a human-readable record of the applied commands
        in ./esxi_instances/.
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """

        config_file_path = self.configuration_file_path
        config_file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_file_path, "w") as f:
            f.write("# Commands applied to the GNS3 VM via SSH:\n")

        self._reset_subinterfaces_commands("eth1")
        self._create_subinterfaces_commands("eth1", nodes)
