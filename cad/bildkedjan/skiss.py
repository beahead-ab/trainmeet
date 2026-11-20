"""Profile Skiss: a hand-drawn track plan becomes a module's track plan (bildkedjan, Ritningar
och skisser: the profile table; lärdomarna, Handritad skiss som underlag; #89 del c2).

A sketch is a sheet of paper, scanned or photographed, with the modules' frames drawn as thin
lines, the tracks in thick black ink, and around them coloured pencil, text and thin leader
lines from the text to what it names. In order:

1. Document rectification (prepare): the paper is found as the large light four-sided thing in
   the photo and straightened to a rectangle; a scan already is one.
2. The frames (frames): thin, long, straight dark lines (Hough) are the frames' sides, and the
   areas they close are the frames. The owner picks the frame that is this module, and its
   corners give the scale: the module's length and width are the owner's (± 20 mm).
3. Ink out of colour (ink): dark and without colour is ink; coloured pencil is coloured, and
   pencil text and leader lines are grey and thin. What is thinner than a track, opened away
   (lärdomarna: an opening of about 7 px at 2200 px), is a frame, a leader line or text.
4. Skeleton and graph (graph): the tracks' ink thinned to a line a pixel wide and made a graph:
   nodes where 1 end (a track's end), 3 ends (a switch) or 4 ends (a crossing) meet. Short
   spurs of the thinning and text left over (short pieces with free ends) are sorted away. A
   small ring with many tracks on it is a turntable.
5. The module (read): the graph in the frame, cut at its gables, in the module's millimetres.
   A node with 3 ends is a switch: its stem is the end that points away from the other two,
   its straight leg the one that runs on most nearly from the stem. 4 ends are a crossing, 2 a
   joint, 1 at a gable a gable track and 1 inside an end. Two switches whose nodes the ink has
   merged into one with 4 ends cannot be told from a crossing by code: they are asked (the AI
   with fixed answers, or the owner), and answered two switches they are drawn as two (part
   c3). A node with 3 ends in a turntable's pit is the turntable's, not a switch (part c3).
6. Ren geometri (geometry): each track redrawn as straights and arcs that follow the sketch,
   within ± SKETCH_MM: a sketch is not measured, so every measure is a proposal from the sketch
   until the owner measures or approves (CAD-17).
"""

from __future__ import annotations

import copy
import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad import curves, smoothing, switches
from cad.bildkedjan.build import one_arc
from cad.bildkedjan.camera import Array, homography
from cad.bildkedjan.paths import crossings as ring_count
from cad.bildkedjan.paths import thin
from cad.curves import Seg
from cad.editor import Drawing
from cad.editor import Node as DrawingNode
from cad.editor import Piece as DrawingPiece
from cad.editor import Switch as DrawingSwitch
from contracts.cad import (
    Certainty,
    DrawingSource,
    DrawnLine,
    GableEnd,
    GraphOrigin,
    GraphSource,
    Smoothing,
)
from contracts.station_model import NodeType, Point, SwitchType

PROFILE = "skiss"
SKETCH_MM = 20.0
"""A sketch's measures: ± 20 mm (bildkedjan, the profile table; lärdomarna)."""
WORK_SIDE = 2400
"""The sheet's long side while it is read, px: the scans are about 2200 px."""
SHEET_SHARE = 0.3
"""The paper fills at least this share of a photo of it."""
FRAME_SHARE = 0.012
"""A frame closes at least this share of the sheet."""
LINE_SHARE = 0.08
ALONG_TRACK = 0.5
"""A frame's side is at least this share of the sheet's shorter side."""
INK_DARK = 0.55
"""Ink is darker than this share of the paper's light."""
INK_GREY = 70
"""and greyer than this saturation (0–255): coloured pencil is not ink."""
TRACK_MIN_PX = 5
"""A track's stroke is at least this wide on the sheet as read: thinner is a frame, a leader
line or text."""
MM_PER_PX_READ = 1.0
"""The frame is read at 1 px per mm."""
MARGIN_MM = 40.0
JOIN_MM = 14.0
"""Junction pixels closer than this are one node."""
MERGE_MM = 28.0
CROSS_MM = 220.0
CROSS_ALIGN = 12.0
CROSS_MIN_ANGLE = 3.0
"""Two nodes with 3 ends this close, joined by their own short piece, are one with 4: a
crossing as the ink draws it, or two switches."""
SPUR_MM = 30.0
LOOP_MM = 120.0
"""A piece from a node back to itself shorter than this is a hole in the ink."""
"""A piece with a free end shorter than this is a spur of the thinning or a letter."""
PIECE_MIN_MM = 60.0
HIDDEN_MM = 150.0
"""A track hidden for at most this long goes on (under a bridge drawn over it)."""
HIDDEN_ALIGN = 20.0
"""A piece of ink alone, shorter than this, is text."""
GABLE_MM = 25.0
"""A track's end this close to a gable goes through it."""
RING_MM = 260.0
"""A ring of track smaller than this across, round, with RING_SPOKES tracks or more on it, is a
turntable; a scissors crossover is a ring of four nodes with four tracks on it."""
RING_SPOKES = 6
PIT_MM = 180.0
"""A turntable's pit is at most this wide to its middle, mm."""
RING_ROUND = 0.25
FIT_MM = 4.0
"""The sketch's lines are redrawn within this, before the ± SKETCH_MM."""
SPLIT_DEPTH = 4
"""At most 2⁴ straights and arcs for a piece the smooth fit cannot follow."""
END_MM = 15.0
"""The ink this near a node is bent by the thinning: a piece is judged inside it, mm."""
HEADING_MM = 40.0


@dataclass(frozen=True)
class Sheet:
    pixels: NDArray[Any]
    """The sheet straightened, BGR."""
    frames: list[Array]
    """Each frame's four corners in the sheet's px, clockwise from the top left."""
    paper: float
    """The paper's light, 0–255."""
    scale: float
    """The sheet's px per px of the photo as sent."""


def _clockwise(corners: Array) -> Array:
    centre = corners.mean(axis=0)
    angles = np.arctan2(corners[:, 1] - centre[1], corners[:, 0] - centre[0])
    ordered = corners[np.argsort(angles)]
    first = int(np.argmin(ordered.sum(axis=1)))
    found: Array = np.roll(ordered, -first, axis=0)
    return found


def _quad(contour: NDArray[Any]) -> Array | None:
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    for share in np.linspace(0.005, 0.12, 48):
        approx = cv2.approxPolyDP(hull, float(share) * perimeter, True)
        if len(approx) == 4:
            return _clockwise(approx.reshape(4, 2).astype(np.float64))
    return None


