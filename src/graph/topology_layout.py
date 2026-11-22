"""Detects network structures and calculates reusable node positions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import atan2, cos, hypot, pi, sin

import networkx as nx


@dataclass(frozen=True)
class TopologyPattern:
    """Describes a detected network structure and its participating nodes."""

    kind: str
    nodes: tuple[str, ...]
    detail: str = ""


class TopologyLayout:
    """Positions topology nodes using recognized graph structures."""

    def __init__(self, nodes: Iterable[str], edges: Iterable[tuple[str, str]]):
        """
        :param nodes: Unique topology node names.
        :param edges: Undirected links, including parallel links and loops.
        :raises ValueError: If a link references an unknown node.
        """
        self._graph = nx.MultiGraph()
        self._graph.add_nodes_from(sorted(set(nodes)))
        for source, target in edges:
            if source not in self._graph or target not in self._graph:
                raise ValueError(f"Unknown topology link endpoint: {source} -- {target}")
            self._graph.add_edge(source, target)

        self._simple = nx.Graph(self._graph)
        self._simple.remove_edges_from(nx.selfloop_edges(self._simple))
        self._logical_positions: dict[str, tuple[float, float]] | None = None

    def get_positions(
        self, spacing: tuple[int, int] = (180, 110), origin: tuple[int, int] = (0, 0)
    ) -> dict[str, tuple[int, int]]:
        """
        Returns stable positions independent of the rendering engine.
        :param spacing: Horizontal and vertical distance per layout unit.
        :param origin: Offset applied to all positions.
        :return: Node names mapped to integer coordinates.
        :raises ValueError: If either spacing value is not positive.
        """
        if spacing[0] <= 0 or spacing[1] <= 0:
            raise ValueError("Layout spacing must be positive")
        if self._logical_positions is None:
            self._logical_positions = self._calculate_positions()
        return {
            name: (round(x * spacing[0]) + origin[0], round(y * spacing[1]) + origin[1])
            for name, (x, y) in sorted(self._logical_positions.items())
        }

    def get_patterns(self) -> list[TopologyPattern]:
        """
        Returns whole-topology, component, block and connection patterns.
        :return: Recognized graph structures with their member nodes.
        """
        patterns: list[TopologyPattern] = []
        components = sorted(nx.connected_components(self._simple), key=lambda c: (-len(c), tuple(sorted(c))))
        if len(components) > 1:
            kind = "forest" if nx.is_forest(self._simple) else "disconnected"
            patterns.append(TopologyPattern(kind, tuple(sorted(self._simple))))

        for component_nodes in components:
            component = self._simple.subgraph(component_nodes)
            blocks = [set(nodes) for nodes in nx.biconnected_components(component)]
            cyclic_blocks = [nodes for nodes in blocks if len(nodes) >= 3]
            composite_kind = self._classify(component)
            if composite_kind in {"friendship", "barbell", "lollipop"}:
                kind = composite_kind
            elif len(cyclic_blocks) > 1:
                kind = "hybrid"
            elif cyclic_blocks and len(cyclic_blocks[0]) < len(component_nodes):
                kind = f"{self._classify(component.subgraph(cyclic_blocks[0]))}_with_branches"
            else:
                kind = self._classify(component)
            patterns.append(TopologyPattern(kind, tuple(sorted(component_nodes))))
            for block in sorted(cyclic_blocks, key=lambda b: (-len(b), tuple(sorted(b)))):
                if len(block) != len(component_nodes) or kind == "hybrid":
                    patterns.append(TopologyPattern(self._classify(component.subgraph(block)), tuple(sorted(block))))

            for source, target in sorted(nx.bridges(component)):
                if self._graph.number_of_edges(source, target) == 1:
                    patterns.append(TopologyPattern("bridge", tuple(sorted((source, target)))))
            for node in sorted(nx.articulation_points(component)):
                patterns.append(TopologyPattern("articulation", (node,)))

        for source, target in sorted(self._simple.edges()):
            count = self._graph.number_of_edges(source, target)
            if count > 1:
                patterns.append(TopologyPattern("parallel_links", (source, target), str(count)))
        for node in sorted(nx.nodes_with_selfloops(self._graph)):
            patterns.append(TopologyPattern("self_loop", (node,), str(self._graph.number_of_edges(node, node))))
        return patterns

    def _classify(self, graph: nx.Graph) -> str:
        """
        Identifies the dominant structural type of a connected graph.
        :param graph: Connected undirected graph without self-loops.
        :return: Topology type identifier.
        """
        size = len(graph)
        if size <= 1:
            return "isolated"
        if size == 2:
            return "link"

        degrees = dict(graph.degree())
        if nx.is_tree(graph):
            if max(degrees.values()) == size - 1:
                return "star"
            if max(degrees.values()) <= 2:
                return "path"
            core = graph.subgraph(node for node, degree in degrees.items() if degree > 1)
            if len(core) > 1 and max(dict(core.degree()).values(), default=0) <= 2:
                return "bus_or_caterpillar"
            return "tree"

        if all(degree == 2 for degree in degrees.values()):
            return "ring"
        if graph.number_of_edges() == size * (size - 1) // 2:
            return "full_mesh"
        if size == 4 and sorted(degrees.values()) == [2, 2, 3, 3]:
            return "diamond"

        if size >= 5:
            for hub, degree in degrees.items():
                if degree != size - 1:
                    continue
                remainder = graph.subgraph(node for node in graph if node != hub)
                if nx.is_connected(remainder) and all(d == 2 for _, d in remainder.degree()):
                    return "wheel"
                if nx.is_connected(remainder) and nx.is_tree(remainder) and max(dict(remainder.degree()).values()) <= 2:
                    return "fan"
                if size % 2 == 1 and all(d == 1 for _, d in remainder.degree()):
                    return "friendship"

        if size <= 70 and any(nx.articulation_points(graph)):
            cores = [graph.subgraph(block) for block in nx.biconnected_components(graph) if len(block) >= 3]
            if len(cores) == 1 and cores[0].number_of_edges() == len(cores[0]) * (len(cores[0]) - 1) // 2:
                clique_size = len(cores[0])
                if nx.is_isomorphic(graph, nx.lollipop_graph(clique_size, size - clique_size)):
                    return "lollipop"
            if len(cores) == 2 and len(cores[0]) == len(cores[1]):
                clique_size = len(cores[0])
                if all(
                    core.number_of_edges() == len(core) * (len(core) - 1) // 2 for core in cores
                ) and nx.is_isomorphic(graph, nx.barbell_graph(clique_size, size - 2 * clique_size)):
                    return "barbell"

        grid = self._grid_mapping(graph)
        if grid is not None:
            rows, cols, _ = grid
            return "ladder" if min(rows, cols) == 2 else "grid"

        if self._prism_mapping(graph) is not None:
            return "prism"

        if size <= 32 and size & (size - 1) == 0:
            dimension = size.bit_length() - 1
            if (
                dimension >= 3
                and graph.number_of_edges() == dimension * size // 2
                and nx.is_isomorphic(graph, nx.hypercube_graph(dimension))
            ):
                return "hypercube"

        if nx.is_bipartite(graph):
            sides = nx.bipartite.color(graph)
            a = sum(side == 0 for side in sides.values())
            return "complete_bipartite" if graph.number_of_edges() == a * (size - a) else "bipartite"

        complement = nx.complement(graph)
        parts = list(nx.connected_components(complement))
        if (
            len(parts) >= 3
            and any(len(part) > 1 for part in parts)
            and all(complement.subgraph(part).number_of_edges() == len(part) * (len(part) - 1) // 2 for part in parts)
        ):
            return "complete_multipartite"

        if nx.density(graph) >= 0.65:
            return "partial_mesh"
        return "planar_mesh" if nx.check_planarity(graph)[0] else "nonplanar_mesh"

    def _grid_mapping(self, graph: nx.Graph) -> tuple[int, int, dict[str, tuple[int, int]]] | None:
        """
        Finds a rectangular grid or ladder coordinate mapping.
        :param graph: Connected graph to inspect.
        :return: Grid dimensions and node coordinates, if matched.
        """
        size = len(graph)
        if not 6 <= size <= 48:
            return None
        for rows in range(2, int(size**0.5) + 1):
            if size % rows:
                continue
            cols = size // rows
            if graph.number_of_edges() != 2 * size - rows - cols:
                continue
            matcher = nx.isomorphism.GraphMatcher(graph, nx.grid_2d_graph(rows, cols))
            if matcher.is_isomorphic():
                return rows, cols, dict(matcher.mapping)
        return None

    def _prism_mapping(self, graph: nx.Graph) -> dict[str, int] | None:
        """
        Recognizes two circular rings joined by matching links.
        :param graph: Connected graph to inspect.
        :return: Node indices of a prism, or None if no match exists.
        """
        size = len(graph)
        if not 6 <= size <= 40 or size % 2 or graph.number_of_edges() != size * 3 // 2:
            return None
        if any(degree != 3 for _, degree in graph.degree()):
            return None
        matcher = nx.isomorphism.GraphMatcher(graph, nx.circular_ladder_graph(size // 2))
        return dict(matcher.mapping) if matcher.is_isomorphic() else None

    def _cycle_order(self, graph: nx.Graph) -> list[str]:
        """
        Returns node order along the edges of a simple cycle.
        :param graph: Connected graph in which every node has degree two.
        :return: Ordered node names around the ring.
        """
        start = min(graph)
        order = [start]
        previous = None
        current = start
        while len(order) < len(graph):
            next_node = min(neighbor for neighbor in graph.neighbors(current) if neighbor != previous)
            order.append(next_node)
            previous, current = current, next_node
        return order

    def _block_positions(self, graph: nx.Graph) -> dict[str, tuple[float, float]]:
        """
        Returns a motif-specific layout for a single connected block.
        :param graph: Biconnected component or a bridge.
        :return: Local coordinates around the block center.
        """
        kind = self._classify(graph)
        nodes = sorted(graph)
        size = len(nodes)
        if size == 1:
            return {nodes[0]: (0.0, 0.0)}
        if size == 2:
            return {nodes[0]: (-1.0, 0.0), nodes[1]: (1.0, 0.0)}

        if kind in {"grid", "ladder"}:
            _, _, mapping = self._grid_mapping(graph)
            return {node: (col * 2.2, row * 2.2) for node, (row, col) in mapping.items()}

        if kind == "diamond":
            hubs = sorted(node for node in graph if graph.degree(node) == 3)
            others = sorted(node for node in graph if graph.degree(node) == 2)
            return {hubs[0]: (-2.0, 0.0), hubs[1]: (2.0, 0.0), others[0]: (0.0, -2.1), others[1]: (0.0, 2.1)}

        if kind == "prism":
            mapping = self._prism_mapping(graph)
            ring_size = size // 2
            radius = max(3.0, ring_size * 0.65)
            return {
                node: (
                    (radius if index < ring_size else radius * 0.5) * cos(2 * pi * (index % ring_size) / ring_size),
                    (radius if index < ring_size else radius * 0.5) * sin(2 * pi * (index % ring_size) / ring_size),
                )
                for node, index in mapping.items()
            }

        if kind in {"fan", "friendship"}:
            hub = next(node for node in nodes if graph.degree(node) == size - 1)
            others = graph.subgraph(node for node in nodes if node != hub)
            if kind == "fan":
                start = min(node for node in others if others.degree(node) == 1)
                order = list(nx.dfs_preorder_nodes(others, start))
                return {hub: (0.0, 0.0)} | {
                    node: (3.0 * cos(pi * index / (len(order) - 1)), 3.0 * sin(pi * index / (len(order) - 1)))
                    for index, node in enumerate(order)
                }
            pairs = sorted(tuple(sorted(group)) for group in nx.connected_components(others))
            positions = {hub: (0.0, 0.0)}
            for index, pair in enumerate(pairs):
                base_angle = 2 * pi * index / len(pairs)
                for sign, node in zip((-1, 1), pair):
                    angle = base_angle + sign * min(0.3, pi / (len(pairs) * 3))
                    positions[node] = (3.0 * cos(angle), 3.0 * sin(angle))
            return positions

        if kind == "wheel":
            hub = next(node for node in nodes if graph.degree(node) == size - 1)
            perimeter = self._cycle_order(graph.subgraph(node for node in nodes if node != hub))
            radius = max(2.4, len(perimeter) * 0.52)
            positions = {hub: (0.0, 0.0)}
            positions.update(
                {
                    node: (radius * cos(2 * pi * index / len(perimeter)), radius * sin(2 * pi * index / len(perimeter)))
                    for index, node in enumerate(perimeter)
                }
            )
            return positions

        if kind == "complete_bipartite":
            colors = nx.bipartite.color(graph)
            sides = [sorted(node for node, value in colors.items() if value == side) for side in (0, 1)]
            return {
                node: ((side * 2 - 1) * 2.0, (index - (len(group) - 1) / 2) * 2.2)
                for side, group in enumerate(sides)
                for index, node in enumerate(group)
            }

        if kind == "complete_multipartite":
            parts = sorted(
                (sorted(part) for part in nx.connected_components(nx.complement(graph))), key=lambda p: (-len(p), p)
            )
            return {
                node: ((column - (len(parts) - 1) / 2) * 2.5, (index - (len(part) - 1) / 2) * 2.2)
                for column, part in enumerate(parts)
                for index, node in enumerate(part)
            }

        if kind == "full_mesh" and size == 4:
            return {
                nodes[0]: (0.0, 0.0),
                nodes[1]: (-2.3, -1.8),
                nodes[2]: (2.3, -1.8),
                nodes[3]: (0.0, 2.2),
            }

        if kind == "ring":
            nodes = self._cycle_order(graph)
        radius = max(2.1, size * 0.52)
        return {
            node: (radius * cos(2 * pi * index / size), radius * sin(2 * pi * index / size))
            for index, node in enumerate(nodes)
        }

    def _tree_positions(self, graph: nx.Graph) -> dict[str, tuple[float, float]]:
        """
        Arranges an acyclic component into non-crossing tree levels.
        :param graph: A connected tree.
        :return: Relative coordinates for each node.
        """
        root = max(sorted(graph), key=lambda name: (graph.degree(name), -len(name)))
        levels = nx.bfs_tree(graph, root, sort_neighbors=sorted)
        depths = nx.single_source_shortest_path_length(levels, root)
        positions: dict[str, tuple[float, float]] = {}
        leaf_index = 0
        for node in nx.dfs_postorder_nodes(levels, source=root):
            children = list(levels.successors(node))
            if not children:
                x = leaf_index * 2.2
                leaf_index += 1
            else:
                x = (positions[children[0]][0] + positions[children[-1]][0]) / 2
            positions[node] = (x, depths[node] * 2.1)
        return positions

    def _candidate_positions(
        self,
        local: dict[str, tuple[float, float]],
        anchor: str,
        anchor_position: tuple[float, float],
        angle: float,
        scale: float,
    ) -> dict[str, tuple[float, float]]:
        """
        Aligns a child block with its shared articulation node.
        :param local: Local block positions.
        :param anchor: Shared node name.
        :param anchor_position: Established coordinate of the shared node.
        :param angle: Direction away from the parent block.
        :param scale: Child block size multiplier.
        :return: Global coordinates of the child block.
        """
        ax, ay = local[anchor]
        cx = sum(x for x, _ in local.values()) / len(local)
        cy = sum(y for _, y in local.values()) / len(local)
        if hypot(cx - ax, cy - ay) < 0.01:
            other = min(name for name in local if name != anchor)
            cx, cy = local[other]
        rotation = angle - atan2(cy - ay, cx - ax)
        return {
            node: (
                anchor_position[0] + ((x - ax) * cos(rotation) - (y - ay) * sin(rotation)) * scale,
                anchor_position[1] + ((x - ax) * sin(rotation) + (y - ay) * cos(rotation)) * scale,
            )
            for node, (x, y) in local.items()
        }

    def _candidate_penalty(
        self,
        candidate: dict[str, tuple[float, float]],
        existing: dict[str, tuple[float, float]],
        block: nx.Graph,
        placed_edges: set[frozenset[str]],
        anchor: str,
    ) -> float:
        """
        Scores collisions between an attached block and existing nodes or links.
        :param candidate: Proposed positions of the child block.
        :param existing: Positions of previously placed nodes.
        :param block: Graph of the child block.
        :param placed_edges: Already placed physical links.
        :param anchor: Shared articulation node.
        :return: Penalty for overlapping nodes and crossing links.
        """
        score = 0.0
        for node, position in candidate.items():
            if node == anchor:
                continue
            for existing_node, other in existing.items():
                if existing_node == anchor:
                    continue
                distance = hypot(position[0] - other[0], position[1] - other[1])
                if distance < 1.8:
                    score += 100 * (1.8 - distance) ** 2

        for source, target in block.edges():
            for link in placed_edges:
                u, v = tuple(link)
                if len({source, target, u, v}) != 4:
                    continue
                a, b = candidate[source], candidate[target]
                c, d = existing[u], existing[v]
                if self._segments_cross(a, b, c, d):
                    score += 150
        return score

    def _segments_cross(
        self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
    ) -> bool:
        """
        Checks whether two line segments intersect away from their endpoints.
        :param a: First endpoint of the first segment.
        :param b: Second endpoint of the first segment.
        :param c: First endpoint of the second segment.
        :param d: Second endpoint of the second segment.
        :return: True if the segment interiors intersect.
        """
        ab_c = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        ab_d = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0])
        cd_a = (d[0] - c[0]) * (a[1] - c[1]) - (d[1] - c[1]) * (a[0] - c[0])
        cd_b = (d[0] - c[0]) * (b[1] - c[1]) - (d[1] - c[1]) * (b[0] - c[0])
        return ab_c * ab_d < -1e-6 and cd_a * cd_b < -1e-6

    def _cyclic_positions(self, graph: nx.Graph) -> dict[str, tuple[float, float]]:
        """
        Combines connected blocks around shared articulation nodes.
        :param graph: A connected graph with at least one cycle.
        :return: Relative node coordinates for the component.
        """
        blocks = [graph.subgraph(nodes).copy() for nodes in nx.biconnected_components(graph)]
        block_ids = {node: [] for node in graph}
        for index, block in enumerate(blocks):
            for name in block:
                block_ids[name].append(index)

        root = max(
            range(len(blocks)),
            key=lambda index: (len(blocks[index]), blocks[index].number_of_edges(), tuple(sorted(blocks[index]))),
        )
        positions = self._block_positions(blocks[root])
        placed_edges: set[frozenset[str]] = {frozenset(edge) for edge in blocks[root].edges()}
        placed_blocks = {root}

        def attach(index: int, parent_anchor: str | None = None) -> None:
            """
            Adds all child blocks of an already positioned block.
            :param index: Index of the parent block.
            :param parent_anchor: Articulation node connecting the parent block.
            """
            parent = blocks[index]
            center = (
                sum(positions[node][0] for node in parent) / len(parent),
                sum(positions[node][1] for node in parent) / len(parent),
            )
            for anchor in sorted(parent):
                if anchor == parent_anchor:
                    continue
                children = [child for child in block_ids[anchor] if child not in placed_blocks]
                children.sort(key=lambda child: (-len(blocks[child]), tuple(sorted(blocks[child]))))
                if not children:
                    continue
                outward = atan2(positions[anchor][1] - center[1], positions[anchor][0] - center[0])
                if hypot(positions[anchor][0] - center[0], positions[anchor][1] - center[1]) < 0.01:
                    outward = 2 * pi * sorted(parent).index(anchor) / len(parent)

                for child_index, child in enumerate(children):
                    block = blocks[child]
                    local = self._block_positions(block)
                    offset = (child_index - (len(children) - 1) / 2) * 0.6
                    preferred = outward + offset
                    best_score = float("inf")
                    chosen = None
                    for turn in (0, pi / 5, -pi / 5, 2 * pi / 5, -2 * pi / 5, pi):
                        for scale in (1.0, 1.3, 1.7):
                            proposal = self._candidate_positions(
                                local, anchor, positions[anchor], preferred + turn, scale
                            )
                            penalty = self._candidate_penalty(proposal, positions, block, placed_edges, anchor)
                            penalty += abs(turn) * 0.2 + (scale - 1.0) * 0.3
                            if penalty < best_score:
                                best_score, chosen = penalty, proposal
                    positions.update({name: point for name, point in chosen.items() if name != anchor})
                    placed_edges.update(frozenset(edge) for edge in block.edges())
                    placed_blocks.add(child)
                    attach(child, anchor)

        attach(root)
        return positions

    def _calculate_positions(self) -> dict[str, tuple[float, float]]:
        """
        Calculates deterministic positions for all graph components.
        :return: Nonnegative coordinates for every topology node.
        """
        positions: dict[str, tuple[float, float]] = {}
        x_offset = 0.0
        for component_nodes in sorted(nx.connected_components(self._simple), key=lambda c: (-len(c), tuple(sorted(c)))):
            component = self._simple.subgraph(component_nodes)
            if len(component) == 1:
                local = {next(iter(component)): (0.0, 0.0)}
            elif nx.is_tree(component):
                local = self._tree_positions(component)
            else:
                local = self._cyclic_positions(component)
            minimum_x = min(x for x, _ in local.values())
            maximum_x = max(x for x, _ in local.values())
            minimum_y = min(y for _, y in local.values())
            for name, (x, y) in local.items():
                positions[name] = (x - minimum_x + x_offset, y - minimum_y)
            x_offset += maximum_x - minimum_x + 4.0
        return positions
