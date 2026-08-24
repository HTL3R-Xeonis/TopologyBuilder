import os


class Settings:
    def __init__(self):
        self.esxi = self._Esxi()
        """Settings related to ESXi."""
        self.gns3 = self._Gns3()
        """Settings related to GNS3."""
        self.testing = self._Testing()
        """Settings related to Testing."""

    class _Esxi:
        """Settings related to ESXi."""

        IPV4_ADDRESS: str = "10.20.20.201"
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
        DATASTORE: str = "datastore1"
        """Specifies the name of the datastore to use on the ESXi client."""
        GNS3_VM_NAME = "GNS3"
        """Name of the GNS3 VM to work on."""

    class _Gns3:
        """Settings related to GNS3."""

        USERNAME: str = "gns3"
        """Username to use for the GNS3 connections."""
        PASSWORD: str | None = os.getenv("GNS3_PASSWORD", None)
        """Password to use for the GNS3 connections."""
        PROJECT_NAME: str = "tb_gns3_project"
        """Name of the GNS3 project to work on. If this project already exists on the GNS3 server, it is going to be overwritten."""
        PORT: int = 80
        """Port of the GNS3 client, where the API requests are expected."""

    class _Testing:
        """Settings related to Testing"""

        def __init__(self):
            self.github_workflow = self._GithubWorkflow()
            """Settings related to Github Workflow Testing"""

        class _GithubWorkflow:
            """Settings related to the GitHub Workflow Testing"""

            # Sets the value to True if in the GitHub workflow environment. If True, it will use the literal API values.
            LITERAL_API_VALUES = (
                os.getenv("LITERAL_API_VALUES", "false").lower() == "true"
            )
            """Specifies whether to use literal API values instead of using API calls to get the existing templates."""

            # Literal API values for ESXi templates
            LITERAL_ESXI_TEMPLATES = {
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

            # Literal API values for GNS3 templates
            LITERAL_GNS3_TEMPLATES = {
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
