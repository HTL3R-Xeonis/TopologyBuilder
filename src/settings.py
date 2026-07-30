import os


class Settings:
    class Testing:
        class GithubWorkflow:
            LITERAL_API_VALUES = (
                os.getenv("LITERAL_API_VALUES", "false").lower() == "true"
            )
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
