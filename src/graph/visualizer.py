"""Renders graph topologies and their links in the terminal."""

from __future__ import annotations

import os
import sys
from collections import Counter
from itertools import pairwise
from math import hypot
from typing import TYPE_CHECKING

from loguru import logger
from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from src.graph.graph import Graph


class BrailleCanvas:
    """Draws diagonal lines using the terminal's Braille character grid."""

    _DOTS = ((0, 1, 2, 6), (3, 4, 5, 7))

    def __init__(self, width: int, height: int):
        """
        :param width: Width in terminal characters.
        :param height: Height in terminal rows.
        :raises ValueError: If the canvas dimensions are invalid.
        """
        if width < 1 or height < 1:
            raise ValueError("Braille canvas dimensions must be positive")
        self.width = width
        self.height = height
        self._dots = [[0] * width for _ in range(height)]

    def dot(self, x: int, y: int) -> None:
        """
        Marks a sub-character drawing position.
        :param x: Horizontal Braille-pixel coordinate.
        :param y: Vertical Braille-pixel coordinate.
        """
        if 0 <= x < self.width * 2 and 0 <= y < self.height * 4:
            self._dots[y // 4][x // 2] |= 1 << self._DOTS[x % 2][y % 4]

    def line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """
        Draws a continuous straight segment in Braille pixels.
        :param start: Start coordinate in Braille pixels.
        :param end: End coordinate in Braille pixels.
        """
        x1, y1 = start
        x2, y2 = end
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx, sy = (1 if x1 < x2 else -1), (1 if y1 < y2 else -1)
        error = dx - dy
        while True:
            self.dot(x1, y1)
            if (x1, y1) == (x2, y2):
                break
            doubled = 2 * error
            if doubled > -dy:
                error -= dy
                x1 += sx
            if doubled < dx:
                error += dx
                y1 += sy

    def characters(self) -> list[list[str]]:
        """
        Returns the rasterized terminal character matrix.
        :return: Rows containing Braille strokes and blank cells.
        """
        return [[chr(0x2800 + mask) if mask else " " for mask in row] for row in self._dots]


class GraphVisualizer:
    """Displays graph connections without altering their reusable layout coordinates."""

    def __init__(self, graph: Graph):
        """
        :param graph: Topology graph to display.
        """

        self._ROLE_COLORS = {"PC": "cyan", "VM": "cyan", "SWITCH": "green", "ROUTER": "blue", "FW": "red"}
        self._graph = graph

    def render(self, show_interfaces: bool = False, interactive: bool = True) -> None:
        """
        Displays the topology as a Braille diagram.
        :param show_interfaces: Whether to label interfaces beside their links.
        :param interactive: Whether to navigate oversized diagrams in the terminal.
        :raises OSError: If interactive terminal input cannot be configured.
        """
        self._render_braille(show_interfaces, interactive)

    def _node_boxes(self, positions: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int, int, int]]:
        """
        Returns terminal cell rectangles for positioned graph nodes.
        :param positions: Node centers in terminal cell coordinates.
        :return: Rectangles as left, top, right and bottom coordinates.
        """
        rectangles = {}
        for name, (x, y) in positions.items():
            width = len(name) + 4
            left = x - width // 2
            rectangles[name] = (left, y - 1, left + width - 1, y + 1)
        return rectangles

    def _terminal_positions(self) -> dict[str, tuple[int, int]]:
        """
        Returns stable terminal positions independent of the viewport size.
        :return: Node centers in terminal cell coordinates.
        """
        original = self._graph.get_node_positions(spacing=(14, 8))
        if not original:
            return {}
        xs = [point[0] for point in original.values()]
        ys = [point[1] for point in original.values()]
        max_label_width = max(map(len, original)) + 4
        scale_x, scale_y = 1.0, 1.0
        for _ in range(15):
            positions = {
                name: (round((x - min(xs)) * scale_x) + max_label_width, round((y - min(ys)) * scale_y) + 3)
                for name, (x, y) in original.items()
            }
            rectangles = self._node_boxes(positions)
            if not any(
                a[0] <= b[2] + 1 and b[0] <= a[2] + 1 and a[1] <= b[3] + 1 and b[1] <= a[3] + 1
                for first, a in rectangles.items()
                for second, b in rectangles.items()
                if first < second
            ):
                return positions
            scale_x *= 1.12
            scale_y *= 1.12
        return positions

    def _endpoint(self, source: tuple[int, int, int, int], target: tuple[float, float]) -> tuple[int, int]:
        """
        Finds the external attachment point of a connection at a node box.
        :param source: Source rectangle in terminal cell coordinates.
        :param target: Direction target in Braille-pixel coordinates.
        :return: Attachment point in Braille-pixel coordinates.
        """
        left, top, right, bottom = source
        center_x = left + right + 1  # two pixels per terminal cell
        center_y = (top + bottom + 1) * 2  # four pixels per terminal cell
        dx, dy = target[0] - center_x, target[1] - center_y
        if not (dx or dy):
            dx = 1
        half_width = right - left + 1
        half_height = (bottom - top + 1) * 2
        factor = min(half_width / abs(dx) if dx else float("inf"), half_height / abs(dy) if dy else float("inf"))
        return round(center_x + dx * factor), round(center_y + dy * factor)

    def _draw_edges(
        self, canvas: BrailleCanvas, rectangles: dict[str, tuple[int, int, int, int]]
    ) -> tuple[set[tuple[int, int]], list[list[tuple[int, int]]]]:
        """
        Draws each physical link between the boundaries of its two nodes.
        :param canvas: Braille raster receiving connections.
        :param rectangles: Terminal rectangles for all graph nodes.
        :return: Crossing cells and the raster paths of all physical links.
        """
        crossings: set[tuple[int, int]] = set()
        previous: list[tuple[str, str, list[tuple[int, int]]]] = []
        paths: list[list[tuple[int, int]]] = []
        links = self._graph._edges
        counts = Counter(frozenset((a, b)) for a, _, b, _ in links)
        sequence: Counter[frozenset[str]] = Counter()
        for source, _, target, _ in links:
            first = rectangles[source]
            if source == target:
                # A self-loop is an independent line outside its node box.
                right, top, bottom = first[2], first[1], first[3]
                ordinal = sequence[frozenset((source, target))]
                distance = 4 + ordinal * 3
                path = [
                    ((right + 1) * 2, top * 4 + 2),
                    ((right + distance) * 2, top * 4 + 2),
                    ((right + distance) * 2, (bottom + 1) * 4 - 2),
                    ((right + 1) * 2, (bottom + 1) * 4 - 2),
                ]
            else:
                second = rectangles[target]
                cx1, cy1 = first[0] + first[2] + 1, (first[1] + first[3] + 1) * 2
                cx2, cy2 = second[0] + second[2] + 1, (second[1] + second[3] + 1) * 2
                pair = frozenset((source, target))
                index = sequence[pair]
                lateral_offset = index - (counts[pair] - 1) / 2
                length = hypot(cx2 - cx1, cy2 - cy1) or 1
                perpendicular = (-(cy2 - cy1) / length, (cx2 - cx1) / length)
                curve_distance = lateral_offset * 12
                middle = (
                    (cx1 + cx2) / 2 + perpendicular[0] * curve_distance,
                    (cy1 + cy2) / 2 + perpendicular[1] * curve_distance,
                )
                start = self._endpoint(first, middle if counts[pair] > 1 else (cx2, cy2))
                end = self._endpoint(second, middle if counts[pair] > 1 else (cx1, cy1))
                if counts[pair] == 1:
                    path = [start, end]
                else:
                    path = [
                        (
                            round(
                                (1 - t / 24) ** 2 * start[0]
                                + 2 * (1 - t / 24) * (t / 24) * middle[0]
                                + (t / 24) ** 2 * end[0]
                            ),
                            round(
                                (1 - t / 24) ** 2 * start[1]
                                + 2 * (1 - t / 24) * (t / 24) * middle[1]
                                + (t / 24) ** 2 * end[1]
                            ),
                        )
                        for t in range(25)
                    ]
            for prior_source, prior_target, previous_path in previous:
                if len({source, target, prior_source, prior_target}) < 4:
                    continue
                for head, tail in pairwise(path):
                    for other_head, other_tail in pairwise(previous_path):
                        crossing = self._segment_crossing(head, tail, other_head, other_tail)
                        if crossing is not None:
                            crossings.add((crossing[0] // 2, crossing[1] // 4))
            for head, tail in pairwise(path):
                canvas.line(head, tail)
            previous.append((source, target, path))
            paths.append(path)
            sequence[frozenset((source, target))] += 1
        return crossings, paths

    def _segment_crossing(
        self, a: tuple[int, int], b: tuple[int, int], c: tuple[int, int], d: tuple[int, int]
    ) -> tuple[int, int] | None:
        """
        Locates an interior intersection of two distinct line segments.
        :param a: First segment start.
        :param b: First segment end.
        :param c: Second segment start.
        :param d: Second segment end.
        :return: Intersection in Braille pixels, or None.
        """
        ax, ay = a
        rx, ry = b[0] - ax, b[1] - ay
        sx, sy = d[0] - c[0], d[1] - c[1]
        denominator = rx * sy - ry * sx
        if not denominator:
            return None
        px, py = c[0] - ax, c[1] - ay
        t = (px * sy - py * sx) / denominator
        u = (px * ry - py * rx) / denominator
        if 0.001 < t < 0.999 and 0.001 < u < 0.999:
            return round(ax + t * rx), round(ay + t * ry)
        return None

    def _label_candidates(self, path: list[tuple[int, int]], label: str, source_end: bool) -> list[tuple[int, int]]:
        """
        Suggests terminal cells beside the selected end of a connection.
        :param path: Link geometry in Braille pixels.
        :param label: Interface name to position.
        :param source_end: Whether to start at the source node.
        :return: Candidate top-left positions ordered by proximity to the node.
        """
        points = path if source_end else list(reversed(path))
        segments = []
        distance = 0.0
        for start, end in pairwise(points):
            x1, y1 = start[0] / 2, start[1] / 4
            x2, y2 = end[0] / 2, end[1] / 4
            length = hypot(x2 - x1, y2 - y1)
            if length:
                segments.append((distance, length, x1, y1, x2, y2))
                distance += length
        if not segments:
            return []

        candidates: list[tuple[int, int]] = []
        # A label must remain on its own half of the physical connection.
        for desired in (2, 3, 4, 6, 8, 11, 15, 20, 26):
            if desired > distance * 0.48:
                continue
            for offset, length, x1, y1, x2, y2 in segments:
                if desired <= offset + length:
                    ratio = (desired - offset) / length
                    x = x1 + ratio * (x2 - x1)
                    y = y1 + ratio * (y2 - y1)
                    dx, dy = (x2 - x1) / length, (y2 - y1) / length
                    break
            else:
                continue
            for padding in (1, 2, 3, 4):
                # Horizontal and steep links need different sides for readable text.
                for side in (-1, 1):
                    candidates.append((round(x - len(label) / 2), round(y + side * (padding + 1))))
                    candidates.append((round(x + padding) if side > 0 else round(x - len(label) - padding), round(y)))
                    if abs(dx) > 0.3 and abs(dy) > 0.3:
                        candidates.append(
                            (
                                round(x + side * (-dy) * (padding + len(label) / 3) - len(label) / 2),
                                round(y + side * dx * (padding + 1)),
                            )
                        )
        return list(dict.fromkeys(candidates))

    def _draw_interface_labels(
        self, image: list[list[str]], paths: list[list[tuple[int, int]]]
    ) -> list[tuple[int, int, int]]:
        """
        Places interface names beside their respective link endpoints.
        :param image: Terminal cells containing links and node boxes.
        :param paths: Raster paths ordered like the graph's physical connections.
        :return: Cell ranges to color as interface labels.
        """
        height, width = len(image), len(image[0])
        pending = []
        for (source, source_if, target, target_if), path in zip(self._graph._edges, paths):
            for node, label, source_end in ((source, source_if, True), (target, target_if, False)):
                if label:
                    pending.append((node, str(label), self._label_candidates(path, str(label), source_end)))

        colored: list[tuple[int, int, int]] = []
        while pending:
            valid = []
            for node, label, candidates in pending:
                positions = [
                    (x, y)
                    for x, y in candidates
                    if 0 <= y < height
                    and 0 <= x
                    and x + len(label) <= width
                    and all(cell == " " for cell in image[y][max(0, x - 1) : min(width, x + len(label) + 1)])
                ]
                valid.append((node, label, positions))
            # Prioritize crowded endpoints instead of letting easy labels occupy their space.
            index = min(range(len(valid)), key=lambda i: (len(valid[i][2]), -len(valid[i][1]), i))
            node, label, positions = valid[index]
            pending.pop(index)
            if not positions:
                logger.warning("Cannot place interface label {}:{} without overlapping the graph", node, label)
                continue
            x, y = positions[0]
            image[y][x : x + len(label)] = list(label)
            colored.append((y, x, x + len(label)))
        return colored

    def _render_braille(self, show_interfaces: bool = False, interactive: bool = True) -> None:
        """
        Renders the topology and optionally opens a navigable viewport.
        :param show_interfaces: Whether to show interfaces next to their links.
        :param interactive: Whether to enable navigation when the terminal is too small.
        :raises OSError: If interactive terminal input cannot be configured.
        """
        console = Console()
        positions = self._terminal_positions()
        if not positions:
            console.print("(empty topology)")
            return
        if show_interfaces:
            margin = (
                max((len(str(interface)) for _, a, _, b in self._graph._edges for interface in (a, b)), default=0) + 3
            )
            positions = {name: (x + margin, y + 4) for name, (x, y) in positions.items()}
        else:
            margin = 0
        rectangles = self._node_boxes(positions)
        width = max(right for _, _, right, _ in rectangles.values()) + 2 + margin
        height = max(bottom for _, _, _, bottom in rectangles.values()) + 2 + (5 if show_interfaces else 0)
        for source, _, target, _ in self._graph._edges:
            if source == target:
                width = max(width, rectangles[source][2] + 14)
        canvas = BrailleCanvas(width, height)
        crossings, paths = self._draw_edges(canvas, rectangles)
        image = canvas.characters()
        for x, y in crossings:
            if 0 <= x < width and 0 <= y < height:
                image[y][x] = "×"

        styles: list[tuple[int, int, int, str]] = []
        for name, (left, top, right, bottom) in rectangles.items():
            border = "─" * (right - left - 1)
            for row, content in ((top, f"┌{border}┐"), (top + 1, f"│ {name} │"), (bottom, f"└{border}┘")):
                image[row][left : right + 1] = list(content)
            color = self._ROLE_COLORS.get(self._graph.nodes[name].role, "white")
            styles.append((top + 1, left + 2, left + 2 + len(name), color))
        if show_interfaces:
            styles.extend(
                (row, left, right, "bright_yellow") for row, left, right in self._draw_interface_labels(image, paths)
            )

        # The coordinates and raster never depend on the terminal dimensions.
        # Only the visible portion changes when navigating the diagram.
        if (
            interactive
            and console.is_terminal
            and sys.stdin.isatty()
            and (width > console.size.width or height > console.size.height)
        ):
            self._show_viewport(console, image, styles)
        else:
            console.print(self._text_region(image, styles, 0, 0, width, height), soft_wrap=True)
            if crossings:
                console.print("× = crossing of separate links (not a junction)", style="dim")

    def _text_region(
        self,
        image: list[list[str]],
        styles: list[tuple[int, int, int, str]],
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> Text:
        """
        Returns a styled, cropped region of the diagram.
        :param image: Complete diagram character matrix.
        :param styles: Styled cell ranges for labels and node names.
        :param x: Leftmost visible column.
        :param y: First visible row.
        :param width: Visible number of columns.
        :param height: Visible number of rows.
        :return: Rich text preserving the colors of visible labels.
        """
        text = Text(no_wrap=True, overflow="ignore")
        start = 0
        for row_number in range(y, min(y + height, len(image))):
            if row_number > y:
                text.append("\n")
                start += 1
            row = "".join(image[row_number][x : x + width])
            text.append(row)
            for style_row, left, right, color in styles:
                if style_row != row_number:
                    continue
                visible_left = max(x, left)
                visible_right = min(x + len(row), right)
                if visible_left < visible_right:
                    text.stylize(color, start + visible_left - x, start + visible_right - x)
            start += len(row)
        return text

    def _show_viewport(self, console: Console, image: list[list[str]], styles: list[tuple[int, int, int, str]]) -> None:
        """
        Opens a stable, scrollable terminal view of an oversized diagram.
        :param console: Active Rich console.
        :param image: Complete diagram character matrix.
        :param styles: Styled cell ranges for labels and node names.
        :raises OSError: If the terminal cannot enter character-input mode.
        """
        import contextlib

        from rich.console import Group
        from rich.live import Live

        old_settings = None
        try:
            if os.name != "nt":
                import termios
                import tty

                descriptor = sys.stdin.fileno()
                old_settings = termios.tcgetattr(descriptor)
                tty.setcbreak(descriptor)

            # Live redraws from the screen origin and flushes complete frames.
            # A spare column avoids terminal auto-wrap at the right edge.
            with Live(
                console=console, screen=True, auto_refresh=False, redirect_stdout=False, redirect_stderr=False
            ) as live:
                x = y = 0
                last_frame = None
                while True:
                    terminal_width, terminal_height = console.size
                    view_width = max(1, terminal_width - 1)
                    view_height = max(1, terminal_height - 1)
                    max_x = max(0, len(image[0]) - view_width)
                    max_y = max(0, len(image) - view_height)
                    x, y = min(x, max_x), min(y, max_y)

                    frame = (x, y, terminal_width, terminal_height)
                    if frame != last_frame:
                        content = self._text_region(image, styles, x, y, view_width, view_height)
                        visible_rows = min(view_height, len(image) - y)
                        if visible_rows < view_height:
                            content.append("\n" * (view_height - visible_rows))
                        status = Text(
                            f"Q/Esc: exit  Arrows: pan  PgUp/PgDn: page  Home/End: corners"
                            f"  [{x + 1}/{max_x + 1}, {y + 1}/{max_y + 1}]",
                            style="reverse",
                            no_wrap=True,
                            overflow="crop",
                        )
                        status.truncate(view_width, overflow="crop")
                        status.pad_right(view_width)
                        live.update(Group(content, status), refresh=True)
                        last_frame = frame

                    key = self._read_navigation_key()
                    if key == "quit":
                        return
                    if key == "left":
                        x = max(0, x - 4)
                    elif key == "right":
                        x = min(max_x, x + 4)
                    elif key == "up":
                        y = max(0, y - 2)
                    elif key == "down":
                        y = min(max_y, y + 2)
                    elif key == "page_up":
                        y = max(0, y - view_height)
                    elif key == "page_down":
                        y = min(max_y, y + view_height)
                    elif key == "home":
                        x = y = 0
                    elif key == "end":
                        x, y = max_x, max_y
        finally:
            if old_settings is not None:
                with contextlib.suppress(OSError):
                    termios.tcsetattr(descriptor, termios.TCSADRAIN, old_settings)

    def _read_navigation_key(self) -> str:
        """
        Reads a navigation command from the active terminal.
        :return: Navigation action name or an empty string for unsupported keys.
        :raises OSError: If reading terminal input fails.
        """
        if os.name == "nt":
            import msvcrt

            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                return {
                    "K": "left",
                    "M": "right",
                    "H": "up",
                    "P": "down",
                    "I": "page_up",
                    "Q": "page_down",
                    "G": "home",
                    "O": "end",
                }.get(msvcrt.getwch(), "")
            return "quit" if key.lower() == "q" or key == "\x1b" else ""

        import select

        descriptor = sys.stdin.fileno()
        key = os.read(descriptor, 1)
        if key in (b"q", b"Q"):
            return "quit"
        if key != b"\x1b":
            return ""
        if not select.select([descriptor], [], [], 0.05)[0]:
            return "quit"
        if os.read(descriptor, 1) not in (b"[", b"O"):
            return ""
        sequence = b""
        for _ in range(5):
            if not select.select([descriptor], [], [], 0.05)[0]:
                break
            character = os.read(descriptor, 1)
            sequence += character
            if character.isalpha() or character == b"~":
                break
        return {
            b"A": "up",
            b"B": "down",
            b"C": "right",
            b"D": "left",
            b"H": "home",
            b"F": "end",
            b"1~": "home",
            b"4~": "end",
            b"5~": "page_up",
            b"6~": "page_down",
        }.get(sequence, "")
