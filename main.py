"""
TopologyBuilder: #TODO beschreibung einfügen
"""

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.config_file_handler import ConfigFileHandler
from src.graph.graph import Graph
from src.setting_context import ObjectContext
from src.settings import Settings
from dotenv import load_dotenv

load_dotenv()


class TopologyBuilder:
    def __init__(self, config_file: str, settings: Settings = Settings()):
        ObjectContext(obj=self, settings=settings)
        c = ConfigFileHandler(config_file)
        c.validate_file()
        g = Graph(c.nodes, c.edges)

        c.validate_file()
        g = Graph(c.nodes, c.edges)
        # nodes = g.nodes
        g.visulize()

        # orchestrator = VMOrchestrator("10.20.20.201", "root", os.getenv("ESXI_PASSWORD"), "GNS3")
        # orchestrator.deploy_graph(g, "gns3", os.getenv("GNS3_PASSWORD"))


if __name__ == "__main__":
    c = ConfigFileHandler("./config_file_example.yml")