def prepare(pixels: NDArray[Any]) -> Sheet:
    """The sheet straightened, and its frames."""
    h, w = pixels.shape[:2]
    factor = min(1.0, WORK_SIDE / max(h, w))
    work = cv2.resize(pixels, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    # The paper: the large light area, when the sheet was photographed on something darker.
    _, light = cv2.threshold(
        cv2.GaussianBlur(gray, (0, 0), 3), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    light = cv2.morphologyEx(
        light, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    )
    contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    sheet = work
    if contours:
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        quad = _quad(largest)
        if quad is not None and SHEET_SHARE * h * w * factor * factor <= area < 0.97 * gray.size:
            top = np.linalg.norm(quad[1] - quad[0])
            side = np.linalg.norm(quad[3] - quad[0])
            width, height = round(float(top)), round(float(side))
            target = np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float64)
            matrix = homography(quad, target)
            sheet = cv2.warpPerspective(work, matrix, (width, height), flags=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(sheet, cv2.COLOR_BGR2GRAY)
    paper = float(np.percentile(gray, 90))
    return Sheet(sheet, frames(sheet, paper), paper, factor)


def ink(pixels: NDArray[Any], paper: float) -> NDArray[Any]:
    """Dark and grey: the ink, as 255."""
    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)
    dark = hsv[..., 2] < INK_DARK * paper
    grey = hsv[..., 1] < INK_GREY
    found: NDArray[Any] = np.where(dark & grey, 255, 0).astype(np.uint8)
    return found


def tracks_ink(pixels: NDArray[Any], paper: float) -> NDArray[Any]:
    """The ink as wide as a track: thinner lines (frames, leader lines, text) opened away."""
    found = ink(pixels, paper)
    size = TRACK_MIN_PX
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    opened: NDArray[Any] = cv2.morphologyEx(found, cv2.MORPH_OPEN, kernel)
    return opened


def frames(pixels: NDArray[Any], paper: float) -> list[Array]:
    """The frames: the areas closed by thin, long, straight dark lines."""
    h, w = pixels.shape[:2]
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    dark = np.where(gray < 0.75 * paper, 255, 0).astype(np.uint8)
    thick = tracks_ink(pixels, paper)
    thin_lines = cv2.subtract(dark, cv2.dilate(thick, np.ones((3, 3), np.uint8)))
    longest = LINE_SHARE * min(h, w)
    lines = cv2.HoughLinesP(
        thin_lines, 1, np.pi / 360, threshold=80, minLineLength=longest, maxLineGap=40
    )
    near_track = cv2.dilate(thick, np.ones((15, 15), np.uint8)) > 0
    barrier = np.zeros((h, w), np.uint8)
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            d = np.array([x2 - x1, y2 - y1], np.float64)
            n = float(np.linalg.norm(d)) or 1.0
            d /= n
            # A line along a track is the track's own edge, not a frame.
            ts = np.linspace(0, n, max(2, int(n / 4)))
            xs = np.clip(np.round(x1 + ts * d[0]).astype(int), 0, w - 1)
            ys = np.clip(np.round(y1 + ts * d[1]).astype(int), 0, h - 1)
            if float(near_track[ys, xs].mean()) > ALONG_TRACK:
                continue
            a = (round(x1 - 14 * d[0]), round(y1 - 14 * d[1]))
            b = (round(x2 + 14 * d[0]), round(y2 + 14 * d[1]))
            cv2.line(barrier, a, b, 255, 3)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.where(barrier > 0, 0, 255).astype(np.uint8), connectivity=4
    )
    found: list[Array] = []
    for label in range(1, count):
        x, y, bw, bh, area = stats[label]
        if area < FRAME_SHARE * h * w:
            continue
        if x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1:
            continue  # the paper around the frames
        mask = np.where(labels == label, 255, 0).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        quad = _quad(max(contours, key=cv2.contourArea))
        if quad is not None:
            found.append(quad)
    return sorted(found, key=lambda q: (round(float(q[:, 1].min()) / 50), float(q[:, 0].min())))


# --- The graph -------------------------------------------------------------------------------


@dataclass
class GNode:
    id: str
    at: Point
    ends: int
    kind: str = ""
    """switch, crossing, end, gable, joint, turntable"""
    merged: list[str] = field(default_factory=list)
    """A crossing made of two nodes with 3 ends: their ids, to split again."""
    parts: list[Point] = field(default_factory=list)
    """Where the two nodes with 3 ends were, to split the X again (part c3)."""
    gable: str | None = None
    track: int | None = None


@dataclass
class GEdge:
    id: str
    a: str
    b: str
    points: list[Point]


@dataclass
class Graph:
    nodes: dict[str, GNode] = field(default_factory=dict)
    edges: dict[str, GEdge] = field(default_factory=dict)

    def at(self, node: str) -> list[GEdge]:
        return [e for e in self.edges.values() if node in (e.a, e.b)]

    def degree(self, node: str) -> int:
        return sum((e.a == node) + (e.b == node) for e in self.edges.values())


def _ordered(pixels: NDArray[Any]) -> list[tuple[int, int]]:
    """A path's pixels (row, col) in order from one end to the other."""
    cells = {(int(r), int(c)) for r, c in pixels}
    if len(cells) <= 2:
        return sorted(cells)

    def neighbours(p: tuple[int, int]) -> list[tuple[int, int]]:
        r, c = p
        return [
            (r + dr, c + dc)
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if (dr or dc) and (r + dr, c + dc) in cells
        ]

    start = min(cells, key=lambda p: (len(neighbours(p)), p))
    path = [start]
    seen = {start}
    at = start
    while True:
        nxt = [q for q in neighbours(at) if q not in seen]
        if not nxt:
            break
        at = min(nxt, key=lambda q: abs(q[0] - path[-1][0]) + abs(q[1] - path[-1][1]))
        seen.add(at)
        path.append(at)
    return path


def graph(mask: NDArray[Any], ppm: float) -> Graph:
    """The ink's skeleton as a graph in the mask's px: the junctions and the ends are nodes,
    and what is left of the skeleton between them, piece by piece, the edges."""
    skeleton = thin(mask).astype(bool)
    runs = ring_count(skeleton.astype(np.uint8))
    ends = skeleton & (runs == 1)
    joins = skeleton & (runs >= 3)
    join_px = max(1, round(JOIN_MM * ppm / 2))
    grown = cv2.dilate(
        joins.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * join_px + 1,) * 2),
    )
    node_area = (grown > 0) & skeleton
    count, node_labels = cv2.connectedComponents(node_area.astype(np.uint8), connectivity=8)
    found = Graph()
    label_node: dict[int, str] = {}
    for label in range(1, count):
        pixels = np.argwhere(node_labels == label)
        centre = pixels.mean(axis=0)
        node = f"j{label}"
        found.nodes[node] = GNode(node, (float(centre[1]), float(centre[0])), 0)
        label_node[label] = node
    end_node: dict[tuple[int, int], str] = {}
    for i, (r, c) in enumerate(np.argwhere(ends & ~node_area)):
        node = f"e{i}"
        found.nodes[node] = GNode(node, (float(c), float(r)), 1)
        end_node[(int(r), int(c))] = node
    rest = skeleton & ~node_area
    count, edge_labels = cv2.connectedComponents(rest.astype(np.uint8), connectivity=8)
    h, w = skeleton.shape
    for label in range(1, count):
        pixels = np.argwhere(edge_labels == label)
        path = _ordered(pixels)
        touching: list[tuple[str, int]] = []
        for index in (0, len(path) - 1):
            r, c = path[index]
            if (r, c) in end_node:
                touching.append((end_node[(r, c)], index))
                continue
            near = node_labels[max(0, r - 1) : min(h, r + 2), max(0, c - 1) : min(w, c + 2)]
            labels = [int(v) for v in np.unique(near) if v]
            if labels:
                touching.append((label_node[labels[0]], index))
        if len(touching) == 1 and len(path) > 2:
            # A loop from a junction back to it, or a piece whose other end is a node too.
            touching.append(touching[0])
        if len(touching) < 2:
            continue
        (a, _), (b, _) = touching[0], touching[-1]
        points = [(float(cc), float(rr)) for rr, cc in path]
        points = [found.nodes[a].at, *points, found.nodes[b].at]
        edge = f"g{label}"
        found.edges[edge] = GEdge(edge, a, b, points)
    for gn in found.nodes.values():
        gn.ends = found.degree(gn.id)
    return found


