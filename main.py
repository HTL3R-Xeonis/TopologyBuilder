"""
TopologyBuilder: #TODO beschreibung einfügen
"""

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.config_file_handler import ConfigFileHandler
from src.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from src.graph_builder import GraphBuilder
from src.vm_orchestrator import VMOrchestrator

if __name__ == "__main__":
    c = ConfigFileHandler("./config_file_example.yml")
    c.validate_file()
    g = GraphBuilder(c.nodes, c.edges)
    nodes = g.build()

    esxi_conn = VMOrchestrator("10.20.20.201", username="root", password="cisco123!")
    gns3_conn = GNS3VMInterfaceSetup()
    gns3_conn.connect(esxi_conn.get_vm_ip_address("GNS3"))
    gns3_conn.write_config_file(nodes)
