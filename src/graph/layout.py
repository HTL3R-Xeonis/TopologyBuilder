"""
Computes 2D node positions for rendering a built topology graph on a canvas
(e.g. a GNS3 project's scene) with a small pure-Python force-directed layout
- no external graphing/plotting library involved.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.blocks import GenericNode

_ITERATIONS = 200
_SEED = 42


def _build_adjacency(nodes: dict[str, GenericNode]) -> dict[str, set[str]]:
    """
    Builds an undirected adjacency map {node_name: {neighbour_names}} from a
    built topology graph.
    :param nodes: built topology of nodes, e.g. Graph.nodes
    :return: adjacency map of node names to their connected neighbours
    """
    adjacency: dict[str, set[str]] = {name: set() for name in nodes}
    for name, node in nodes.items():
        for interface_name in node.interfaces:
            neighbour = node.get_neighbour(interface_name)
            if neighbour is None:
                continue
            adjacency[name].add(neighbour.name)
            adjacency[neighbour.name].add(name)
    return adjacency


def _rescale(
    positions: dict[str, tuple[float, float]], width: float, height: float
) -> dict[str, tuple[float, float]]:
    """
    Uniformly rescales and centers a set of positions to fit within
    [0, width] x [0, height], preserving their relative shape (the same
    scale factor is used for both axes, so the layout isn't stretched).
    """
    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    extent = max(max_x - min_x, max_y - min_y) or 1.0

    margin = min(width, height) * 0.08
    usable = max(width, height) - 2 * margin
    scale = usable / extent

    x_offset = (width - (max_x - min_x) * scale) / 2
    y_offset = (height - (max_y - min_y) * scale) / 2

    return {
        name: (
            (x - min_x) * scale + x_offset,
            (y - min_y) * scale + y_offset,
        )
        for name, (x, y) in positions.items()
    }


def _layout(
    adjacency: dict[str, set[str]], width: float, height: float
) -> dict[str, tuple[float, float]]:
    """
    Computes 2D node positions with a Fruchterman-Reingold-style force-directed
    layout: nodes repel each other, connected nodes attract each other. The
    simulation itself is unbounded (no walls); the result is rescaled to fit
    [0, width] x [0, height] afterwards. Simulating with hard walls causes
    nodes pushed to an edge to pile up there instead of spreading out.
    :param adjacency: adjacency map of node names to their connected neighbours
    :param width: target layout width, used only for the final rescale
    :param height: target layout height, used only for the final rescale
    :return: map of node names to (x, y) positions within [0, width] x [0, height]
    """
    names = list(adjacency)
    if not names:
        return {}

    rng = random.Random(_SEED)
    spread = math.sqrt(width * height)
    positions = {
        name: (rng.uniform(0, spread), rng.uniform(0, spread)) for name in names
    }

    k = spread / math.sqrt(len(names))

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
            positions[name] = (x + dx / dist * limited, y + dy / dist * limited)

    return _rescale(positions, width, height)


def compute_node_positions(
    nodes: dict[str, GenericNode], width: float = 2000.0, height: float = 1000.0
) -> dict[str, tuple[float, float]]:
    """
    Computes a force-directed 2D layout for the given topology - useful for
    placing nodes on any canvas, e.g. a GNS3 project's scene.
    :param nodes: built topology of nodes, e.g. Graph.nodes
    :param width: canvas width
    :param height: canvas height
    :return: map of node names to (x, y) positions within [0, width] x [0, height]
    """
    adjacency = _build_adjacency(nodes)
    return _layout(adjacency, width, height)
