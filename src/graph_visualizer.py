"""
Renders a built topology graph as an ASCII node-link diagram for the terminal.
Node positions are computed with a small pure-Python force-directed layout
(no external graphing/plotting libraries involved).
"""

__autor__ = "Leon Eiböck"
__date__ = "08/08/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import math
import random
import shutil

from rich.console import Console
from rich.tree import Tree

from src.factories import GenericNode

_ITERATIONS = 200
_SEED = 42
_CHAR_ASPECT_RATIO = 2.0  # terminal character cells are roughly twice as tall as wide


def _build_adjacency(nodes: dict[str, GenericNode]) -> dict[str, set[str]]:
    """
    Builds an undirected adjacency map {node_name: {neighbour_names}} from a
    built topology graph.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    :return: adjacency map of node names to their connected neighbours
    """
    adjacency: dict[str, set[str]] = {name: set() for name in nodes}
    seen_edges = set()

    for node in nodes.values():
        for interface in node.interfaces.values():
            edge = interface.edge
            if edge is None or id(edge) in seen_edges:
                continue
            seen_edges.add(id(edge))

            name_1 = edge.incidence_1.node.name
            name_2 = edge.incidence_2.node.name
            adjacency[name_1].add(name_2)
            adjacency[name_2].add(name_1)

    return adjacency


def _layout(
    adjacency: dict[str, set[str]], width: float, height: float
) -> dict[str, tuple[float, float]]:
    """
    Computes 2D node positions with a Fruchterman-Reingold-style force-directed
    layout: nodes repel each other, connected nodes attract each other.
    :param adjacency: adjacency map of node names to their connected neighbours
    :param width: layout width
    :param height: layout height
    :return: map of node names to (x, y) positions within [0, width] x [0, height]
    """
    names = list(adjacency)
    if not names:
        return {}

    rng = random.Random(_SEED)
    positions = {
        name: (rng.uniform(0, width), rng.uniform(0, height)) for name in names
    }

    area = width * height
    k = math.sqrt(area / len(names))

    for iteration in range(_ITERATIONS):
        temperature = max(width, height) * 0.1 * (1 - iteration / _ITERATIONS)
        displacement = {name: [0.0, 0.0] for name in names}

        for i, name_a in enumerate(names):
            ax, ay = positions[name_a]
            for name_b in names[i + 1 :]:
                bx, by = positions[name_b]
                dx, dy = ax - bx, ay - by
                dist = math.hypot(dx, dy) or 0.01
                force = k * k / dist
                fx, fy = dx / dist * force, dy / dist * force
                displacement[name_a][0] += fx
                displacement[name_a][1] += fy
                displacement[name_b][0] -= fx
                displacement[name_b][1] -= fy

        seen_pairs = set()
        for name_a, neighbours in adjacency.items():
            for name_b in neighbours:
                pair = tuple(sorted((name_a, name_b)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                ax, ay = positions[name_a]
                bx, by = positions[name_b]
                dx, dy = ax - bx, ay - by
                dist = math.hypot(dx, dy) or 0.01
                force = dist * dist / k
                fx, fy = dx / dist * force, dy / dist * force
                displacement[name_a][0] -= fx
                displacement[name_a][1] -= fy
                displacement[name_b][0] += fx
                displacement[name_b][1] += fy

        for name in names:
            dx, dy = displacement[name]
            dist = math.hypot(dx, dy) or 0.01
            limited = min(dist, temperature)
            x, y = positions[name]
            x = min(width, max(0.0, x + dx / dist * limited))
            y = min(height, max(0.0, y + dy / dist * limited))
            positions[name] = (x, y)

    return positions


def _draw_line(grid: list[list[str]], x0: int, y0: int, x1: int, y1: int) -> None:
    """
    Draws a line of '.' characters between two grid cells, in place, using
    Bresenham's line algorithm. Endpoints are left untouched for node markers.
    """
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0

    while True:
        if (x, y) not in ((x0, y0), (x1, y1)):
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]) and grid[y][x] == " ":
                grid[y][x] = "."
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def _marker_for_degree(degree: int) -> str:
    """
    Picks a node marker based on how many connections it has, so hubs stand
    out from leaf nodes.
    """
    if degree >= 3:
        return "●"  # ●
    if degree == 2:
        return "o"
    if degree == 1:
        return "□"  # □
    return "·"  # ·


