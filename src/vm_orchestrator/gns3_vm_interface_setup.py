__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.connections import SSHConnection
from src.graph import Graph
from src.settings import Settings, Verbosity
from loguru import logger


class GNS3VMInterfaceSetup:
    """
    Object to handle the interface configuration of the GNS3 VM to ensure, that only the dedicated GNS3 device can communicate with the VM on the ESXi host.
    This is done by subinterfaces with vlans on the GNS3 VM which correspond with the VLANs of the vSwitch on the ESXi host.
    """

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
        stdin, stdout, stderr = self.gns3_ssh_connection.exec_command(
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

    def _create_subinterface_creation_commands(self, graph: Graph) -> None:
        """
        Creates the commands for the creation of subinterfaces, on the ``self.parent_interface`` interface.
        A direct ESXi-to-ESXi link's two interfaces share the exact same
        VirtualLan object (see Graph._assign_vlans), so without deduping
        here, the same subinterface name would be created twice - the
        second ``ip link add`` fails since the name already exists, and
        since the script runs with ``set -e``, that aborts every
        remaining subinterface command in the whole script. Such a VLAN
        also needs no subinterface at all - both vNICs already share the
        port group directly at the ESXi layer, so nothing on this VLAN
        ever needs to reach the GNS3 VM's trunk NIC.
        :return:
        """
        from src.graph import Environment

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

                # ----------------------------------------------------------------------------------------------------------
                if Settings.IS_DRY_RUN:
                    Verbosity.volumatic_print(
                        Verbosity.NORMAL,
                        f"Would create subinterface {vlan.name} with vlan {vlan.id}",
                    )
                    continue
                Verbosity.volumatic_print(
                    Verbosity.NORMAL,
                    f"Creates subinterface {vlan.name} with vlan {vlan.id}",
                )
                # ----------------------------------------------------------------------------------------------------------

                self.script += (
                    f"ip link add link {self.parent_interface} name {vlan.name} type vlan id {vlan.id}\n"
                    + f"ip link set {vlan.name} up\n"
                )

    def initialize_commands(self, graph: Graph) -> None:
        """
        Initializes the commands for the creation and deletion of subinterfaces, on the GNS3 VM.
        :param graph: Create the commands based on given graph
        :return:
        :raises RuntimeError: Is thrown when an error occurs while trying to get subinterface information.
        """
        self._create_subinterface_deletion_commands()
        self._create_subinterface_creation_commands(graph)

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
