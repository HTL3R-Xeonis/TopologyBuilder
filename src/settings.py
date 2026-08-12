import os


class Settings:
    class Esxi:
        """
        Settings related to ESXi
        """

        # Specify the name of the virtual Switch to work with
        VIRTUAL_SWITCH = "internal_network"

        # Given port groups will not be deleted from the vSwitch
        IGNORE_PORT_GROUPS = {"PG_GNS3_TRUNK"}

    class Testing:
        """
        Settings related to Testing
        """

        class GithubWorkflow:
            """
            Settings related to Testing with the GitHub Workflow
            """

            # Sets the value to True if in the GitHub workflow environment. If True, it will use the literal API values.
            LITERAL_API_VALUES = (
                os.getenv("LITERAL_API_VALUES", "false").lower() == "true"
            )

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
