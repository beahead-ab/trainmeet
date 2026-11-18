"""The rules every panel keeps on its grid, whoever laid it out (STD-26, §3.1).

A track may only meet another where both end, at a node they share: a switch, a crossing, a
joint between two pieces. Anywhere else, two tracks on the same cell, two tracks that cross
without a crossing, or a track that runs through a node without ending there, is a fault. The
engine checks its own layout with this, and the panel built from a track plan is refused by it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from contracts.station_model import Cell

EPSILON = 1e-6


@dataclass(frozen=True)
class Hit:
    """Two paths that meet where they may not, or a path through a node it does not end at."""

    kind: str  # "same" (on the same cells), "cross" (crossing), "through" (through a node)
    a: str
    b: str
    at: Cell


def cell_text(point: Cell) -> str:
    return "(" + ", ".join(f"{round(v, 2):g}" for v in point) + ")"


def straight(a: Cell, b: Cell) -> bool:
    """Horizontal, vertical or diagonal between cells (STD-26)."""
    dc, dr = abs(b[0] - a[0]), abs(b[1] - a[1])
    return dc < EPSILON or dr < EPSILON or abs(dc - dr) < EPSILON


def _cross(o: Cell, a: Cell, b: Cell) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on(p: Cell, a: Cell, b: Cell) -> bool:
    """p on the segment a–b."""
    if abs(_cross(a, b, p)) > EPSILON * max(1.0, abs(b[0] - a[0]) + abs(b[1] - a[1])):
        return False
    return (
        min(a[0], b[0]) - EPSILON <= p[0] <= max(a[0], b[0]) + EPSILON
        and min(a[1], b[1]) - EPSILON <= p[1] <= max(a[1], b[1]) + EPSILON
    )


def _same(p: Cell, q: Cell) -> bool:
    return abs(p[0] - q[0]) < 1e-4 and abs(p[1] - q[1]) < 1e-4


def _meeting(a: Cell, b: Cell, c: Cell, d: Cell) -> tuple[str, Cell] | None:
    """Where the segments a–b and c–d meet: ("point", p), ("overlap", p) or None."""
    d1, d2 = _cross(c, d, a), _cross(c, d, b)
    d3, d4 = _cross(a, b, c), _cross(a, b, d)
    scale = max(1.0, abs(b[0] - a[0]) + abs(b[1] - a[1]), abs(d[0] - c[0]) + abs(d[1] - c[1]))
    tol = EPSILON * scale * scale
    if abs(d1) <= tol and abs(d2) <= tol:
        # Collinear: they overlap if they share more than a point.
        shared = [p for p in (a, b) if _on(p, c, d)] + [p for p in (c, d) if _on(p, a, b)]
        unique: list[Cell] = []
        for p in shared:
            if not any(_same(p, q) for q in unique):
                unique.append(p)
        if len(unique) >= 2:
            return (
                "overlap",
                ((unique[0][0] + unique[1][0]) / 2, (unique[0][1] + unique[1][1]) / 2),
            )
        if unique:
            return ("point", unique[0])
        return None
    if (d1 > tol and d2 > tol) or (d1 < -tol and d2 < -tol):
        return None
    if (d3 > tol and d4 > tol) or (d3 < -tol and d4 < -tol):
        return None
    t = d1 / (d1 - d2) if abs(d1 - d2) > 0 else 0.0
    return ("point", (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))


def hits(
    paths: Mapping[str, Sequence[Cell]],
    ends: Mapping[str, tuple[str, str]],
    nodes: Mapping[str, Cell],
    knots: frozenset[str] = frozenset(),
) -> list[Hit]:
    """Every place where two paths meet other than at a node both end at, and every node that a
    path runs through without ending there. `ends` names each path's two end nodes; `nodes`
    holds every named node's cell. A knot may lie on another path (TKL82)."""
    found: list[Hit] = []
    names = list(paths)
    boxes = {}
    for name in names:
        pts = paths[name]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        boxes[name] = (min(xs), min(ys), max(xs), max(ys))
    node_cells = [(n, c) for n, c in nodes.items() if n not in knots]
    knot_cells = [nodes[n] for n in knots if n in nodes]
    for name in names:
        pts = paths[name]
        own = set(ends.get(name, ()))
        for node, cell in node_cells:
            if node in own:
                continue
            box = boxes[name]
            if not (
                box[0] - EPSILON <= cell[0] <= box[2] + EPSILON
                and box[1] - EPSILON <= cell[1] <= box[3] + EPSILON
            ):
                continue
            if any(_on(cell, a, b) for a, b in pairwise(pts)):
                found.append(Hit("through", name, node, cell))
    for i, first in enumerate(names):
        box1 = boxes[first]
        for second in names[i + 1 :]:
            box2 = boxes[second]
            if (
                box1[2] < box2[0] - EPSILON
                or box2[2] < box1[0] - EPSILON
                or box1[3] < box2[1] - EPSILON
                or box2[3] < box1[1] - EPSILON
            ):
                continue
            shared = set(ends.get(first, ())) & set(ends.get(second, ()))
            allowed = [nodes[n] for n in shared if n in nodes] + knot_cells
            hit = _first_hit(paths[first], paths[second], allowed)
            if hit is not None:
                kind, at = hit
                found.append(Hit(kind, first, second, at))
    return found


def _first_hit(
    one: Sequence[Cell], other: Sequence[Cell], allowed: list[Cell]
) -> tuple[str, Cell] | None:
    for a, b in pairwise(one):
        for c, d in pairwise(other):
            met = _meeting(a, b, c, d)
            if met is None:
                continue
            kind, at = met
            if kind == "overlap":
                return ("same", at)
            if any(_same(at, q) for q in allowed):
                continue
            return ("cross", at)
    return None


def describe(hit: Hit, name: Mapping[str, str] | None = None) -> str:
    """The fault in Swedish, with the tracks' names."""
    shown = name or {}
    a = shown.get(hit.a, hit.a)
    b = shown.get(hit.b, hit.b)
    if hit.kind == "through":
        return f"Spåret {a} går genom {hit.b} i ruta {cell_text(hit.at)} utan att sluta där."
    if hit.kind == "same":
        return f"Spåren {a} och {b} ligger på samma ruta vid {cell_text(hit.at)}."
    return f"Spåren {a} och {b} korsar varandra i ruta {cell_text(hit.at)} utan korsning."
