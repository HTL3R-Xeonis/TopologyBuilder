from pathlib import Path

import paramiko

from src.factories import GenericNode
from src.logger_adapter import get_logger
from src.factories import Environment

logger = get_logger()


class GNS3VMInterfaceSetup:
    def __init__(self, gns3_vm_name: str = "GNS3"):
        self.gns3_vm_name = gns3_vm_name
        self.conn = None

        self.config_file_path = Path("./esxi_instances/config_i1_gns3.txt")
        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file_path, "w") as f:
            f.write("sudo su\n")

    def connect(self, ip_address: str) -> None:
        gns3_ip = ip_address

        if gns3_ip is None:
            raise logger.alert(
                ConnectionError, "Cannot connect to GNS3 VM. No IP address was found."
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

        self.conn = client

    def get_subinterfaces(self, interface: str) -> list[str]:
        lines = self.conn.exec_command(
            f"ip -br link show type vlan | grep @{interface} | awk '{{sub(/@.*/, \"\", $1); print $1}}'"
        )[1].readlines()
        lines = [line.strip() for line in lines]
        return lines

    def write_command(self, command: str) -> None:
        with open(self.config_file_path, "a") as f:
            f.write(f"{command}\n")

    def reset_subinterfaces_commands(self) -> None:
        for si in self.get_subinterfaces("eth1"):
            self.write_command(f"ip link delete {si}")

    def create_subinterfaces_commands(self, nodes: dict[str, GenericNode]) -> None:
        vlan_id = 2
        for node in nodes.values():
            if not node.env == Environment.ON_ESXI:
                continue
            for interface in node.interfaces.values():
                if vlan_id >= 4094:
                    logger.alert(
                        ValueError,
                        "VLANs on ESXi exceed the limit of 4094. Reduce the number of interfaces on VMs on ESXi",
                    )
                self.write_command(
                    f"ip link add {interface.esxi_vlan} type vlan id {vlan_id}"
                )
                vlan_id += 1

    def write_config_file(self, nodes: dict[str, GenericNode]) -> None:
        self.reset_subinterfaces_commands()
        self.create_subinterfaces_commands(nodes)
