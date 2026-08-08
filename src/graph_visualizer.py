"""
Renders a built topology graph as a plain-text tree for display in the terminal.
"""

__autor__ = "Leon Eiböck"
__date__ = "08/08/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

from src.factories import GenericNode


def render_graph(nodes: dict[str, GenericNode]) -> str:
    """
    Renders a built topology graph as a plain-text tree, listing each node's
    connections to its neighbours.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    :return: Human-readable, terminal-friendly representation of the topology
    """
    lines = []

    for name, node in nodes.items():
        lines.append(f"{name} ({node.image})")

        interfaces = list(node.interfaces.items())
        for index, (if_name, interface) in enumerate(interfaces):
            is_last = index == len(interfaces) - 1
            branch = "└──" if is_last else "├──"

            edge = interface.edge
            if edge is None:
                lines.append(f"{branch} {if_name} -- (unconnected)")
                continue

            other_interface = (
                edge.incidence_2 if edge.incidence_1 is interface else edge.incidence_1
            )
            lines.append(
                f"{branch} {if_name} -- {other_interface.node.name}:{other_interface.name}"
            )

    return "\n".join(lines)
