import os
from typing import ClassVar

import yaml
from dotenv import load_dotenv
from loguru import logger

from .verbosity import Verbosity

load_dotenv()


def _env_url(name: str, default: str) -> str:
    """A service URL from the environment (empty counts as unset), without a trailing slash; else ``default``."""
    return (os.getenv(name) or default).rstrip("/")


class Settings:
    def __init__(self):
        self.esxi = self.ESXI()
        """Settings related to ESXi."""
        self.gns3 = self.GNS3()
        """Settings related to GNS3."""
        self.api = self.API()
        """Settings related to API requests."""

    @staticmethod
    def initialise_settings(path: str) -> None:
        """
        Loads settings overrides from a YAML file (see
        ``settings.example.yml``) and applies them onto this class and its
        nested ESXI/GNS3/API classes. Any key not present in the file is
        left at its current value, so the file only needs to declare what
        it wants to override.

        Passwords are deliberately not supported here - use the
        ESXI_PASSWORD/GNS3_PASSWORD environment variables (a .env file
        works too, see ``.env.example``) or the CLI's own
        --esxi_password/--gns3_password options instead, so a secret never
        ends up sitting in a settings file on disk.
        :param path: path to the YAML settings file
        :return:
        :raises FileNotFoundError: is thrown when no file exists at ``path``.
        :raises ValueError: is thrown when the file contains a 'password' key anywhere.
        """
        with open(path, "r") as file:
            data = yaml.safe_load(file) or {}

        esxi = data.get("esxi", {})
        gns3 = data.get("gns3", {})
        if "password" in esxi or "password" in gns3:
            raise ValueError(
                "Passwords are not supported in the settings file - use "
                "ESXI_PASSWORD/GNS3_PASSWORD environment variables (e.g. via "
                "a .env file) or the corresponding CLI options instead."
            )

        if "topology_file" in data:
            Settings.TOPOLOGY_FILE = data["topology_file"]
        if "log_file_path" in data:
            Settings.LOG_FILE_PATH = data["log_file_path"]
        if "generate_max_retries" in data:
            Settings.GENERATE_MAX_RETRIES = int(data["generate_max_retries"])
        if "incremental_deploy" in data:
            Settings.INCREMENTAL_DEPLOY = bool(data["incremental_deploy"])

        if "ip" in esxi:
            Settings.ESXI.IP = esxi["ip"]
        if "port" in esxi:
            Settings.ESXI.PORT = esxi["port"]
        if "username" in esxi:
            Settings.ESXI.USERNAME = esxi["username"]
        if "virtual_switch" in esxi:
            Settings.ESXI.VIRTUAL_SWITCH = esxi["virtual_switch"]
        if "trunk_port_group" in esxi:
            Settings.ESXI.TRUNK_PORT_GROUP = esxi["trunk_port_group"]
        if "ignore_port_groups" in esxi:
            Settings.ESXI.IGNORE_PORT_GROUPS = set(esxi["ignore_port_groups"])
        if "datastore" in esxi:
            Settings.ESXI.DATASTORE = esxi["datastore"]
        if "gns3_vm_name" in esxi:
            Settings.ESXI.GNS3_VM_NAME = esxi["gns3_vm_name"]
        if "delete_unused_vms" in esxi:
            Settings.ESXI.DELETE_UNUSED_VMS = bool(esxi["delete_unused_vms"])
        if "gns3_vm_ova_path" in esxi:
            Settings.ESXI.GNS3_VM_OVA_PATH = esxi["gns3_vm_ova_path"]
        if "gns3_vm_mgmt_network" in esxi:
            Settings.ESXI.GNS3_VM_MGMT_NETWORK = esxi["gns3_vm_mgmt_network"]
        if "http_timeout_seconds" in esxi:
            Settings.ESXI.HTTP_TIMEOUT_SECONDS = esxi["http_timeout_seconds"]
        if "task_timeout_seconds" in esxi:
            Settings.ESXI.TASK_TIMEOUT_SECONDS = float(esxi["task_timeout_seconds"])
        if "gns3_vm_mac_range" in esxi:
            mac_range = esxi["gns3_vm_mac_range"]
            if mac_range is not None:
                if len(mac_range) != 2:
                    raise ValueError(
                        "esxi.gns3_vm_mac_range must be a list of exactly "
                        "two MAC addresses: [start, end]"
                    )
                mac_range = (mac_range[0], mac_range[1])
            Settings.ESXI.GNS3_VM_MAC_RANGE = mac_range

        if "username" in gns3:
            Settings.GNS3.USERNAME = gns3["username"]
        if "project_name" in gns3:
            Settings.GNS3.PROJECT_NAME = gns3["project_name"]
        if "port" in gns3:
            Settings.GNS3.PORT = gns3["port"]
        if "parent_interface" in gns3:
            Settings.GNS3.PARENT_INTERFACE = gns3["parent_interface"]
        if "interface_setup_timeout_seconds" in gns3:
            Settings.GNS3.INTERFACE_SETUP_TIMEOUT_SECONDS = float(
                gns3["interface_setup_timeout_seconds"]
            )

        api = data.get("api", {})
        if "esxi_template_server_url" in api:
            Settings.API.ESXI_TEMPLATE_SERVER_URL = api["esxi_template_server_url"]
        if "gns3_template_server_url" in api:
            Settings.API.GNS3_TEMPLATE_SERVER_URL = api["gns3_template_server_url"]
        if "topology_generator_url" in api:
            Settings.API.TOPOLOGY_GENERATOR_URL = api["topology_generator_url"]
        if "ova_deploy_url" in api:
            Settings.API.OVA_DEPLOY_URL = api["ova_deploy_url"]

        logger.info(f"Loaded settings overrides from {path}")

    VERBOSITY_LEVEL: Verbosity = Verbosity.NORMAL
    """The verbosity level of the program."""
    TOPOLOGY_FILE: str = "./topology_example.yaml"
    """Path to the YAML file which represents the topology."""
    LOG_FILE_PATH: str = "./logs/app.log"
    """Path to the log file main() configures loguru to write to."""
    IS_DRY_RUN: bool = False
    """If True, only prints what would happen. May still execute API requests."""
    ONLY_ON_GNS3: bool = False
    """If True, only deploys nodes which are in the GNS3 environment."""
    ONLY_ON_ESXI: bool = False
    """"Only deploys nodes which are in the ESXi environment. Still creates Cloud-nodes on GNS3 to ensure possible connections between the ESXi-VMs."""
    GENERATE_MAX_RETRIES: int = 3
    """How many times the `generate` command retries requesting a new
    topology from the Topology Generator API after one fails validation,
    before giving up."""
    INCREMENTAL_DEPLOY: bool = True
    """Whether TopologyBackend.deploy_topology (the whole-file deploy
    path used by TopologyOperator's .topoproj import, and by `deploy`
    when a project already exists) passes incremental=True through to
    VMOrchestrator.deploy_graph. True (default) reuses anything already
    live by name and only creates what's new/changed - a single slow or
    failing device (e.g. a stuck OVA import) doesn't undo devices that
    already deployed successfully. False does a full deploy: resets the
    ESXi vSwitch, deletes ESXi VMs/GNS3 projects not in the current
    graph (see ESXI.DELETE_UNUSED_VMS), and redeploys everything from
    scratch even if a same-named node/VM already exists - slower and
    more disruptive, but guarantees a clean, fully reproducible result
    with no state left over from a previous deploy. Does not affect
    add_node/add_link, which are inherently incremental by definition
    and always pass incremental=True regardless of this setting."""

    class ESXI:
        """Settings related to ESXi."""

        IP: str = "10.20.20.200"
        """IPv4 address of the ESXi client."""
        PORT: int = 443
        """Port of the ESXi client, where the API requests are expected."""
        USERNAME: str = "root"
        """Username to use for the ESXi connections."""
        PASSWORD: str | None = os.getenv("ESXI_PASSWORD", None)
        """Password to use for the ESXi connections."""
        HTTP_TIMEOUT_SECONDS: float | None = 60
        """Socket-level timeout for every individual vSphere API call made
        over this connection (passed to SmartConnect as its own
        httpConnectionTimeout). None restores pyVmomi's own default of no
        timeout at all, meaning a single call can block forever if the
        connection goes silently dead (no RST/FIN) - observed live: an
        ESXiConnection._wait_for_task poll of task.info.state hung for
        hours during a network interruption, with no exception and no way
        to recover short of restarting the whole process. A finished
        vSphere call normally answers in well under a second; a
        long-running operation (VM clone/create/delete) runs as a
        server-side task that's checked with many short, individually-
        bounded polls (see ESXiConnection._wait_for_task), so this does
        not limit how long a deploy step may legitimately take - only how
        long a single dead-connection call can block before surfacing as
        an error instead of hanging silently."""
        TASK_TIMEOUT_SECONDS: float = 1800
        """Maximum total time ESXiConnection._wait_for_task spends polling
        a single vSphere task before giving up with a TimeoutError,
        instead of looping forever if the task's own state never reaches
        success/error - covers a task that is itself stuck server-side
        (as opposed to a dead connection, which HTTP_TIMEOUT_SECONDS
        covers instead). 30 minutes is generous for even a large
        OVA-based VM clone."""
        VIRTUAL_SWITCH: str = "internal_network"
        """Specifies the virtual switch to use on the ESXi client."""
        TRUNK_PORT_GROUP: str = "PG_GNS3_TRUNK"
        """Name of the port group carrying the GNS3 VM's VLAN trunk NIC. Must
        accept promiscuous mode/MAC changes/forged transmits, which GNS3's
        Cloud nodes need to bridge topology devices through it - ESXi's
        default security policy silently drops that traffic otherwise."""
        IGNORE_PORT_GROUPS: ClassVar[set[str]] = {"PG_GNS3_TRUNK"}
        """Specifies which port groups not to delete on the virtual switch."""
        RESERVED_PORT_GROUPS: ClassVar[set[str]] = {
            "VM Network",
            "Management Network",
        }
        """ESXi's own built-in port groups (present on essentially every
        install, not created by this tool). Always protected from deletion
        regardless of IGNORE_PORT_GROUPS' contents - deleting 'Management
        Network' in particular can sever the host's own management access."""
        DATASTORE: str | None = None
        """Specifies the name of the datastore to use on the ESXi client.
        None (default) auto-picks the datastore with the most free space
        at deploy time (see ESXiConnection.find_biggest_datastore)."""
        GNS3_VM_NAME = "GNS3 (1)"
        """Name of the GNS3 VM to work on."""
        DELETE_UNUSED_VMS: bool = True
        """If True (default), a non-incremental deploy automatically
        deletes ESXi VMs this tool previously created (identified via
        their 'topologybuilder-image:' annotation, set on every VM this
        tool imports) that are no longer part of the current topology -
        cleans up leftovers from an earlier deploy of a *different*
        topology before resetting the vSwitch, so a stale VM's NIC can't
        block port-group removal. The GNS3 VM is always auto-detected
        (see ESXiConnection.find_gns3_vm) and never deleted, regardless of
        this setting. A VM without the annotation - i.e. anything this
        tool didn't create itself - is never touched either way."""
        GNS3_VM_OVA_PATH: str | None = None
        """Local filesystem path to the GNS3 VM's own OVA (an NFS share
        mounted locally works fine here, it's just a path) - see
        src.gns3_vm_deploy.deploy_fresh_gns3_vm. None (default) leaves
        that feature unconfigured; callers that need it (e.g.
        TopologyOperator's own GNS3-VM-missing recovery) should treat a
        None here as "not available", not attempt a deploy with no OVA."""
        GNS3_VM_MGMT_NETWORK: str | None = None
        """ESXi port group for a freshly deployed GNS3 VM's management NIC
        (must be the OVA's first-added network adapter) - see
        src.gns3_vm_deploy.deploy_fresh_gns3_vm. TRUNK_PORT_GROUP above is
        reused for the second (trunk) NIC, rather than adding a second new
        setting for it."""
        GNS3_VM_MAC_RANGE: tuple[str, str] | None = None
        """(start_mac, end_mac) - if set, a freshly deployed GNS3 VM's
        management NIC gets a MAC address from this inclusive range
        instead of inheriting the old VM's own MAC (see
        src.gns3_vm_deploy.deploy_fresh_gns3_vm's own mac_range parameter
        for the exact rule, and src.mac_range for the picking logic) -
        e.g. so a DHCP server can be configured to only hand out IP
        addresses to devices whose MAC falls in this range. None
        (default) leaves the GNS3 VM's MAC exactly as before this
        setting existed: inherited from the old VM if there is one,
        otherwise whatever ESXi auto-assigns."""

    class GNS3:
        """Settings related to GNS3."""

        USERNAME: str = "gns3"
        """Username to use for the GNS3 connections."""
        PASSWORD: str | None = os.getenv("GNS3_PASSWORD", None)
        """Password to use for the GNS3 connections."""
        PROJECT_NAME: str | None = None
        """Name of the GNS3 project to work on. If this project already
        exists on the GNS3 server, it is going to be overwritten. None
        (default) uses the topology file's own stem instead (e.g.
        'my_lab.yaml' -> project 'my_lab') - see
        src.cli._resolve_project_name. Set explicitly to use a fixed
        name regardless of which topology file is active."""
        PORT: int = 80
        """Port of the GNS3 client, where the API requests are expected."""
        PARENT_INTERFACE: str | None = None
        """Name of the interface of the GNS3 VM to create and delete the
        subinterfaces. None (default) auto-detects it by MAC address: the
        GNS3 VM's own vNIC wired to Settings.ESXI.TRUNK_PORT_GROUP is
        looked up on the ESXi side, then matched against the GNS3 VM's
        guest-OS interfaces by MAC (see VMOrchestrator.
        _resolve_gns3_parent_interface) - this interface name isn't
        guaranteed to match across different GNS3 VM builds (e.g. 'eth1'
        vs. 'ens192'), but the MAC does. Set explicitly to skip detection
        and force a specific name."""
        INTERFACE_SETUP_TIMEOUT_SECONDS: float = 120
        """Timeout for the SSH channel GNS3VMInterfaceSetup.execute_script
        uses to run the VLAN-subinterface script on the GNS3 VM (passed to
        paramiko's exec_command, which applies it to the channel's
        blocking reads/writes). Without it, a connection that goes
        silently dead mid-script leaves stdout.read()/stderr.read()
        blocking forever - observed live, same real incident as
        Settings.ESXI.HTTP_TIMEOUT_SECONDS's own docstring. The script
        itself normally finishes in well under this."""

    class API:
        """
        Settings related to API requests.

        Each service URL below comes from, strongest first: the settings file's ``api`` section, an environment
        variable (or ``.env`` entry) with the same name as the setting, and this lab's built-in address. The
        environment layer is what lets a deployment that runs all services together point everything somewhere else
        in one place, without touching any settings file.
        """

        GNS3_TEMPLATE_SERVER_URL = _env_url(
            "GNS3_TEMPLATE_SERVER_URL", "http://10.20.20.171:8001"
        )
        """URL to the GNS3 template API server."""
        ESXI_TEMPLATE_SERVER_URL = _env_url(
            "ESXI_TEMPLATE_SERVER_URL", "http://10.20.20.171:8000"
        )
        """URL to the ESXi template API server."""
        TOPOLOGY_GENERATOR_URL = _env_url(
            "TOPOLOGY_GENERATOR_URL", "http://10.20.20.172:8002"
        )
        """URL to the Topology Generator API server, used by the
        `generate` command to turn a natural-language prompt into a
        topology config file via an LLM."""
        TOPOLOGY_GENERATOR_TIMEOUT_SECONDS: int = 1800
        """How long to wait for a response from the Topology Generator
        API. Generation can legitimately take a while on constrained
        hardware, across multiple Ollama servers/retries server-side."""
        OVA_DEPLOY_URL = _env_url("OVA_DEPLOY_URL", "http://10.20.20.172:8003")
        """URL to the TopologyBuilderServices OVA-deploy API, used by
        ESXiConnection.deploy_virtual_machine to import an OVA straight
        from its own NFS mount to ESXi, with network wiring driven
        entirely by the request's own `network` mapping - no local
        download/upload hop on this project's side at all."""
        OVA_DEPLOY_TIMEOUT_SECONDS: int = 600
        """How long to wait for a response from the OVA-deploy API. This
        is a synchronous call that blocks for the entire server-side
        transfer, with no progress polling exposed over HTTP."""
        OVA_CHECK_TIMEOUT_SECONDS: int = 60
        """How long to wait for the OVA-deploy API to prove that an OVA can be
        read (it reads the start and the end of the file from the NFS share)."""

        LITERAL_API_VALUES: bool = (
            os.getenv("LITERAL_API_VALUES", "false").lower() == "true"
        )
        """Specifies whether to use literal API values instead of using API calls to get the existing templates."""
        LITERAL_ESXI_TEMPLATES: ClassVar[set[str]] = {
            "pfSense",
            "mint21",
            "debian",
            "OPNsense",
            "Ubuntu-Server",
            "Windows 11 Pro Education",
            "Windows 10 Pro Education",
            "Windows Server 2022 Standard",
            "Rocky 9.2",
        }
        """Literal ESXi template name values."""
        LITERAL_GNS3_TEMPLATES: ClassVar[set[str]] = {
            "VPCS",
            "Frame Relay switch",
            "Ethernet switch",
            "Cisco IOSv 15.6(1)T",
            "Ethernet hub",
            "NAT",
            "Cisco IOSvL2 15.2.1",
            "Cloud",
            "ATM switch",
        }
        """Literal GNS3 template name values."""
