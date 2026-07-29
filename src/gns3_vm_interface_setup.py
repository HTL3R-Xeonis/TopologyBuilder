"""
Handles the creation of the configuration file for the subinterfaces of the GNS3 VM
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from pathlib import Path

import paramiko
from paramiko import SSHClient

from src.factories import GenericNode
from src.logger_adapter import get_logger
from src.factories import Environment

logger = get_logger()


class GNS3VMInterfaceSetup:
    """
    class to handle the interface configuration of the GNS3 VM to ensure, that only the dedicated GNS3 device can communicate with the VM on the ESXi host.
    This is done by subinterfaces with vlans on the GNS3 VM which correspond with the VLANs of the vSwitch on the ESXi host.
    """

    def __init__(self, gns3_vm_name: str = "GNS3"):
        """
        Initialize the GNS3 VM interface setup class
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host

        @TODO create pytest
        """
        self.gns3_vm_name = gns3_vm_name
        self.ssh_gns3_client = None

    def connect(self, ip_address: str | None) -> SSHClient:
        """
        Establishes an SSH connection to the given GNS3 VM IPv4 address
        :param ip_address: IPv4 address
        :return: Connection to the GNS3 VM

        @TODO create pytest
        """
        if self.ssh_gns3_client is not None:
            return self.ssh_gns3_client
        gns3_ip = ip_address

        if gns3_ip is None:
            raise logger.alert(
                ConnectionError,
                "Cannot connect to GNS3 VM. No IP address or VM was found.",
            )

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=gns3_ip,
            port=22,
            username="gns3",
            password="gns3",
            timeout=10,
        )

        self.ssh_gns3_client = client
        return client

    def _get_subinterfaces(self, interface: str) -> list[str]:
        """
        Gets the subinterface-names of given interface-name and returns them as a list.
        :param interface: the name of the interface to look on for subinterfaces
        :return: A list of found subinterface-names as strings or an empty list

        @TODO create pytest
        """
        lines = self.ssh_gns3_client.exec_command(
            f"ip -br link show type vlan | grep @{interface} | awk '{{sub(/@.*/, \"\", $1); print $1}}'"
        )[1].readlines()
        lines = [line.strip() for line in lines]
        return lines

    @staticmethod
    def _write_command(path: Path, command: str) -> None:
        """
        Appends the given command to the given file
        :param path: path to the file to write to
        :param command: string to write
        :return:
        @TODO create pytest
        """
        if not path.exists():
            logger.alert(FileNotFoundError, f"File not found: {path}")
        with open(path, "a") as f:
            f.write(f"{command}\n")

    def _reset_subinterfaces_commands(self, path: Path, interface: str) -> None:
        """
        Writes the commands to given file, to delete the subinterfaces
        :param path: path to file
        :param interface: name of interface, from which the subinterfaces are
        :return:
        @TODO create pytest
        """
        for si in self._get_subinterfaces(interface):
            self._write_command(path, f"ip link delete {si}")

    def _create_subinterfaces_commands(
        self, path: Path, interface_name: str, nodes: dict[str, GenericNode]
    ) -> None:
        """
        Writes the commands to given file, to create and turn up the needed subinterfaces accordingly to the topology
        :param path: path to file
        :param interface_name: name of interface to which to add the subinterfaces
        :param nodes: built topology of the nodes
        :return:
        @TODO create pytest
        """
        vlan_id = 2
        for node in nodes.values():
            if not node.env == Environment.ON_ESXI:
                continue
            for node_interface in node.interfaces.values():
                if vlan_id >= 4094:
                    logger.alert(
                        ValueError,
                        "VLANs on ESXi exceed the limit of 4094. Reduce the number of interfaces on VMs on ESXi",
                    )
                self._write_command(
                    path,
                    f"ip link add link {interface_name} name {node_interface.esxi_vlan} type vlan id {vlan_id}\n"
                    f"ip link set {node_interface.esxi_vlan} up",
                )
                vlan_id += 1

    def write_config_file(
        self, nodes: dict[str, GenericNode], gns3_ip_address: str | None
    ) -> None:
        """
        Writes the config file for the GNS3 VM to delete and create the needed subinterfaces.
        :param nodes: built topology of the nodes
        :param gns3_ip_address: IPv4 address
        :return:
        @TODO create pytest
        """
        if self.ssh_gns3_client is None:
            self.connect(gns3_ip_address)

        config_file_path = Path(
            f"./esxi_instances/config_i{gns3_ip_address[-1]}_gns3.txt"
        )
        config_file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_file_path, "w") as f:
            f.write("sudo su\n")

        self._reset_subinterfaces_commands(config_file_path, "eth1")
        self._create_subinterfaces_commands(config_file_path, "eth1", nodes)