def _length(points: list[Point]) -> float:
    return float(sum(math.dist(a, b) for a, b in itertools.pairwise(points)))


def _join(found: Graph, node: str) -> None:
    """A node with 2 ends is no node: its two edges become one."""
    edges = found.at(node)
    if len(edges) != 2 or edges[0] is edges[1]:
        return
    first, second = edges
    a_points = first.points if first.b == node else first.points[::-1]
    b_points = second.points if second.a == node else second.points[::-1]
    a = first.a if first.b == node else first.b
    b = second.b if second.a == node else second.a
    first.a, first.b, first.points = a, b, a_points + b_points[1:]
    del found.edges[second.id]
    del found.nodes[node]


def clean(found: Graph, ppm: float) -> None:
    """Spurs, text and leader lines sorted away, and joints joined."""
    for _ in range(6):
        changed = False
        for edge in list(found.edges.values()):
            if edge.id not in found.edges:
                continue
            length = _length(edge.points) / ppm
            if edge.a == edge.b and length < LOOP_MM:
                # A hole in the ink where strokes meet thinned to a small loop.
                del found.edges[edge.id]
                changed = True
                continue
            free = [n for n in (edge.a, edge.b) if found.degree(n) == 1]
            if (free and length < SPUR_MM) or (len(free) == 2 and length < PIECE_MIN_MM):
                del found.edges[edge.id]
                for n in free:
                    found.nodes.pop(n, None)
                changed = True
        for name in list(found.nodes):
            if name in found.nodes and found.degree(name) == 2:
                _join(found, name)
                changed = True
        for name in list(found.nodes):
            if name in found.nodes and found.degree(name) == 0:
                del found.nodes[name]
        if not changed:
            break
    for gn in found.nodes.values():
        gn.ends = found.degree(gn.id)


def _crossed(found: Graph, edge: GEdge, ppm: float) -> bool:
    """Two nodes with 3 ends whose other ends pair up across the piece between them into two
    straight lines that cross: two tracks crossing at a shallow angle, whose ink runs together
    for a while (a piece of length about the stroke's width over the angle)."""
    if _length(edge.points) / ppm > CROSS_MM:
        return False
    a_edges = [e for e in found.at(edge.a) if e.id != edge.id]
    b_edges = [e for e in found.at(edge.b) if e.id != edge.id]
    if len(a_edges) != 2 or len(b_edges) != 2:
        return False
    a_heads = [_direction(_away(e, edge.a)) for e in a_edges]
    b_heads = [_direction(_away(e, edge.b)) for e in b_edges]
    across = _direction(_away(edge, edge.a))
    # Both of A's other ends point away from B, and both of B's away from A.
    if any(_turn(h, across) < math.pi / 2 for h in a_heads):
        return False
    if any(_turn(h, across + math.pi) < math.pi / 2 for h in b_heads):
        return False
    best = min(
        max(_turn(a_heads[0] + math.pi, b_heads[i]), _turn(a_heads[1] + math.pi, b_heads[1 - i]))
        for i in (0, 1)
    )
    angle = _turn(a_heads[0], a_heads[1])
    return best <= math.radians(CROSS_ALIGN) and angle >= math.radians(CROSS_MIN_ANGLE)


def bridge(found: Graph, ppm: float) -> None:
    """A track hidden for a stretch (under a bridge drawn over it, or where the pen lifted)
    goes on: two ends that face each other across a gap of at most HIDDEN_MM are joined; an
    end whose way on meets another track within it joins that track there (a switch hidden)."""
    ends = [n for n in found.nodes.values() if found.degree(n.id) == 1]
    out: dict[str, float] = {}
    for n in ends:
        edge = found.at(n.id)[0]
        out[n.id] = _direction(_away(edge, n.id)) + math.pi
    done: set[str] = set()
    pairs = []
    for a in ends:
        for b in ends:
            if a.id >= b.id:
                continue
            gap = math.dist(a.at, b.at)
            if gap > HIDDEN_MM * ppm or gap < 1:
                continue
            towards = math.atan2(b.at[1] - a.at[1], b.at[0] - a.at[0])
            if _turn(out[a.id], towards) > math.radians(HIDDEN_ALIGN):
                continue
            if _turn(out[b.id], towards + math.pi) > math.radians(HIDDEN_ALIGN):
                continue
            pairs.append((gap, a.id, b.id))
    counter = 0
    for _, a_id, b_id in sorted(pairs):
        if a_id in done or b_id in done:
            continue
        counter += 1
        a, b = found.nodes[a_id], found.nodes[b_id]
        found.edges[f"h{counter}"] = GEdge(f"h{counter}", a_id, b_id, [a.at, b.at])
        done |= {a_id, b_id}
        a.ends = b.ends = 2
    for n in ends:
        if n.id in done or n.id not in found.nodes:
            continue
        hit = _ray_hit(found, n, out[n.id], ppm)
        if hit is None:
            continue
        edge, index, point = hit
        counter += 1
        node = GNode(f"k{counter}", point, 3)
        found.nodes[node.id] = node
        first = GEdge(f"{edge.id}a{counter}", edge.a, node.id, [*edge.points[: index + 1], point])
        second = GEdge(f"{edge.id}b{counter}", node.id, edge.b, [point, *edge.points[index + 1 :]])
        del found.edges[edge.id]
        found.edges[first.id] = first
        found.edges[second.id] = second
        found.edges[f"h{counter}"] = GEdge(f"h{counter}", n.id, node.id, [n.at, point])
        done.add(n.id)
    for name in list(found.nodes):
        if name in found.nodes and found.degree(name) == 2:
            _join(found, name)
    for gn in found.nodes.values():
        gn.ends = found.degree(gn.id)


def _ray_hit(found: Graph, node: GNode, out: float, ppm: float) -> tuple[GEdge, int, Point] | None:
    """Where the way on from an end first meets another track, within HIDDEN_MM."""
    best: tuple[float, GEdge, int, Point] | None = None
    ux, uy = math.cos(out), math.sin(out)
    own = {e.id for e in found.at(node.id)}
    for edge in found.edges.values():
        if edge.id in own:
            continue
        for i, p in enumerate(edge.points):
            dx, dy = p[0] - node.at[0], p[1] - node.at[1]
            along = dx * ux + dy * uy
            if along <= 2 or along > HIDDEN_MM * ppm:
                continue
            if abs(-dx * uy + dy * ux) <= 2.0 * ppm and (best is None or along < best[0]):
                best = (along, edge, i, p)
    return None if best is None else (best[1], best[2], best[3])


def merge_pairs(found: Graph, ppm: float) -> None:
    """Two nodes with 3 ends, joined by a short piece of their own, or crossing as two straight
    lines, are one node with 4."""
    for edge in sorted(found.edges.values(), key=lambda e: _length(e.points)):
        if edge.id not in found.edges or edge.a == edge.b:
            continue
        a, b = found.nodes.get(edge.a), found.nodes.get(edge.b)
        if a is None or b is None or a.ends != 3 or b.ends != 3:
            continue
        if _length(edge.points) / ppm > MERGE_MM and not _crossed(found, edge, ppm):
            continue
        mid = ((a.at[0] + b.at[0]) / 2, (a.at[1] + b.at[1]) / 2)
        node = GNode(f"m{a.id}{b.id}", mid, 4, merged=[a.id, b.id], parts=[a.at, b.at])
        found.nodes[node.id] = node
        del found.edges[edge.id]
        for other in list(found.edges.values()):
            if other.a in (a.id, b.id):
                other.a = node.id
                other.points = [mid, *other.points]
            if other.b in (a.id, b.id):
                other.b = node.id
                other.points = [*other.points, mid]
        del found.nodes[a.id]
        del found.nodes[b.id]
    for gn in found.nodes.values():
        gn.ends = found.degree(gn.id)


