"""
Provides a class for the creation of the configuration file for the subinterfaces of the GNS3 VM.
"""

__license__ = "GNU GPLv3"

from pathlib import Path

from src.connections_handler import SSHConnection
from src.factories import GenericNode, compute_esxi_vlan_assignments
from src.logger_adapter import get_logger

logger = get_logger(__name__)

# Guest-side interface name prefixes that are never a VMware vNIC, so never
# a candidate for the trunk NIC - Docker/libvirt bridges, veth pairs, tun/tap
# devices, and loopback.
_VIRTUAL_INTERFACE_PREFIXES = ("lo", "docker", "virbr", "veth", "br-", "tun", "tap")


class GNS3VMInterfaceSetup:
    """
    class to handle the interface configuration of the GNS3 VM to ensure, that only the dedicated GNS3 device can communicate with the VM on the ESXi host.
    This is done by subinterfaces with vlans on the GNS3 VM which correspond with the VLANs of the vSwitch on the ESXi host.
    """

    def __init__(self, gns3_connection: SSHConnection) -> None:
        """
        Initialize the GNS3 VM interface setup class
        :param gns3_connection: SSH connection to the GNS3 VM
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

    def _verify_interface_exists(self, interface_name: str) -> None:
        """
        Confirms the given interface actually exists on the GNS3 VM before
        trying to create VLAN subinterfaces on it. The trunk NIC's name
        isn't guaranteed to be 'eth1' on every GNS3 VM build - e.g. a
        --fresh-gns3-vm import from an OVA that only declares one NIC gets
        a second one added afterward (see OVAImporter/add_vm_network_adapters),
        and the guest OS may not name that added NIC the same way. Raises a
        clear error listing the actual available interfaces, instead of
        letting the first 'ip link add' fail deep inside _apply_command
        with a bare 'Cannot find device' message.
        :param interface_name: interface name to check for
        :return:
        """
        _, stdout, _ = self.gns3_connection.exec_command(
            f"ip -br link show {interface_name}"
        )
        if stdout.channel.recv_exit_status() == 0:
            return

        _, stdout, _ = self.gns3_connection.exec_command(
            "ip -br link show | awk '{print $1}' | grep -v '^lo$'"
        )
        available = [line.strip() for line in stdout.readlines()]
        raise logger.alert(
            ValueError,
            f"GNS3 VM has no interface named '{interface_name}'. Available "
            f"interfaces: {available}. Specify --gns3-trunk-interface if "
            f"the trunk NIC isn't named '{interface_name}' on this VM.",
        )

    def _detect_trunk_interface(self) -> str:
        """
        Auto-detects the GNS3 VM's trunk NIC by querying its interfaces and
        excluding the management interface (the one carrying the IP this
        SSH connection is on) and known virtual/non-VMware interfaces
        (loopback, Docker/libvirt bridges, veth pairs, ...). Used when no
        --gns3-trunk-interface is given, since the name isn't guaranteed to
        be 'eth1' across different GNS3 VM builds. Only auto-picks when
        exactly one candidate remains - refuses to guess otherwise, same as
        ESXiConnection.find_gns3_vm does for the VM name itself.
        :return: the detected trunk interface name
        """
        _, stdout, _ = self.gns3_connection.exec_command("ip -br addr show")
        addr_lines = [line.strip() for line in stdout.readlines() if line.strip()]

        mgmt_interface = None
        for line in addr_lines:
            if self.gns3_connection.ip_address in line:
                mgmt_interface = line.split()[0]
                break

        _, stdout, _ = self.gns3_connection.exec_command("ip -br link show")
        all_interfaces = [
            line.split()[0] for line in stdout.readlines() if line.strip()
        ]

        candidates = [
            name
            for name in all_interfaces
            if name != mgmt_interface
            and not name.lower().startswith(_VIRTUAL_INTERFACE_PREFIXES)
        ]

        if len(candidates) == 1:
            logger.info(f"Auto-detected GNS3 VM trunk interface '{candidates[0]}'")
            return candidates[0]

        raise logger.alert(
            ValueError,
            f"Could not auto-detect the GNS3 VM's trunk interface "
            f"(management interface: '{mgmt_interface}', other candidate(s): "
            f"{candidates}). Specify --gns3-trunk-interface.",
        )

    def _reset_subinterfaces_commands(self, interface: str) -> None:
        """
        Deletes the existing subinterfaces of given interface on the GNS3 VM.
        :param interface: name of interface, from which the subinterfaces are
        :return:
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
        """
        for esxi_vlan_name, vlan_id in compute_esxi_vlan_assignments(nodes).items():
            self._apply_command(
                f"ip link add link {interface_name} name {esxi_vlan_name} type vlan id {vlan_id}"
            )
            self._apply_command(f"ip link set {esxi_vlan_name} up")

    def write_config_file(
        self, nodes: dict[str, GenericNode], trunk_interface: str | None = None
    ) -> None:
        """
        Applies the VLAN subinterface configuration to the GNS3 VM: deletes the
        existing subinterfaces and creates the ones needed for the given
        topology. Also keeps a human-readable record of the applied commands
        in ./esxi_instances/.
        :param nodes: built topology of the nodes
        :param trunk_interface: name of the GNS3 VM's trunk NIC to create
            VLAN subinterfaces on, or None to auto-detect it (see
            _detect_trunk_interface) - not guaranteed to be 'eth1' across
            different GNS3 VM builds. Verified to exist before use either
            way (auto-detection already guarantees this; an explicitly
            given name is checked via _verify_interface_exists).
        :return:
        """
        if trunk_interface is None:
            trunk_interface = self._detect_trunk_interface()
        else:
            self._verify_interface_exists(trunk_interface)

        config_file_path = self.configuration_file_path
        config_file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_file_path, "w") as f:
            f.write("# Commands applied to the GNS3 VM via SSH:\n")

        self._reset_subinterfaces_commands(trunk_interface)
        self._create_subinterfaces_commands(trunk_interface, nodes)
