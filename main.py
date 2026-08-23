"""
TopologyBuilder: #TODO beschreibung einfügen
"""

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.config_file_handler import ConfigFileHandler
from src.graph.graph import Graph
from src.vm_orchestrator.vm_orchestrator import VMOrchestrator

if __name__ == "__main__":
    c = ConfigFileHandler("./config_file_example.yml")
    c.validate_file()
    g = Graph(c.nodes, c.edges)
    nodes = g.nodes
    g.visulize()

    orchestrator = VMOrchestrator("10.20.20.201", "root", "cisco123!", "GNS3")
    orchestrator.deploy_graph(g, "gns3", "gns3")