def render_graph(nodes: dict[str, GenericNode]) -> str:
    """
    Renders a built topology graph as an ASCII node-link diagram sized to fit
    the current terminal width.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    :return: ASCII rendering of the topology graph
    """
    adjacency = _build_adjacency(nodes)
    if not adjacency:
        return "(empty topology)"

    terminal_width, _ = shutil.get_terminal_size(fallback=(100, 24))
    width = max(60, min(terminal_width - 2, 160))

    # Lay out nodes in a square "visual" space, then compress the vertical
    # axis by the terminal's character aspect ratio (cells are taller than
    # wide) when mapping to grid rows - otherwise the topology renders far
    # too tall and narrow.
    logical_size = float(width - 12)
    positions = _layout(adjacency, logical_size, logical_size)
    height = max(20, round(logical_size / _CHAR_ASPECT_RATIO) + 4)

    # Resolve each node to a unique grid cell (nudging down on collision) before
    # drawing anything, so edges, markers and labels all agree on node positions.
    occupied: set[tuple[int, int]] = set()
    node_cell: dict[str, tuple[int, int]] = {}
    for name, (x, y) in positions.items():
        cell_x = min(width - 1, max(0, round(x)))
        cell_y = min(height - 1, max(0, round(y / _CHAR_ASPECT_RATIO)))
        while (cell_x, cell_y) in occupied and cell_y < height - 1:
            cell_y += 1
        occupied.add((cell_x, cell_y))
        node_cell[name] = (cell_x, cell_y)

    grid = [[" "] * width for _ in range(height)]

    seen_pairs = set()
    for name, neighbours in adjacency.items():
        for neighbour in neighbours:
            pair = tuple(sorted((name, neighbour)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            x0, y0 = node_cell[name]
            x1, y1 = node_cell[neighbour]
            _draw_line(grid, x0, y0, x1, y1)

    for name, (x, y) in node_cell.items():
        grid[y][x] = _marker_for_degree(len(adjacency[name]))

    for name, (x, y) in node_cell.items():
        for offset, char in enumerate(f" {name}", start=1):
            label_x = x + offset
            if (
                label_x >= width
                or (label_x, y) in occupied
                or (label_x + 1, y) in occupied
            ):
                break
            if grid[y][label_x] not in (" ", "."):
                break
            grid[y][label_x] = char

    return "\n".join("".join(row).rstrip() for row in grid if "".join(row).strip())


def print_connection_tree(nodes: dict[str, GenericNode]) -> None:
    """
    Prints a colored tree listing each device and the devices it is connected
    to, via its interfaces.
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    """
    tree = Tree("[bold]Topology[/bold]")

    for name, node in nodes.items():
        device = tree.add(f"[bold cyan]{name}[/bold cyan] [dim]({node.image})[/dim]")

        interfaces = list(node.interfaces.items())
        if not interfaces:
            device.add("[dim](no interfaces)[/dim]")
            continue

        for if_name, interface in interfaces:
            edge = interface.edge
            if edge is None:
                device.add(f"[yellow]{if_name}[/yellow] [dim]-- unconnected[/dim]")
                continue

            other_interface = (
                edge.incidence_2 if edge.incidence_1 is interface else edge.incidence_1
            )
            device.add(
                f"[yellow]{if_name}[/yellow] [dim]->[/dim] "
                f"[bold green]{other_interface.node.name}[/bold green]"
                f"[dim]:{other_interface.name}[/dim]"
            )

    Console().print(tree)
