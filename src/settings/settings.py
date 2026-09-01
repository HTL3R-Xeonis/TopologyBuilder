import os

import yaml
from loguru import logger

from .verbosity import Verbosity
from dotenv import load_dotenv

load_dotenv()


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

        if "username" in gns3:
            Settings.GNS3.USERNAME = gns3["username"]
        if "project_name" in gns3:
            Settings.GNS3.PROJECT_NAME = gns3["project_name"]
        if "port" in gns3:
            Settings.GNS3.PORT = gns3["port"]
        if "parent_interface" in gns3:
            Settings.GNS3.PARENT_INTERFACE = gns3["parent_interface"]

        api = data.get("api", {})
        if "esxi_template_server_url" in api:
            Settings.API.ESXI_TEMPLATE_SERVER_URL = api["esxi_template_server_url"]
        if "gns3_template_server_url" in api:
            Settings.API.GNS3_TEMPLATE_SERVER_URL = api["gns3_template_server_url"]

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
        VIRTUAL_SWITCH: str = "internal_network"
        """Specifies the virtual switch to use on the ESXi client."""
        TRUNK_PORT_GROUP: str = "PG_GNS3_TRUNK"
        """Name of the port group carrying the GNS3 VM's VLAN trunk NIC. Must
        accept promiscuous mode/MAC changes/forged transmits, which GNS3's
        Cloud nodes need to bridge topology devices through it - ESXi's
        default security policy silently drops that traffic otherwise."""
        IGNORE_PORT_GROUPS: set[str] = {"PG_GNS3_TRUNK"}
        """Specifies which port groups not to delete on the virtual switch."""
        RESERVED_PORT_GROUPS: set[str] = {"VM Network", "Management Network"}
        """ESXi's own built-in port groups (present on essentially every
        install, not created by this tool). Always protected from deletion
        regardless of IGNORE_PORT_GROUPS' contents - deleting 'Management
        Network' in particular can sever the host's own management access."""
        DATASTORE: str = "datastore1 (2)"
        """Specifies the name of the datastore to use on the ESXi client."""
        GNS3_VM_NAME = "GNS3 (1)"
        """Name of the GNS3 VM to work on."""

    class GNS3:
        """Settings related to GNS3."""

        USERNAME: str = "gns3"
        """Username to use for the GNS3 connections."""
        PASSWORD: str | None = os.getenv("GNS3_PASSWORD", None)
        """Password to use for the GNS3 connections."""
        PROJECT_NAME: str = "tb_gns3_project"
        """Name of the GNS3 project to work on. If this project already exists on the GNS3 server, it is going to be overwritten."""
        PORT: int = 80
        """Port of the GNS3 client, where the API requests are expected."""
        PARENT_INTERFACE: str = "eth1"
        """Name of the interface of the GNS3 VM to create and delete the subinterfaces."""

    class API:
        """Settings related to API requests."""

        GNS3_TEMPLATE_SERVER_URL = "http://10.20.20.171:8001"
        """URL to the GNS3 template API server."""
        ESXI_TEMPLATE_SERVER_URL = "http://10.20.20.171:8000"
        """URL to the ESXi template API server."""

        LITERAL_API_VALUES: bool = (
            os.getenv("LITERAL_API_VALUES", "false").lower() == "true"
        )
        """Specifies whether to use literal API values instead of using API calls to get the existing templates."""
        LITERAL_ESXI_TEMPLATES: set[str] = {
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
        LITERAL_GNS3_TEMPLATES: set[str] = {
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
