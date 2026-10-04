from __future__ import annotations

from ..connections import ESXiConnection
from ..graph import Graph
from .esxi_doctor import ESXiDoctor
from .status import Status


class Doctor:
    """
    Object to check the state of the ESXi and GNS3 host.
    """

    def __init__(self, esxi_connection: ESXiConnection) -> None:
        self.esxi_doctor = ESXiDoctor(esxi_connection)

    def is_graph_deployed(self, graph: Graph) -> list[Status]:
        statuses = []
        statuses.extend(self.esxi_doctor.is_graph_esxi_sided_deployed(graph))
        return statuses
