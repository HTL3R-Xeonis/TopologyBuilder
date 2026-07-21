"""
TopologyBuilder: #TODO beschreibung einfügen
"""

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.config_file_handler import ConfigFileHandler
from src.graph_builder import GraphBuilder

if __name__ == "__main__":
    c = ConfigFileHandler("./config_file_example.yml")
    c.validate_file()
    g = GraphBuilder(c.nodes, c.edges)
    print(g.build()["POP-ISP1-1"]._interfaces)