def _radial_ends(found: Graph, ppm: float) -> None:
    """Tracks that end around a circle, each pointing at its middle, end at a turntable whose
    pit is not drawn in ink (coloured pencil): the rays on past their ends meet in its middle,
    and their ends become one turntable node there."""
    ends = [n for n in found.nodes.values() if found.degree(n.id) == 1]
    if len(ends) < RING_SPOKES:
        return
    cell = 6.0 * ppm
    votes: dict[tuple[int, int], set[str]] = {}
    rays: dict[str, tuple[Point, float]] = {}
    for n in ends:
        edge = found.at(n.id)[0]
        out = _direction(_away(edge, n.id)) + math.pi
        rays[n.id] = (n.at, out)
        for r in np.arange(15.0, PIT_MM, 3.0) * ppm:
            x = n.at[0] + r * math.cos(out)
            y = n.at[1] + r * math.sin(out)
            votes.setdefault((round(x / cell), round(y / cell)), set()).add(n.id)
    if not votes:
        return
    key = max(votes, key=lambda k: len(votes[k]))
    if len(votes[key]) < RING_SPOKES:
        return
    centre = (key[0] * cell, key[1] * cell)
    spokes = []
    for nid, (at, out) in rays.items():
        to_centre = (centre[0] - at[0], centre[1] - at[1])
        along = to_centre[0] * math.cos(out) + to_centre[1] * math.sin(out)
        off = abs(-to_centre[0] * math.sin(out) + to_centre[1] * math.cos(out))
        if 0 < along <= PIT_MM * ppm and off <= 15 * ppm:
            spokes.append(nid)
    if len(spokes) < RING_SPOKES:
        return
    table = GNode(f"t{len(found.nodes)}", centre, 0, "turntable")
    found.nodes[table.id] = table
    for nid in spokes:
        for e in found.at(nid):
            if e.a == nid:
                e.a, e.points = table.id, [table.at, *e.points]
            if e.b == nid:
                e.b, e.points = table.id, [*e.points, table.at]
        del found.nodes[nid]


TABLE_JOIN_MM = 80.0
"""Radial tracks drawn into a turntable's pit run together, or are taken for a hidden switch,
before its middle: a node with 3 ends this near the middle is the pit's, not a switch (part
c3)."""


def _into_tables(found: Graph) -> None:
    """Nodes with 3 ends in a turntable's pit made part of it: the radial tracks that ran
    together there end at the turntable."""
    for table in [n for n in found.nodes.values() if n.kind == "turntable"]:
        inside = [
            n
            for n in found.nodes.values()
            if n.id != table.id
            and n.kind != "turntable"
            and found.degree(n.id) == 3
            and math.dist(n.at, table.at) <= TABLE_JOIN_MM
        ]
        for other in inside:
            for edge in list(found.at(other.id)):
                ends = {edge.a, edge.b}
                if ends == {other.id, table.id} or edge.a == edge.b:
                    del found.edges[edge.id]
                    continue
                if edge.a == other.id:
                    edge.a, edge.points = table.id, [table.at, *edge.points[1:]]
                if edge.b == other.id:
                    edge.b, edge.points = table.id, [*edge.points[:-1], table.at]
            del found.nodes[other.id]
        table.ends = found.degree(table.id)


def turntables(found: Graph, ppm: float) -> None:
    """A small ring of track with tracks on it is a turntable: its ring and nodes become one
    node, where the radial tracks end."""
    _radial_ends(found, ppm)
    while True:
        ring = _small_ring(found, ppm)
        if ring is None:
            return
        nodes, edges = ring
        points = np.array([found.nodes[n].at for n in nodes])
        centre = (float(points[:, 0].mean()), float(points[:, 1].mean()))
        table = GNode(f"t{len(found.nodes)}", centre, 0, kind="turntable")
        found.nodes[table.id] = table
        for e in edges:
            found.edges.pop(e, None)
        for other in list(found.edges.values()):
            if other.a in nodes:
                other.a = table.id
            if other.b in nodes:
                other.b = table.id
        for n in nodes:
            found.nodes.pop(n, None)
        table.ends = found.degree(table.id)


def _small_ring(found: Graph, ppm: float) -> tuple[list[str], list[str]] | None:
    """A cycle of edges whose nodes all lie within RING_MM, with at least 4 other edges on it."""
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for e in found.edges.values():
        adjacency.setdefault(e.a, []).append((e.b, e.id))
        adjacency.setdefault(e.b, []).append((e.a, e.id))
    for start in found.nodes:
        stack: list[tuple[str, list[str], list[str]]] = [(start, [start], [])]
        while stack:
            node, path, edges = stack.pop()
            if len(path) > 12:
                continue
            for nxt, eid in adjacency.get(node, []):
                if eid in edges:
                    continue
                if nxt == start and len(edges) >= 2:
                    ring = [*edges, eid]
                    pts = np.concatenate([np.array(found.edges[e].points) for e in ring])
                    span = float(np.max(np.ptp(pts, axis=0))) / ppm
                    centre = pts.mean(axis=0)
                    radii = np.linalg.norm(pts - centre, axis=1)
                    round_ = float(radii.std()) <= RING_ROUND * float(radii.mean())
                    spokes = sum(
                        1
                        for e in found.edges.values()
                        if e.id not in edges and ((e.a in path) != (e.b in path))
                    )
                    if span <= RING_MM and spokes >= RING_SPOKES and round_:
                        return path, ring
                    continue
                if nxt in path:
                    continue
                stack.append((nxt, [*path, nxt], [*edges, eid]))
    return None


# --- The module ----------------------------------------------------------------------------


@dataclass
class Sketched:
    """A frame read: the graph in the module's mm, the frame as a picture in the module's mm
    (for Fotot under), and the parts code cannot decide."""

    graph: Graph
    image: NDArray[Any]
    grid: tuple[float, float, float, int, int]
    """x0, y0, ppm, width, height: as rectify.Grid."""
    length: float
    width_a: float
    width_b: float
    offset: float
    uncertain: dict[str, Point] = field(default_factory=dict)
    """X1 …: nodes with 4 ends that were two nodes, where code cannot tell a crossing from
    two switches."""


