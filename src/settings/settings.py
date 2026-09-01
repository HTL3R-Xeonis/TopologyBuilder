import os
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
        pass

    VERBOSITY_LEVEL: Verbosity = Verbosity.NORMAL
    """The verbosity level of the program."""
    TOPOLOGY_FILE: str = "./topology_example.yaml"
    """Path to the YAML file which represents the topology."""
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
        IGNORE_PORT_GROUPS: set[str] = {"PG_GNS3_TRUNK"}
        """Specifies which port groups not to delete on the virtual switch."""
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

        # @TODO Remove always True. Is currently set for convenience
        LITERAL_API_VALUES: bool = True or (
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
