"""
Provides a class for the creation of the configuration file for the subinterfaces of the GNS3 VM.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from pathlib import Path

from src.connection_handler.ssh_connection import SSHConnection
from src.graph_builder.factories import Environment
from src.graph_builder.factories import GenericNode
from src.logger_adapter import get_logger

logger = get_logger()


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
        self.interface_map = {}
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

    def _write_commands(self, commands: str) -> None:
        """
        Writes the given string to the a file which is located in ./esxi_instances/
        :param commands: string to write
        :return:
        @TODO create pytest
        """
        config_file_path = self.configuration_file_path
        config_file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.configuration_file_path, "w", newline="\n") as f:
            f.write(f"{commands}")

    def _reset_subinterfaces_commands(self, interface: str) -> str:
        """
        Writes the commands to a file, which is located in ./esxi_instances/, to delete the subinterfaces
        :param interface: name of interface, from which the subinterfaces are
        :return:
        @TODO create pytest
        """
        commands = ""
        for si in self._get_subinterfaces(interface):
            commands += f"ip link delete {si}\n"
        return commands

    def _create_subinterfaces_commands(
        self, interface_name: str, nodes: dict[str, GenericNode]
    ) -> str:
        """
        Writes the commands to a file, which is located in ./esxi_instances/, to create and turn up the needed subinterfaces accordingly to the topology
        :param interface_name: name of interface to which to add the subinterfaces
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """
        vlan_id = 2
        commands = ""
        for node in nodes.values():
            if not node.env == Environment.ON_ESXI:
                continue
            for node_interface in node.interfaces.values():
                if vlan_id >= 4094:
                    logger.alert(
                        ValueError,
                        "VLANs on ESXi exceed the limit of 4094. Reduce the number of interfaces on VMs on ESXi",
                    )
                commands += (
                    f"ip link add link {interface_name} name {node_interface.esxi_vlan} type vlan id {vlan_id}\n"
                    + f"ip link set {node_interface.esxi_vlan} up\n"
                )
                self.interface_map[node_interface.esxi_vlan] = vlan_id

                vlan_id += 1
        return commands

    def write_config_file(self, nodes: dict[str, GenericNode]) -> None:
        """
        Writes the config file for the GNS3 VM to delete and create the needed subinterfaces.
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """
        commands = "#!/bin/bash\n"
        commands += self._reset_subinterfaces_commands("eth1")
        commands += self._create_subinterfaces_commands("eth1", nodes)
        self._write_commands(commands)