def read(
    sheet: NDArray[Any],
    paper: float,
    corners: Array,
    length: float,
    width_a: float,
    width_b: float,
    offset: float = 0.0,
) -> Sketched:
    """The frame (its corners in the sheet's px: A at Kant 1, B at Kant 1, B far, A far) read
    as a module of the given measures."""
    outline = np.array(
        [[0.0, 0.0], [length, offset], [length, offset + width_b], [0.0, width_a]], np.float64
    )
    to_sheet = homography(outline, np.asarray(corners, np.float64))
    lo = outline.min(axis=0) - MARGIN_MM
    hi = outline.max(axis=0) + MARGIN_MM
    ppm = 1 / MM_PER_PX_READ
    width = math.ceil((hi[0] - lo[0]) * ppm)
    height = math.ceil((hi[1] - lo[1]) * ppm)
    shift = np.array([[1 / ppm, 0, lo[0]], [0, 1 / ppm, lo[1]], [0, 0, 1]], np.float64)
    matrix = to_sheet @ shift
    image = cv2.warpPerspective(
        sheet,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderValue=(255, 255, 255),
    )
    # The ink found on the sheet, where its strokes have the sheet's thickness, then moved.
    ink_sheet = tracks_ink(sheet, paper)
    mask = cv2.warpPerspective(
        ink_sheet,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
    )
    mask = np.where(mask > 100, 255, 0).astype(np.uint8)
    found = graph(mask, ppm)
    stroke = _stroke(mask) / ppm
    clean(found, ppm)
    turntables(found, ppm)
    bridge(found, ppm)
    clean(found, ppm)
    merge_pairs(found, ppm)
    # px to the module's mm.
    for node in found.nodes.values():
        node.at = (lo[0] + node.at[0] / ppm, lo[1] + node.at[1] / ppm)
        node.parts = [(lo[0] + x / ppm, lo[1] + y / ppm) for x, y in node.parts]
    for edge in found.edges.values():
        edge.points = [(lo[0] + x / ppm, lo[1] + y / ppm) for x, y in edge.points]
    _cut(found, outline, length, offset, width_a, width_b)
    clean(found, 1.0)
    _into_tables(found)
    uncertain: dict[str, Point] = {}
    k = 0
    for node in sorted(found.nodes.values(), key=lambda n: n.at):
        if node.kind in ("gable", "turntable"):
            continue
        if node.ends == 1:
            node.kind = "end"
        elif node.ends == 3:
            node.kind = "switch"
        elif node.ends == 4:
            node.kind = "crossing"
            if node.merged:
                k += 1
                uncertain[f"X{k}"] = node.at
        elif node.ends >= 5:
            node.kind = "turntable"
        else:
            node.kind = "joint"
    ink = Ink(mask.astype(np.float32) / 255.0, (float(lo[0]), float(lo[1])), ppm)
    for node in found.nodes.values():
        if node.kind == "switch":
            _points_back(found, node, stroke, ink)
    return Sketched(
        found,
        image,
        (float(lo[0]), float(lo[1]), ppm, width, height),
        length,
        width_a,
        width_b,
        offset,
        uncertain,
    )


def _stroke(mask: NDArray[Any]) -> float:
    """The tracks' stroke width in the mask's px: twice the distance to the paper from the
    ink's middle."""
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    middle = thin(mask).astype(bool) & (mask > 0)
    values = distance[middle]
    return float(2 * np.median(values)) if len(values) else float(TRACK_MIN_PX)


