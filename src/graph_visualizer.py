"""
Renders a built topology graph as a Graphviz diagram.
"""

__autor__ = "Leon Eiböck"
__date__ = "08/08/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import subprocess
from pathlib import Path

from src.factories import GenericNode
from src.logger_adapter import get_logger

logger = get_logger(__name__)

_RENDERABLE_FORMATS = {".png": "png", ".svg": "svg", ".pdf": "pdf"}

_ROLE_STYLES = {
    "PC": {"shape": "ellipse"},
    "VM": {"shape": "ellipse", "style": "dashed"},
    "Switch": {"shape": "box"},
    "Router": {"shape": "diamond"},
    "Firewall": {"shape": "box", "style": "bold"},
}


def to_dot(nodes: dict[str, GenericNode]) -> str:
    """
    Converts a built topology graph into Graphviz DOT source.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    :return: Graphviz DOT source describing the topology
    """
    lines = ["graph Topology {"]

    for name, node in nodes.items():
        style = _ROLE_STYLES.get(node.__class__.__name__, {})
        attrs = ", ".join(f'{key}="{value}"' for key, value in style.items())
        label = f'label="{name}\\n({node.image})"'
        lines.append(f'    "{name}" [{label}{", " + attrs if attrs else ""}];')

    seen_edges = set()
    for node in nodes.values():
        for interface in node.interfaces.values():
            edge = interface.edge
            if edge is None or id(edge) in seen_edges:
                continue
            seen_edges.add(id(edge))

            node_1 = edge.incidence_1.node.name
            node_2 = edge.incidence_2.node.name
            label = f"{edge.incidence_1.name} - {edge.incidence_2.name}"
            lines.append(f'    "{node_1}" -- "{node_2}" [label="{label}"];')

    lines.append("}")
    return "\n".join(lines)


def write_graph(nodes: dict[str, GenericNode], output_path: str) -> None:
    """
    Writes a visualization of the topology graph to the given path.
    A '.dot' extension writes raw Graphviz source. '.png', '.svg' or '.pdf'
    render an image via the 'dot' command, which must be installed separately.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    :param output_path: path to write the graph to
    """
    dot_source = to_dot(nodes)
    path = Path(output_path)
    suffix = path.suffix.lower()

    if suffix not in _RENDERABLE_FORMATS:
        path.write_text(dot_source)
        logger.info(f"Wrote Graphviz source to {path}")
        return

    image_format = _RENDERABLE_FORMATS[suffix]
    try:
        subprocess.run(
            ["dot", f"-T{image_format}", "-o", str(path)],
            input=dot_source,
            text=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise logger.alert(
            FileNotFoundError,
            "Graphviz 'dot' command not found. Install Graphviz, or use a "
            "'.dot' output path to get the raw source instead.",
        ) from e
    logger.info(f"Rendered topology graph to {path}")