@dataclass(frozen=True)
class Ink:
    """The tracks' ink as read, 0 to 1, in px of the module's mm: its (0, 0) at lo, ppm px per
    mm."""

    mask: NDArray[Any]
    lo: tuple[float, float]
    ppm: float

    def at(self, points: Array) -> Array:
        px = (points - np.array(self.lo)) * self.ppm
        flat = px.reshape(-1, 2).astype(np.float32)
        width = 1024
        rows = max(1, -(-len(flat) // width))
        padded = np.zeros((rows * width, 2), np.float32) - 10.0
        padded[: len(flat)] = flat
        found = cv2.remap(
            self.mask,
            padded[:, 0].reshape(rows, width),
            padded[:, 1].reshape(rows, width),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )
        sampled: Array = found.ravel()[: len(flat)].reshape(px.shape[:-1]).astype(np.float64)
        return sampled


INK_BEHIND_MM = 300.0
"""How far behind where the ink parts the diverging leg's edge is followed, mm."""
INK_D = (0.15, 1.3)
"""The leg's offset is fitted up to this many strokes (the second number): where the two strokes
still overlap, before the thinning bends the ink's middle; it must reach the first."""


def _back_from_ink(
    ink: Ink,
    at: Point,
    stem: list[Point],
    straight: list[Point],
    diverging: list[Point],
    stroke: float,
) -> Parting | None:
    """How far behind the parting the points lie, from the ink's width across the straight
    (part c3): where the two strokes overlap the ink is wider by the leg's offset d, so d is
    read there too, where the thinning cannot tell the legs apart, against the straight's own
    other edge. d = a·(u - u0)² from the points at u0 on, least squares over u0."""
    near = [p for p in stem if math.dist(p, at) <= 200.0]
    near += [p for p in straight if math.dist(p, at) <= 200.0]
    if len(near) < 5:
        return None
    line = np.array(near, np.float64)
    centre = line.mean(axis=0)
    _, vectors = np.linalg.eigh((line - centre).T @ (line - centre))
    t = vectors[:, 1]
    ahead = np.array(straight[-1], np.float64) - np.array(at, np.float64)
    if float(t @ ahead) < 0:
        t = -t
    n = np.array([-t[1], t[0]])
    leg = np.array(diverging, np.float64)
    if float(np.mean((leg - centre) @ n)) < 0:
        n = -n
    origin = centre + t * float((np.array(at) - centre) @ t)
    behind = min(INK_BEHIND_MM, 0.9 * _length(stem))
    us = np.arange(-behind, 2 * stroke, 1.0)
    vs = np.arange(-stroke, 2.5 * stroke, 0.25)
    grid = origin[None, None, :] + us[:, None, None] * t + vs[None, :, None] * n
    values = ink.at(grid)
    edges = []
    for row in values:
        on = np.nonzero(row >= 0.5)[0]
        if not len(on):
            edges.append(np.nan)
            continue
        j, i = int(on[-1]), int(on[0])
        if j + 1 < len(row) and row[j] > row[j + 1]:
            # Where the ink falls through one half, between the last place on and the next.
            far = j + (row[j] - 0.5) / (row[j] - row[j + 1])
        else:
            far = float(j)
        if i > 0 and row[i] > row[i - 1]:
            near_edge = i - (row[i] - 0.5) / (row[i] - row[i - 1])
        else:
            near_edge = float(i)
        # The ink's width across the straight: the leg widens it on its side only, so the
        # straight's own other edge is the reference wherever the line lies.
        edges.append(float((far - near_edge) * 0.25))
    edge = np.array(edges)
    finite = np.isfinite(edge)
    if int(finite.sum()) < 20:
        return None
    # From the stem's side, as long as the leg's offset is under INK_D strokes.
    base = float(np.median(edge[finite & (us <= -0.5 * behind)])) if behind > 0 else 0.0
    top = INK_D[1] * stroke
    over = np.nonzero(finite & (edge - base > top))[0]
    last = int(over[0]) if len(over) else len(us)
    u, d = us[:last][finite[:last]], edge[:last][finite[:last]]
    if len(u) < 20 or float((d - base).max()) < INK_D[0] * stroke:
        return None
    d = d - base
    # d = a·(u - u0)² + c from u0 on and 0 before it: the leg's arc from the points, and the
    # step c where the leg's stroke begins (a hand's jog, or the drawing's own px), least
    # squares for each u0.
    best: tuple[float, float, float] | None = None
    for u0 in np.arange(float(u[0]) + 10.0, float(u[-1]) - 10.0, 1.0):
        q = np.clip(u - u0, 0.0, None) ** 2
        design = np.stack([q, (u >= u0).astype(np.float64)], axis=1)
        (a, c), *_ = np.linalg.lstsq(design, d, rcond=None)
        if a <= 0 or c < -1.0:
            continue
        cost = float(np.sum((design @ np.array([a, c]) - d) ** 2))
        if best is None or cost < best[0]:
            best = (cost, float(u0), float(a))
    if best is None:
        return None
    _, u0, a = best
    # The points at u0, behind the parting when u0 < 0.
    return Parting(max(0.0, -u0), t, n, 1 / (2 * a))


def _points_back(found: Graph, node: GNode, stroke: float, ink: Ink | None = None) -> None:
    """A switch's node where its legs' ink parts is not its points: the legs' strokes overlap
    until they lie a stroke apart. Beyond the parting the diverging leg lies d = (s + u)²/2R
    from the straight line through the stem and the straight leg, u along it from the parting
    and s back to the points: √d is a straight line in u that reaches 0 at u = -s. d is read
    from how much wider the ink is where the strokes overlap (part c3, _back_from_ink), else
    fitted to the diverging leg's ink beyond the parting; when neither can be, s = 2·w/φ for a
    leg that leaves at the angle φ (d = s²/2R = w, φ = s/R). The node is moved back along its
    stem to the points."""
    found_legs = legs(found, node.id)
    if found_legs is None:
        return
    stem = found.edges[found_legs.stem]
    straight = found.edges[found_legs.straight]
    diverging = found.edges[found_legs.diverging]
    fitted = (
        _back_from_ink(
            ink,
            node.at,
            _away(stem, node.id),
            _away(straight, node.id),
            _away(diverging, node.id),
            stroke,
        )
        if ink is not None
        else None
    )
    if fitted is None:
        fitted = _back_from_offsets(
            node.at, _away(stem, node.id), _away(straight, node.id), _away(diverging, node.id)
        )
    back = fitted.back if fitted is not None else None
    if back is None:
        phi = _turn(
            _heading_beyond(_away(straight, node.id)),
            _heading_beyond(_away(diverging, node.id)),
        )
        if phi < math.radians(1.0):
            return
        back = 2 * stroke / phi
    back = min(back, POINTS_BACK_MAX, 0.8 * _length(stem.points))
    away = _away(stem, node.id)
    # Along the stem's own ink, the distance back.
    walked = 0.0
    at = away[0]
    for a, b in itertools.pairwise(away):
        step = math.dist(a, b)
        if walked + step >= back:
            t = (back - walked) / step if step else 0.0
            at = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            break
        walked += step
        at = b
    old = node.at
    node.at = at
    keep = [p for p in away if math.dist(p, old) > back]
    trimmed = [at, *keep] if keep else [at, away[-1]]
    stem.points = trimmed if stem.a == node.id else trimmed[::-1]
    # Between the points and the parting both legs run in the stem's ink: the straight leg
    # on the line, the diverging one leaving it as the offsets say (d = u²/2R), when they were
    # fitted; else both in the stem's ink.
    shared = [p for p in away if math.dist(p, old) <= back][::-1]
    shared_of = {straight.id: shared, diverging.id: shared}
    if fitted is not None and back > 0:
        start = np.array(at, np.float64)
        along = np.arange(3.0, back, 3.0)
        line = [(float(q[0]), float(q[1])) for q in start + np.outer(along, fitted.t)]
        bend = (
            start + np.outer(along, fitted.t) + np.outer(along**2 / (2 * fitted.radius), fitted.n)
        )
        shared_of = {straight.id: line, diverging.id: [(float(x), float(y)) for x, y in bend]}
    for leg in (straight, diverging):
        part = shared_of[leg.id]
        if leg.a == node.id:
            leg.points = [at, *part, *leg.points]
        else:
            leg.points = [*leg.points, *part[::-1], at]


HEADING_SPAN = (25.0, 90.0)
"""A leg's heading is taken between these distances from its node, mm: past where the thinning
bends it."""


OFFSET_SPAN = (20.0, 200.0)
"""The diverging leg's ink used for its offsets: from and to these distances from the parting,
mm."""
OFFSET_MAX = 40.0
"""And no further from the straight line than this, mm: beyond, a leg is often straight."""


@dataclass(frozen=True)
class Parting:
    """Where a switch's points lie behind the parting of its ink, and how its diverging leg
    leaves the straight line: along t, toward n, with the radius."""

    back: float
    t: Array
    n: Array
    radius: float


def _back_from_offsets(
    at: Point, stem: list[Point], straight: list[Point], diverging: list[Point]
) -> Parting | None:
    """How far behind the parting the points lie, from the diverging leg's offsets from the
    straight line; None when the leg's ink does not give it."""
    near = [p for p in stem if math.dist(p, at) <= 200.0]
    near += [p for p in straight if math.dist(p, at) <= 200.0]
    if len(near) < 5:
        return None
    line = np.array(near, np.float64)
    centre = line.mean(axis=0)
    _, vectors = np.linalg.eigh((line - centre).T @ (line - centre))
    t = vectors[:, 1]
    ahead = np.array(straight[-1], np.float64) - np.array(at, np.float64)
    if float(t @ ahead) < 0:
        t = -t
    n = np.array([-t[1], t[0]])
    pts = np.array(diverging, np.float64)
    gone = np.linalg.norm(pts - np.array(at), axis=1)
    u = (pts - np.array(at)) @ t
    signed = (pts - centre) @ n
    d = np.abs(signed)
    use = (gone >= OFFSET_SPAN[0]) & (gone <= OFFSET_SPAN[1]) & (d <= OFFSET_MAX) & (u > 0)
    if int(use.sum()) < 5 or float(np.ptp(u[use])) < 30.0:
        return None
    slope, intercept = np.polyfit(u[use], np.sqrt(d[use]), 1)
    if slope <= 1e-6:
        return None
    side = n if float(np.mean(signed[use])) >= 0 else -n
    # √d = (s + u)/√(2R): the slope is 1/√(2R).
    return Parting(max(0.0, float(intercept / slope)), t, side, 1 / (2 * float(slope) ** 2))


def _heading_beyond(points: list[Point]) -> float:
    """A leg's heading a little way from its node, where the thinning no longer bends it."""
    start = points[0]
    near = next((p for p in points if math.dist(p, start) >= HEADING_SPAN[0]), points[-1])
    far = next((p for p in points if math.dist(p, start) >= HEADING_SPAN[1]), points[-1])
    if math.dist(near, far) < 5:
        return _direction(points)
    return math.atan2(far[1] - near[1], far[0] - near[0])


POINTS_BACK_MAX = 400.0
"""A switch's points lie at most this far behind where the sketch's strokes part, mm."""


def _cut(
    found: Graph, outline: Array, length: float, offset: float, width_a: float, width_b: float
) -> None:
    """The graph cut at the module's gables: what lies outside goes, and where a track leaves
    through a gable it ends at a gable node, numbered from Kant 1."""
    polygon = outline.astype(np.float32).reshape(-1, 1, 2)

    def inside(p: Point) -> bool:
        return cv2.pointPolygonTest(polygon, (float(p[0]), float(p[1])), True) >= -1.0

    counter = 0
    for edge in list(found.edges.values()):
        pts = edge.points
        flags = [inside(p) for p in pts]
        if all(flags):
            continue
        del found.edges[edge.id]
        # The runs of the edge inside, each from a node or a crossing of the outline.
        start = None
        for i in range(len(pts) + 1):
            on = i < len(pts) and flags[i]
            if on and start is None:
                start = i
            elif not on and start is not None:
                run = pts[start:i]
                a = edge.a if start == 0 else None
                b = edge.b if i == len(pts) else None
                if _length(run) >= 10:
                    counter += 1
                    ids = []
                    for end, p in ((a, run[0]), (b, run[-1])):
                        if end is not None:
                            ids.append(end)
                            continue
                        node = f"c{counter}{len(ids)}"
                        gable = None
                        if abs(p[0]) <= GABLE_MM:
                            gable = "A"
                        elif abs(p[0] - length) <= GABLE_MM:
                            gable = "B"
                        found.nodes[node] = GNode(
                            node,
                            (0.0, p[1]) if gable == "A" else (length, p[1]) if gable == "B" else p,
                            1,
                            kind="gable" if gable else "end",
                            gable=gable,
                        )
                        ids.append(node)
                    e = GEdge(f"{edge.id}r{counter}", ids[0], ids[1], list(run))
                    if found.nodes[ids[0]].kind == "gable":
                        e.points[0] = found.nodes[ids[0]].at
                    if found.nodes[ids[1]].kind == "gable":
                        e.points[-1] = found.nodes[ids[1]].at
                    found.edges[e.id] = e
                start = None
    for gn in list(found.nodes.values()):
        if not inside(gn.at) and gn.kind != "gable" and found.degree(gn.id) == 0:
            del found.nodes[gn.id]
    for gn in found.nodes.values():
        if gn.kind or found.degree(gn.id) != 1:
            continue
        if abs(gn.at[0]) <= GABLE_MM:
            gn.kind, gn.gable = "gable", "A"
            gn.at = (0.0, gn.at[1])
        elif abs(gn.at[0] - length) <= GABLE_MM:
            gn.kind, gn.gable = "gable", "B"
            gn.at = (length, gn.at[1])
        else:
            continue
        for e in found.at(gn.id):
            if e.a == gn.id:
                e.points[0] = gn.at
            if e.b == gn.id:
                e.points[-1] = gn.at
    for end, width, base in (("A", width_a, 0.0), ("B", width_b, offset)):
        own = sorted((n for n in found.nodes.values() if n.gable == end), key=lambda n: n.at[1])
        for k, n in enumerate(own, start=1):
            n.track = k
        del width, base
    for gn in found.nodes.values():
        gn.ends = found.degree(gn.id)


# --- The drawing -----------------------------------------------------------------------------


def _away(edge: GEdge, node: str) -> list[Point]:
    return edge.points if edge.a == node else edge.points[::-1]


def _direction(points: list[Point]) -> float:
    """The heading of a line leaving its first point, over HEADING_MM."""
    start = points[0]
    far = next((p for p in points if math.dist(p, start) >= HEADING_MM), points[-1])
    return math.atan2(far[1] - start[1], far[0] - start[0])


def _turn(a: float, b: float) -> float:
    return abs(math.remainder(a - b, 2 * math.pi))


@dataclass(frozen=True)
class SwitchLegs:
    stem: str
    straight: str
    diverging: str


def legs(found: Graph, node: str) -> SwitchLegs | None:
    """A switch's stem (the end pointing away from the other two) and its straight leg (the one
    that runs on most nearly from the stem), by the ends' headings."""
    edges = found.at(node)
    if len(edges) != 3:
        return None
    heads = [_direction(_away(e, node)) for e in edges]
    stem = max(
        range(3),
        key=lambda i: min(_turn(heads[i], heads[j]) for j in range(3) if j != i),
    )
    others = [i for i in range(3) if i != stem]
    through = heads[stem] + math.pi
    straight = min(others, key=lambda i: _turn(heads[i], through))
    diverging = next(i for i in others if i != straight)
    return SwitchLegs(edges[stem].id, edges[straight].id, edges[diverging].id)


def _simple(points: list[Point], min_radius: float) -> list[Seg] | None:
    """One straight or one arc through the ends, when the ink lies within FIT_MM of it."""
    a, b = np.array(points[0]), np.array(points[-1])
    chord = float(np.linalg.norm(b - a))
    if chord < 1.0:
        return None
    # The thinning bends the ink where it meets a node: judged inside END_MM of the ends.
    inner = [p for p in points if min(math.dist(p, points[0]), math.dist(p, points[-1])) > END_MM]
    judged = [points[0], *inner, points[-1]] if len(inner) >= 5 else points
    # A straight: the ink on its own line within FIT_MM, and the nodes near that line.
    ink = np.array(judged, np.float64)
    centre = ink.mean(axis=0)
    _, vectors = np.linalg.eigh((ink - centre).T @ (ink - centre))
    n = vectors[:, 0]
    if (
        float(np.abs((ink - centre) @ n).max()) <= FIT_MM
        and float(np.abs((np.array([a, b]) - centre) @ n).max()) <= 2 * FIT_MM
    ):
        return [curves.Line(points[0], points[-1])]
    return one_arc(judged, min_radius, (FIT_MM, FIT_MM / 2))


def _split(points: list[Point], min_radius: float, depth: int = 0) -> list[Seg]:
    """Straights and arcs, halving the ink until each half is one: the last way, when the
    smooth fit does not follow the sketch."""
    simple = _simple(points, min_radius)
    if simple is not None:
        return simple
    if depth >= SPLIT_DEPTH or len(points) < 8:
        return [curves.Line(points[0], points[-1])]
    middle = len(points) // 2
    return [
        *_split(points[: middle + 1], min_radius, depth + 1),
        *_split(points[middle:], min_radius, depth + 1),
    ]


def _worst(segs: list[Seg], points: list[Point]) -> float:
    return max(curves.distance(segs, p) for p in points[::3])


def _fit(points: list[Point], min_radius: float) -> list[Seg]:
    """A piece of the sketch's ink as straights and arcs: one straight or one arc when the ink
    is that, else the smooth fit, else halved."""
    if len(points) < 2 or math.dist(points[0], points[-1]) < 1.0:
        return [curves.Line(points[0], points[-1])]
    sampled = [points[0]]
    for p in points[1:]:
        if math.dist(p, sampled[-1]) >= 3.0:
            sampled.append(p)
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    simple = _simple(sampled, min_radius)
    if simple is not None:
        return simple
    try:
        segs = smoothing.fit(sampled, min_radius, FIT_MM, None, 6.0)
    except ValueError:
        segs = []
    if segs and math.dist(curves.path_point(segs, curves.path_length(segs)), sampled[-1]) <= FIT_MM:
        segs = curves.reshaped(segs, points[0], points[-1])
        if _worst(segs, sampled) <= SKETCH_MM / 2:
            return segs
    return _split(sampled, min_radius)


TWO_SWITCHES = "tva-vaxlar"
"""The answer (questions.NODE_ANSWERS) that an uncertain X is two switches."""


def split_nodes(sketched: Sketched, answers: dict[str, str]) -> list[str]:
    """The uncertain X's (X1 …) the owner or the AI answered are two switches."""
    return sorted(name for name in sketched.uncertain if answers.get(name) == TWO_SWITCHES)


def _split_x(found: Graph, node: GNode) -> None:
    """An X that is two switches drawn as the two nodes with 3 ends the ink merged, joined by
    a piece of their own: each of the four tracks goes to the one on its side (part c3)."""
    first, second = (np.array(p, np.float64) for p in node.parts)
    if float(np.linalg.norm(second - first)) < 1.0:
        return
    middle, axis = (first + second) / 2, second - first
    nodes = [
        GNode(f"{node.id}a", (float(first[0]), float(first[1])), 3, "switch"),
        GNode(f"{node.id}b", (float(second[0]), float(second[1])), 3, "switch"),
    ]
    for edge in found.at(node.id):
        away = _away(edge, node.id)
        ahead = next((p for p in away if math.dist(p, node.at) >= HEADING_MM), away[-1])
        own = nodes[1] if float((np.array(ahead) - middle) @ axis) > 0 else nodes[0]
        if edge.a == node.id:
            edge.a = own.id
            edge.points = [own.at, *edge.points[1:]]
        if edge.b == node.id:
            edge.b = own.id
            edge.points = [*edge.points[:-1], own.at]
    if any(found.degree(n.id) != 2 for n in nodes):
        # The four tracks do not pair up two and two: left as a crossing.
        for edge in found.edges.values():
            for n in nodes:
                if edge.a == n.id:
                    edge.a = node.id
                    edge.points = [node.at, *edge.points[1:]]
                if edge.b == n.id:
                    edge.b = node.id
                    edge.points = [*edge.points[:-1], node.at]
        return
    del found.nodes[node.id]
    for n in nodes:
        found.nodes[n.id] = n
    between = [
        (float(x), float(y))
        for x, y in np.linspace(np.array(nodes[0].at), np.array(nodes[1].at), 6)
    ]
    joining = GEdge(f"{node.id}j", nodes[0].id, nodes[1].id, between)
    found.edges[joining.id] = joining
    for n in nodes:
        n.ends = found.degree(n.id)


def drawing(
    sketched: Sketched,
    target: Drawing,
    answers: dict[str, str],
    certainty: Certainty = Certainty.PROBABLE,
) -> tuple[Drawing, list[float]]:
    """The track plan from the sketch, in the module's drawing (with its measures and no
    pieces): each piece redrawn as straights and arcs, a switch at each node with 3 ends, a
    crossing at each with 4. answers: what each uncertain X is (X1 …: questions.NODE_ANSWERS),
    the owner's or the AI's; an X answered two switches is drawn as the two (part c3), any
    other as a crossing."""
    found = sketched.graph
    split = split_nodes(sketched, answers)
    if split:
        found = copy.deepcopy(found)
        for name in split:
            at = sketched.uncertain[name]
            node = min(
                (n for n in found.nodes.values() if n.kind == "crossing" and n.parts),
                key=lambda n: math.dist(n.at, at),
                default=None,
            )
            if node is not None and math.dist(node.at, at) < 1.0:
                _split_x(found, node)
    min_radius = switches.limits(target.scale).switch_min_radius
    origin = GraphOrigin(source=GraphSource.SKETCH, certainty=certainty)
    ids: dict[str, str] = {}
    for node in found.nodes.values():
        if node.kind == "gable" and node.gable is not None:
            made = target.new_id("n")
            target.nodes[made] = DrawingNode(
                made, NodeType.MODULE_JOINT, node.at, GableEnd(node.gable), node.track
            )
        else:
            kind = {
                "switch": NodeType.SWITCH,
                "crossing": NodeType.CROSSING,
                "end": NodeType.BUFFER_STOP,
                "turntable": NodeType.TURNTABLE,
            }.get(node.kind, NodeType.JOINT)
            made = target.new_id("n")
            target.nodes[made] = DrawingNode(made, kind, node.at)
        ids[node.id] = made
    pieces: dict[str, str] = {}
    deviation: list[float] = []
    for edge in found.edges.values():
        a, b = ids[edge.a], ids[edge.b]
        pts = [target.nodes[a].at, *edge.points[1:-1], target.nodes[b].at]
        segs = _fit(pts, min_radius)
        made = target.new_id("s")
        target.pieces[made] = DrawingPiece(made, a, b, segs, None, origin)
        pieces[edge.id] = made
        target.lines[made] = DrawnLine(
            piece=made,
            points=[(round(x, 1), round(y, 1)) for x, y in edge.points[::2][:4000]],
            source="sketch",
        )
        deviation.extend(curves.distance(segs, p) for p in edge.points[::5])
    number = 0
    for node in sorted(found.nodes.values(), key=lambda n: n.at[0]):
        if node.kind != "switch":
            continue
        found_legs = legs(found, node.id)
        if found_legs is None:
            continue
        number += 1
        node_id = ids[node.id]
        diverging = target.pieces[pieces[found_legs.diverging]]
        away = target.away(diverging.id, node_id)
        leg_head = curves.start_heading(away[0])
        made = target.new_id("v")
        target.switches[made] = DrawingSwitch(
            id=made,
            node=node_id,
            type=SwitchType.ORDINARY,
            trunk=pieces[found_legs.stem],
            straight=pieces[found_legs.straight],
            diverging=pieces[found_legs.diverging],
            radius=None,
            angle=None,
            origin=origin,
            number=str(number),
            design=None,
            toward=GableEnd.B if math.cos(leg_head) >= 0 else GableEnd.A,
        )
    target.source = DrawingSource.SKETCH
    target.smoothing = Smoothing.LIGHT
    target.validate()
    return target, deviation


def counts(sketched: Sketched, answers: dict[str, str] | None = None) -> tuple[int, int]:
    """Switches and crossings read: an X answered two switches counts as two (part c3)."""
    nodes = sketched.graph.nodes.values()
    split = len(split_nodes(sketched, answers or {}))
    switches_ = sum(n.kind == "switch" for n in nodes) + 2 * split
    return switches_, sum(n.kind == "crossing" for n in nodes) - split


# --- Kept with the job ------------------------------------------------------------------------


def to_json(sketched: Sketched) -> dict[str, Any]:
    g = sketched.graph
    return {
        "nodes": [
            [
                n.id,
                list(n.at),
                n.ends,
                n.kind,
                n.merged,
                n.gable,
                n.track,
                [list(p) for p in n.parts],
            ]
            for n in g.nodes.values()
        ],
        "edges": [
            [e.id, e.a, e.b, [[round(x, 2), round(y, 2)] for x, y in e.points]]
            for e in g.edges.values()
        ],
        "grid": list(sketched.grid),
        "length": sketched.length,
        "width_a": sketched.width_a,
        "width_b": sketched.width_b,
        "offset": sketched.offset,
        "uncertain": {k: list(v) for k, v in sketched.uncertain.items()},
    }


def from_json(data: dict[str, Any], image: NDArray[Any]) -> Sketched:
    g = Graph()
    for nid, at, ends, kind, merged, gable, track, *rest in data["nodes"]:
        parts = [(float(p[0]), float(p[1])) for p in rest[0]] if rest else []
        g.nodes[nid] = GNode(
            nid,
            (float(at[0]), float(at[1])),
            int(ends),
            kind,
            list(merged),
            gable=gable,
            track=track,
            parts=parts,
        )
    for eid, a, b, points in data["edges"]:
        g.edges[eid] = GEdge(eid, a, b, [(float(x), float(y)) for x, y in points])
    x0, y0, ppm, w, h = data["grid"]
    return Sketched(
        g,
        image,
        (float(x0), float(y0), float(ppm), int(w), int(h)),
        float(data["length"]),
        float(data["width_a"]),
        float(data["width_b"]),
        float(data["offset"]),
        {k: (float(v[0]), float(v[1])) for k, v in data["uncertain"].items()},
    )
