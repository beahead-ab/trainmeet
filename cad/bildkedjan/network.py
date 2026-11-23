"""Step 12 of the chain, the first half: from the connections to the track network, each piece
drawn once (bildkedjan, Geometri; lärdomarna, Växlar: "varje spårbit ritas bara en gång").

Every connection is a path y(x) across the module. Where two paths run within SHARE_GAUGES of a
gauge of each other they are on the same track. So at every millimetre of x the paths fall in
groups, and a group that keeps its members is one piece of track. Where a group splits, a track
leaves another: a switch whose diverging leg heads for gable B; where two groups join, a switch
whose leg heads for gable A. Two groups that join for a short while and part again with their
sides swapped have crossed: a crossing, at the point where they cross. Paths begin and end at
the terminals: the gables' tracks and the ends inside the module.

The switch's points (tungspetsen) are not where the groups part, which is some way after them,
but where the diverging leg leaves the straight one tangentially: its distance from it grows as
d = (s - s0)² / 2R (lärdomarna, Växlar), which gives s0 and the radius R.

Where the legs part the map is weak and a path takes the stronger track, so the distance is not
read from the paths but from the rails themselves (part c3): across the straight track, every
SEP_STEP mm, the cross section of the measuring image is matched against the straight's two
rails and the diverging leg's two, d apart, starting where the leg lies a gauge off and walking
back toward the points while the leg's rails are still told from the straight's (down to
SEP_FLOOR mm, about three of the photo's px). That curve d(s) is fitted three ways:

- the switch library's types (cad/switches.py), each with its own geometry as AnyRail draws it:
  an arc of the type's radius tangent to the straight at s0, then straight on at the type's
  angle. A type whose median distance from d(s) is at most DESIGN_FIT_MM (AR3: 1 mm) places the
  switch, with the type's radius: its node is where the drawn leg leaves the straight, as in
  AnyRail;
- a free arc, d = (s - s0)² / 2R, when no type fits (the switch is then antagen, AR3);
- the blade tips: d = a·u + b·u² from s1 (u = s - s1, a and b at least 0), the place the
  diverging rail visibly leaves the stock rail. A real turnout's blades leave at an angle of
  their own, so the tips lie some way after the arc's tangent point; they are what an owner
  measures as tungspetsarna, and what the result says.

Without the measuring image (or with too little of the leg seen) the switch falls back on the
fit to the leg's path (fit_points).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan import trackmap
from cad.bildkedjan.camera import Array
from cad.bildkedjan.paths import Path, Terminal
from cad.bildkedjan.rectify import Grid
from contracts.cad import SwitchDesign

SHARE_GAUGES = 0.18
"""Two paths closer than this many gauges are on the same track (3 mm in H0)."""
TIDY_MM = 8
"""Shorter partings and joinings than this are noise and are smoothed away."""
BUBBLE_MM = 250
BUBBLE_GAUGES = 0.6
CROSSING_SPAN_MM = 160.0
"""Two groups joined for less than this, that part with their sides swapped, crossed."""
FIT_DEPTH_GAUGES = 0.75
"""The leg's distance from the straight is fitted up to this many gauges."""
FIT_MIN_DEPTH = 0.4
MIN_PIECE_MM = 10.0
POINTS_BEHIND_MM = 200.0
"""How far behind where the legs part a switch's points can lie (R 2200: about 120 mm)."""
MAX_RADIUS_GAUGES = 400
"""A fitted radius over this many gauges (6,6 m in H0) is no switch's: the fit found nothing."""
SEP_STEP = 2.0
"""The diverging leg's distance from the straight is read every this many mm along it."""
SEP_HALF = 60.0
"""The cross section reaches this far either side of the straight, mm."""
SEP_SMOOTH = 0.6
"""The rails are found as lines this wide (the standard deviation, mm) in the cross section."""
SEP_FLOOR_MM = 3.0
SEP_FLOOR_PX = 2.5
"""Closer than this (mm, or the photo's px) the leg's rails merge with the straight's."""
SEP_SHARE = 0.5
"""The leg's two rails stand out at least this share as much as the straight's two."""
SEP_MISS_MM = 12.0
"""The walk toward the points stops after this much without the leg's rails."""
SEP_RISE_MM = 1.0
"""Once the leg is at the floor, where its rails merge with the straight's, a reading this much
above it is no longer the leg's: the walk has run on past the merge onto other rails (between two
switches toe to toe, toward the other's), and stops there (part c6)."""
SEP_TOP_GAUGES = 0.9
"""d is fitted up to this many gauges: further on the leg's inner rail meets the frog."""
SEP_REACH_MM = 300.0
"""How far behind where the legs part the walk may go, mm."""
SEP_MIN_POINTS = 8
DESIGN_FIT_MM = 1.0
"""A library type whose geometry lies within this of d(s) (the median, mm) is the switch's type
(bildkedjan step 15, Växelinpassning: medianfel över 1 mm är antagen)."""
SEP_START_MM = 350.0
"""The walk starts where the leg is a gauge off, at most this far beyond where the legs part."""
TIPS_REACH_MM = 400.0
TRUNK_SKIP_MM = 30.0
TRUNK_SPAN_MM = 60.0
TRUNK_MIN_MM = 20.0
"""A switch's straight leg is the one that turns least from the trunk. The trunk's heading is
taken over TRUNK_SPAN_MM from TRUNK_SKIP_MM behind where the legs part (at least TRUNK_MIN_MM of
it): next to where they part the trunk is still drawn toward the diverging leg. Part c6 did so
only between two switches toe to toe; since part c7 for every switch, whether the trunk runs to
another switch or to a gable."""
REFERENCE_MM = 250.0
"""The straight is a line fitted to the straight leg's path this far either side of the node."""


@dataclass
class Node:
    id: str
    kind: str
    """gable, end, switch or crossing"""
    x: float
    y: float
    terminal: Terminal | None = None


@dataclass
class Edge:
    id: str
    a: str
    b: str
    """The nodes at its smaller and its larger x."""
    pid: int
    """The path its points come from."""
    members: frozenset[int]


@dataclass
class SwitchFit:
    node: str
    trunk: str
    straight: str
    diverging: str
    toward: str
    """A or B: the gable the diverging leg heads for."""
    radius: float | None
    deviation: float
    """The fit's median deviation from the leg, mm."""
    points: int
    tips: float | None = None
    """The x of the blade tips on the straight (tungspetsarna), when the rails show them."""
    design: str | None = None
    """The library type the leg fits (AR3), by id."""
    tips_spread: float = 0.0
    """Half the span the blade tips can lie in, mm."""
    parted: float = math.nan
    """The x where the legs part, before the points were fitted."""


@dataclass(frozen=True)
class Seen:
    """The measuring image a switch's legs are read in (part c3): the image in grey, its grid,
    where a track's rails lie from its middle, whether the rails are lighter or darker than what
    lies beside them (1 or -1; 0 unknown), and the photo's px per mm."""

    gray: NDArray[Any]
    grid: Grid
    rail: float
    polarity: float
    ppm: float

    @classmethod
    def of(cls, gray: NDArray[Any], grid: Grid, profile: trackmap.Profile, ppm: float) -> Seen:
        kind = trackmap.rail_kind(profile)
        polarity = 1.0 if kind == "light" else -1.0 if kind == "dark" else 0.0
        return cls(gray, grid, profile.rail, polarity, ppm)

    @property
    def floor(self) -> float:
        return max(SEP_FLOOR_MM, SEP_FLOOR_PX / max(self.ppm, 1e-6))


@dataclass
class Network:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    switches: list[SwitchFit] = field(default_factory=list)
    crossings: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    """Nodes where four ends meet and the code cannot tell what it is."""


def _y_at(path: Path, x: float) -> float:
    return float(np.interp(x, path.xs, path.ys))


def _first(path: Path) -> int:
    return math.ceil(float(path.xs[0]) - 1e-9)


def _last(path: Path) -> int:
    return math.floor(float(path.xs[-1]) + 1e-9)


def _covers(path: Path, x: float) -> bool:
    return _first(path) <= x <= _last(path)


def _tidy(mask: Array) -> Array:
    """A run of True or False shorter than TIDY_MM inside the mask is turned over."""
    found = mask.copy()
    for value in (False, True):
        start = None
        for i in range(len(found) + 1):
            inside = i < len(found) and found[i] == value
            if inside and start is None:
                start = i
            elif not inside and start is not None:
                if start > 0 and i < len(found) and i - start < TIDY_MM:
                    found[start:i] = not value
                start = None
    return found


def _together(paths: list[Path], gauge: float) -> dict[tuple[int, int], tuple[int, Array]]:
    """For each pair of paths, from which x and where they are on the same track."""
    found: dict[tuple[int, int], tuple[int, Array]] = {}
    limit = SHARE_GAUGES * gauge
    for i, p in enumerate(paths):
        for j in range(i + 1, len(paths)):
            q = paths[j]
            lo = int(max(p.xs[0], q.xs[0]))
            hi = int(min(p.xs[-1], q.xs[-1]))
            if hi <= lo:
                continue
            xs = np.arange(lo, hi + 1, dtype=np.float64)
            yp = np.interp(xs, p.xs, p.ys)
            yq = np.interp(xs, q.xs, q.ys)
            slope = np.gradient((yp + yq) / 2)
            apart = np.abs(yp - yq) * np.cos(np.arctan(slope))
            close = _tidy(apart < limit)
            found[(i, j)] = (lo, _bubbles(close, apart, gauge))
    return found


def _bubbles(close: Array, apart: Array, gauge: float) -> Array:
    """Two paths on one track that part for a while and come together again, never more than
    BUBBLE_GAUGES apart, wandered: at low resolution a path's middle wanders a few millimetres
    where the map is weak. Two tracks that part and meet again (a loop) lie a track apart."""
    found = close.copy()
    start = None
    for i in range(len(found) + 1):
        inside = i < len(found) and not found[i]
        if inside and start is None:
            start = i
        elif not inside and start is not None:
            if (
                start > 0
                and i < len(found)
                and i - start <= BUBBLE_MM
                and float(apart[start:i].max()) <= BUBBLE_GAUGES * gauge
            ):
                found[start:i] = True
            start = None
    return found


def _groups(
    paths: list[Path], together: dict[tuple[int, int], tuple[int, Array]], x: int
) -> list[frozenset[int]]:
    present = [i for i, p in enumerate(paths) if _covers(p, x)]
    parent = {i: i for i in present}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in present:
        for b in present:
            if a >= b:
                continue
            entry = together.get((a, b))
            if entry is None:
                continue
            lo, mask = entry
            k = x - lo
            if 0 <= k < len(mask) and mask[k]:
                parent[root(a)] = root(b)
    groups: dict[int, set[int]] = {}
    for i in present:
        groups.setdefault(root(i), set()).add(i)
    return sorted((frozenset(g) for g in groups.values()), key=lambda g: min(g))


@dataclass
class _Run:
    members: frozenset[int]
    x0: int
    x1: int
    a: str = ""
    b: str = ""


def _straightest(paths: list[Path], members: frozenset[int], x0: float, x1: float) -> int:
    """The member that bends least around the run: the one that goes straight on."""

    def bend(i: int) -> float:
        p = paths[i]
        lo, hi = max(p.xs[0], x0 - 60), min(p.xs[-1], x1 + 60)
        xs = np.arange(lo, hi + 1, 2.0)
        if len(xs) < 5:
            return 0.0
        heads = np.arctan(np.gradient(np.interp(xs, p.xs, p.ys), xs))
        return float(np.abs(np.diff(heads)).sum())

    return min(sorted(members), key=bend)


def build(
    paths: list[Path],
    terminals: list[Terminal],
    gauge: float,
    seen: Seen | None = None,
    designs: Sequence[SwitchDesign] = (),
) -> Network:
    """The network of the accepted paths: nodes, the pieces between them, the switches with
    their points and radii, and the crossings. seen: the measuring image the switches' legs are
    read in; designs: the library's types they are fitted with."""
    net = Network()
    if not paths:
        return net
    for t in terminals:
        if any(t.id in (p.a, p.b) for p in paths):
            net.nodes[t.id] = Node(t.id, t.kind, t.at[0], t.at[1], t)
    together = _together(paths, gauge)
    x_lo = min(_first(p) for p in paths)
    x_hi = max(_last(p) for p in paths)
    columns = [_groups(paths, together, x) for x in range(x_lo, x_hi + 1)]
    # Runs: a group that keeps its members from one x to the next.
    runs: list[_Run] = []
    open_runs: dict[frozenset[int], _Run] = {}
    for k, groups in enumerate(columns):
        x = x_lo + k
        current = set(groups)
        for members in list(open_runs):
            if members not in current:
                del open_runs[members]
        for members in groups:
            if members in open_runs:
                open_runs[members].x1 = x
            else:
                run = _Run(members, x, x)
                runs.append(run)
                open_runs[members] = run
    counter = [0]

    def new(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}{counter[0]}"

    # The run's ends: a terminal, or an event with the runs before or after it.
    events: dict[tuple[int, frozenset[frozenset[int]]], str] = {}
    for run in runs:
        for side in ("a", "b"):
            x = run.x0 if side == "a" else run.x1
            neighbour_x = x - 1 if side == "a" else x + 1
            ends_here = [
                i
                for i in run.members
                if (_first(paths[i]) if side == "a" else _last(paths[i])) == x
            ]
            terminal = None
            for i in ends_here:
                tid = paths[i].a if side == "a" else paths[i].b
                if tid in net.nodes:
                    terminal = tid
                    break
            linked = [
                other
                for other in runs
                if other is not run
                and (other.x1 == neighbour_x if side == "a" else other.x0 == neighbour_x)
                and other.members & run.members
            ]
            if terminal is not None and not linked:
                setattr(run, side, terminal)
                continue
            # The event joins this run with the linked ones on the other side; one id for it.
            key_members = frozenset([run.members, *(o.members for o in linked)])
            key = (x if side == "a" else neighbour_x, key_members)
            if key not in events:
                events[key] = new("N")
            setattr(run, side, events[key])
    # Merge event ids that describe the same transition from both sides.
    _unify(runs)
    for run in runs:
        for side in ("a", "b"):
            node = getattr(run, side)
            if node not in net.nodes:
                x = run.x0 if side == "a" else run.x1
                y = float(np.mean([_y_at(paths[i], x) for i in run.members]))
                net.nodes[node] = Node(node, "event", float(x), y)
    for run in runs:
        pid = _straightest(paths, run.members, run.x0, run.x1)
        edge = Edge(new("E"), run.a, run.b, pid, run.members)
        net.edges[edge.id] = edge
    _classify(net, paths, gauge, seen, designs)
    return net


def _unify(runs: list[_Run]) -> None:
    """A transition at x seen from the runs before it and from the runs after it is one node:
    the runs that meet there get the same id."""
    at: dict[int, list[tuple[_Run, str]]] = {}
    for run in runs:
        at.setdefault(run.x1, []).append((run, "b"))
        at.setdefault(run.x0 - 1, []).append((run, "a"))
    for _, ends in at.items():
        # Group the ends that share paths across the transition.
        groups: list[set[int]] = []
        for i, (run, _) in enumerate(ends):
            joined = [g for g in groups if any(ends[j][0].members & run.members for j in g)]
            merged = {i}.union(*joined) if joined else {i}
            groups = [g for g in groups if g not in joined]
            groups.append(merged)
        for group in groups:
            ids = sorted(getattr(ends[j][0], ends[j][1]) for j in group)
            terminals = [n for n in ids if not n.startswith("N")]
            chosen = terminals[0] if terminals else ids[0]
            for j in group:
                run, side = ends[j]
                if getattr(run, side).startswith("N"):
                    setattr(run, side, chosen)


def _edges_at(net: Network, node: str) -> tuple[list[Edge], list[Edge]]:
    """The edges that end at the node from smaller x, and those that start at it."""
    before = [e for e in net.edges.values() if e.b == node]
    after = [e for e in net.edges.values() if e.a == node]
    return before, after


def _heading(path: Path, x0: float, x1: float) -> float:
    lo, hi = max(path.xs[0], min(x0, x1)), min(path.xs[-1], max(x0, x1))
    if hi - lo < 4:
        return 0.0
    xs = np.arange(lo, hi + 1, 1.0)
    slope = np.polyfit(xs, np.interp(xs, path.xs, path.ys), 1)[0]
    return math.atan(float(slope))


def _classify(
    net: Network,
    paths: list[Path],
    gauge: float,
    seen: Seen | None = None,
    designs: Sequence[SwitchDesign] = (),
) -> None:
    """Each event node made a switch, a crossing or an uncertain part, and the switches' points
    found from the leg's rails (or path)."""
    for node in list(net.nodes.values()):
        if node.kind != "event":
            continue
        before, after = _edges_at(net, node.id)
        if len(before) == 1 and len(after) == 2:
            _switch(net, paths, node, before[0], after, "B", gauge)
        elif len(before) == 2 and len(after) == 1:
            _switch(net, paths, node, after[0], before, "A", gauge)
        elif len(before) == 1 and len(after) == 1:
            # Nothing happens here: the two edges are one.
            _join(net, before[0], after[0], node.id)
        else:
            node.kind = "uncertain"
            net.uncertain.append(node.id)
    _crossings(net, paths)
    if seen is not None:
        _read(net, paths, gauge, seen, designs)
        _untangle(net, paths)


def _join(net: Network, first: Edge, second: Edge, node: str) -> None:
    first.b = second.b
    del net.edges[second.id]
    del net.nodes[node]


def _switch(
    net: Network,
    paths: list[Path],
    node: Node,
    trunk: Edge,
    legs: list[Edge],
    toward: str,
    gauge: float,
) -> None:
    sign = 1.0 if toward == "B" else -1.0
    trunk_path = paths[trunk.pid]
    # Next to where the legs part the trunk is still drawn toward the diverging leg: its heading
    # is taken where the leg has left it, as far as the trunk reaches toward the other switch or
    # the gable (part c6 between two switches toe to toe; part c7 for every switch, where the
    # straight and the diverging leg were swapped at a gable).
    far = net.nodes[trunk.a] if toward == "B" else net.nodes[trunk.b]
    room = abs(node.x - far.x)
    if room >= TRUNK_SKIP_MM + TRUNK_MIN_MM:
        span = min(room, TRUNK_SKIP_MM + TRUNK_SPAN_MM)
        base = _heading(trunk_path, node.x - sign * TRUNK_SKIP_MM, node.x - sign * span)
    else:
        base = _heading(trunk_path, node.x - sign * 60, node.x - sign * 4)
    turns = [
        abs(_heading(paths[leg.pid], node.x + sign * 4, node.x + sign * 60) - base) for leg in legs
    ]
    straight, diverging = (legs[0], legs[1]) if turns[0] <= turns[1] else (legs[1], legs[0])
    node.kind = "switch"
    parted = node.x
    # The leg's own piece, and the trunk only as far as the points can lie behind where the
    # legs part: further on, the leg's path may leave the trunk again at another switch.
    if toward == "B":
        reach = (
            max(net.nodes[trunk.a].x, node.x - POINTS_BEHIND_MM),
            net.nodes[diverging.b].x,
        )
    else:
        reach = (
            net.nodes[diverging.a].x,
            min(net.nodes[trunk.b].x, node.x + POINTS_BEHIND_MM),
        )
    fit = fit_points(paths[straight.pid], paths[diverging.pid], node.x, toward, gauge, reach)
    if fit is not None and fit[1] <= MAX_RADIUS_GAUGES * gauge and abs(fit[0] - node.x) <= 400:
        s0_x, radius, deviation, count = fit
        # The points never on top of the trunk's other end: a switch at a gable lies inside.
        if toward == "B":
            s0_x = max(s0_x, net.nodes[trunk.a].x + MIN_PIECE_MM)
        else:
            s0_x = min(s0_x, net.nodes[trunk.b].x - MIN_PIECE_MM)
        node.x = s0_x
        node.y = _y_at(paths[straight.pid], s0_x)
    else:
        # No fit, or a radius no switch has: where the legs part, the radius unknown (antagen).
        radius, deviation, count = None, math.inf, 0
    net.switches.append(
        SwitchFit(
            node.id,
            trunk.id,
            straight.id,
            diverging.id,
            toward,
            radius,
            deviation,
            count,
            parted=parted,
        )
    )


def _read(
    net: Network,
    paths: list[Path],
    gauge: float,
    seen: Seen,
    designs: Sequence[SwitchDesign],
) -> None:
    """Each switch (the crossings told apart first, as the legs' paths place them) read again
    from its legs' rails, where they show it: its node, radius and type, and its blade tips."""
    for fit in net.switches:
        node = net.nodes[fit.node]
        trunk = net.edges[fit.trunk]
        diverging = net.edges[fit.diverging]
        straight = paths[net.edges[fit.straight].pid]
        toward = fit.toward
        leg_end = net.nodes[diverging.b].x if toward == "B" else net.nodes[diverging.a].x
        read = read_switch(
            seen, straight, paths[diverging.pid], fit.parted, toward, gauge, leg_end, designs
        )
        if (
            read is None
            or read.radius > MAX_RADIUS_GAUGES * gauge
            or abs(read.points - fit.parted) > 400
        ):
            continue  # the rails do not show the leg well enough: its path's fit stays
        s0_x = read.points
        # The points never on top of a gable or an end at the trunk's other end; a switch
        # there is untangled once all are placed (_untangle).
        other = net.nodes[trunk.a] if toward == "B" else net.nodes[trunk.b]
        if other.kind in ("gable", "end"):
            if toward == "B":
                s0_x = max(s0_x, other.x + MIN_PIECE_MM)
            else:
                s0_x = min(s0_x, other.x - MIN_PIECE_MM)
        tips = read.tips
        if tips is not None:
            tips = max(tips, s0_x) if toward == "B" else min(tips, s0_x)
        node.x = s0_x
        node.y = _y_at(straight, s0_x)
        fit.radius, fit.deviation, fit.points = read.radius, read.deviation, read.count
        fit.tips, fit.design, fit.tips_spread = tips, read.design, read.tips_spread


def fit_points(
    straight: Path,
    leg: Path,
    x_part: float,
    toward: str,
    gauge: float,
    reach: tuple[float, float] | None = None,
) -> tuple[float, float, float, int] | None:
    """The points (as x) and the radius from d = (s - s0)² / 2R: the leg's distance from the
    straight path, as the square root, grows linearly from the points. The fit takes the leg
    from where it is FIT_MIN_DEPTH mm off to FIT_DEPTH_GAUGES gauges off, and trims what lies
    more than two deviations from the line. reach: the x the leg's own piece and the trunk
    span; beyond it the leg's path is another track's (a path runs on through more switches)."""
    sign = 1.0 if toward == "B" else -1.0
    span = 400.0
    lo, hi = sorted((x_part - sign * span, x_part + sign * span))
    lo = max(lo, straight.xs[0], leg.xs[0])
    hi = min(hi, straight.xs[-1], leg.xs[-1])
    if reach is not None:
        lo, hi = max(lo, reach[0]), min(hi, reach[1])
    if hi - lo < 20:
        return None
    xs = np.arange(lo, hi + 1, 1.0)
    ys = np.interp(xs, straight.xs, straight.ys)
    yl = np.interp(xs, leg.xs, leg.ys)
    heads = np.arctan(np.gradient(ys, xs))
    d = np.abs(yl - ys) * np.cos(heads)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))])
    # Along the leg toward its gable, from the points onward.
    if sign < 0:
        s = s[-1] - s
    depth = FIT_DEPTH_GAUGES * gauge
    use = (d >= FIT_MIN_DEPTH) & (d <= depth)
    # Only the leg's first climb away from the straight, not a later approach to another track.
    order = np.argsort(s)
    first_far = next((k for k in order if d[k] > depth), None)
    if first_far is not None:
        use &= s <= s[first_far]
    if use.sum() < 8:
        return None
    sd, root = s[use], np.sqrt(d[use])
    keep = np.ones(len(sd), bool)
    for _ in range(4):
        m, c = np.polyfit(sd[keep], root[keep], 1)
        residual = root - (m * sd + c)
        spread = float(np.std(residual[keep])) or 1e-6
        new_keep = np.abs(residual) <= 2.5 * spread
        if new_keep.sum() < 8 or (new_keep == keep).all():
            break
        keep = new_keep
    if m <= 1e-6:
        return None
    s0 = -c / m
    radius = 1 / (2 * m * m)
    model = np.clip(sd - s0, 0, None) ** 2 / (2 * radius)
    deviation = float(np.median(np.abs(model[keep] - d[use][keep])))
    # Back from s to x on the straight.
    s_axis = s if sign > 0 else s[::-1]
    x_axis = xs if sign > 0 else xs[::-1]
    x0 = float(np.interp(s0, s_axis, x_axis))
    return x0, float(radius), deviation, int(keep.sum())


@dataclass(frozen=True)
class SwitchRead:
    """A switch read from its legs' rails: its node (the arc's tangent point) as x, the radius,
    the median distance of the fit from d(s), how many places d was read at, the blade tips' x
    and the library type, if one fits."""

    points: float
    radius: float
    deviation: float
    count: int
    tips: float | None
    design: str | None
    tips_spread: float = 0.0
    """Half the span the blade tips can lie in, mm."""


def reference(straight: Path, x: float) -> tuple[float, float] | None:
    """The straight leg as a line y = k·x + c through its path near x."""
    near = (straight.xs >= x - REFERENCE_MM) & (straight.xs <= x + REFERENCE_MM)
    if int(near.sum()) < 20:
        return None
    k, c = np.polyfit(straight.xs[near], straight.ys[near], 1)
    return float(k), float(c)


def _lines(sections: NDArray[Any], polarity: float) -> NDArray[Any]:
    """How much each place in each cross section looks like a rail: a thin line, lighter or
    darker than beside it."""
    sigma = SEP_SMOOTH / trackmap.STEP
    size = 2 * math.ceil(3 * sigma) + 1
    blurred = cv2.GaussianBlur(sections.astype(np.float32), (size, 1), sigma)
    curvature = np.gradient(np.gradient(blurred, axis=1), axis=1)
    found: NDArray[Any] = -curvature * polarity
    return found


def separation(
    seen: Seen,
    line: tuple[float, float],
    leg: Path,
    start: float,
    stop: float,
    gauge: float,
) -> Array:
    """The diverging leg's distance d from the straight line, read from the rails: rows (x, d)
    from start (where the leg is about a gauge off) toward stop (behind the points), as long as
    the leg's two rails stand out beside the straight's two."""
    if seen.polarity == 0:
        return np.zeros((0, 2))
    k, c = line
    step = SEP_STEP if stop > start else -SEP_STEP
    lo, hi = (
        max(float(leg.xs[0]), seen.grid.x0),
        min(float(leg.xs[-1]), seen.grid.x0 + seen.grid.width / seen.grid.ppm),
    )
    xs = np.arange(start, stop, step)
    xs = xs[(xs >= lo) & (xs <= hi)]
    if len(xs) < SEP_MIN_POINTS:
        return np.zeros((0, 2))
    head = math.atan(k)
    points = np.stack([xs, k * xs + c], axis=1)
    sections = trackmap.cross_sections(
        seen.gray, seen.grid, points, np.full(len(xs), head), SEP_HALF
    )
    rails = _lines(sections, seen.polarity)
    us = np.arange(-SEP_HALF, SEP_HALF + trackmap.STEP / 2, trackmap.STEP)
    leg_ys = np.interp(xs, leg.xs, leg.ys)
    offsets = (leg_ys - (k * xs + c)) * math.cos(head)
    side = 1.0 if float(np.median(offsets[: max(3, len(xs) // 4)])) >= 0 else -1.0
    r = seen.rail
    es = np.arange(-2.0, 2.01, 0.25)
    found: list[tuple[float, float]] = []
    previous: float | None = None
    lowest = math.inf
    missed = 0.0
    for i, x in enumerate(xs):
        row = rails[i]
        straight = np.interp(side * (es - r), us, row) + np.interp(side * (es + r), us, row)
        best = int(np.argmax(straight))
        e, strength = float(es[best]), float(straight[best])
        guess = previous if previous is not None else abs(float(offsets[i]))
        ds = np.arange(max(1.5, guess - 4.0), guess + 3.0, 0.25)
        leg_rails = np.interp(side * (e + ds - r), us, row) + np.interp(
            side * (e + ds + r), us, row
        )
        j = int(np.argmax(leg_rails))
        if strength > 0 and leg_rails[j] >= SEP_SHARE * strength and 0 < j < len(ds) - 1:
            d = float(ds[j])
            if lowest <= seen.floor and d >= lowest + SEP_RISE_MM:
                break  # past where the leg's rails merge: other rails from here
            found.append((float(x), d))
            previous = d
            lowest = min(lowest, d)
            missed = 0.0
            if previous < seen.floor:
                break
        else:
            missed += SEP_STEP
            if missed > SEP_MISS_MM:
                break
    return np.array(found, np.float64).reshape(-1, 2)


def design_offsets(u: Array, radius: float, angle: float) -> Array:
    """A library type's diverging leg as AnyRail draws it: an arc tangent to the straight at
    u = 0, then straight on at the type's angle; its distance from the straight at u."""
    turn = math.radians(angle)
    end = radius * math.sin(turn)
    arc = radius - np.sqrt(np.maximum(radius * radius - u * u, 0.0))
    on = radius * (1 - math.cos(turn)) + (u - end) * math.tan(turn)
    found: Array = np.where(u <= 0, 0.0, np.where(u <= end, arc, on))
    return found


def fit_design(
    data: Array, sign: float, designs: Sequence[SwitchDesign]
) -> tuple[SwitchDesign, float, float] | None:
    """The library type whose geometry lies nearest d(s), with its tangent point and the median
    distance."""
    xs, ds = data[:, 0], data[:, 1]
    near = float(xs[int(np.argmin(ds))])
    best: tuple[float, float, SwitchDesign] | None = None
    for known in designs:
        if known.radius is None or known.angle is None:
            continue
        for steps in (np.arange(-60.0, 600.0, 1.0), None):
            if steps is None:
                assert best is not None
                if best[2] is not known:
                    break
                steps = np.arange(-1.0, 1.01, 0.05) + (near - best[1]) * sign
            s0s = near - sign * steps
            u = (xs[None, :] - s0s[:, None]) * sign
            off = np.median(np.abs(design_offsets(u, known.radius, known.angle) - ds), axis=1)
            k = int(np.argmin(off))
            if best is None or float(off[k]) < best[0]:
                best = (float(off[k]), float(s0s[k]), known)
    if best is None:
        return None
    return best[2], best[1], best[0]


def fit_arc(data: Array, sign: float) -> tuple[float, float, float] | None:
    """A free arc d = (s - s0)² / 2R through d(s): √d is a line that reaches 0 at s0. The
    tangent point, the radius and the median distance."""
    xs, root = data[:, 0], np.sqrt(data[:, 1])
    keep = np.ones(len(xs), bool)
    m = c = 0.0
    for _ in range(4):
        m, c = (float(v) for v in np.polyfit(xs[keep], root[keep], 1))
        residual = root - (m * xs + c)
        spread = float(np.std(residual[keep])) or 1e-6
        new_keep = np.abs(residual) <= 2.5 * spread
        if int(new_keep.sum()) < SEP_MIN_POINTS or (new_keep == keep).all():
            break
        keep = new_keep
    if m * sign <= 1e-6:
        return None
    s0 = -c / m
    radius = 1 / (2 * m * m)
    model = np.clip((xs - s0) * sign, 0, None) ** 2 / (2 * radius)
    return s0, radius, float(np.median(np.abs(model - data[:, 1])))


def fit_tips(data: Array, sign: float) -> float | None:
    """Where the diverging rail leaves the stock rail: d = a·u + b·u² from there, u = (s - s1),
    with a, b at least 0 (the blades' own angle, and the curve after them)."""
    xs, ds = data[:, 0], data[:, 1]
    near = float(xs[int(np.argmin(ds))])
    s1s = near - sign * np.arange(0.5, TIPS_REACH_MM, 1.0)
    u = (xs[None, :] - s1s[:, None]) * sign
    valid = (u > 0).all(axis=1)
    if not valid.any():
        return None
    s11, s12, s22 = (u * u).sum(1), (u**3).sum(1), (u**4).sum(1)
    b1, b2 = (u * ds).sum(1), (u * u * ds).sum(1)
    det = s11 * s22 - s12 * s12
    with np.errstate(divide="ignore", invalid="ignore"):
        a = (b1 * s22 - b2 * s12) / det
        b = (b2 * s11 - b1 * s12) / det
        only_a = np.maximum(b1 / s11, 0.0)
        only_b = np.maximum(b2 / s22, 0.0)

    def cost(ca: Array, cb: Array) -> Array:
        found: Array = ((ds[None, :] - ca[:, None] * u - cb[:, None] * u * u) ** 2).sum(1)
        return found

    both = (a >= 0) & (b >= 0) & np.isfinite(a) & np.isfinite(b)
    zero = np.zeros_like(a)
    costs = np.minimum(cost(only_a, zero), cost(zero, only_b))
    costs = np.where(
        both, np.minimum(costs, cost(np.where(both, a, 0), np.where(both, b, 0))), costs
    )
    costs = np.where(valid, costs, np.inf)
    return float(s1s[int(np.argmin(costs))])


def read_switch(
    seen: Seen,
    straight: Path,
    leg: Path,
    x_part: float,
    toward: str,
    gauge: float,
    leg_end: float,
    designs: Sequence[SwitchDesign],
) -> SwitchRead | None:
    """The switch read from its legs' rails, or None when they do not show enough of it."""
    sign = 1.0 if toward == "B" else -1.0
    line = reference(straight, x_part)
    if line is None:
        return None
    k, c = line
    # Where the leg's path is a gauge off, on its own piece and near enough for the line.
    last = x_part + sign * SEP_START_MM
    last = min(last, leg_end) if sign > 0 else max(last, leg_end)
    ahead = np.arange(x_part, last, sign * SEP_STEP)
    if not len(ahead):
        return None
    apart = np.abs(np.interp(ahead, leg.xs, leg.ys) - (k * ahead + c)) * math.cos(math.atan(k))
    far = np.nonzero(apart >= gauge)[0]
    start = float(ahead[far[0]]) if len(far) else float(ahead[-1])
    data = separation(seen, line, leg, start, x_part - sign * SEP_REACH_MM, gauge)
    data = data[(data[:, 1] >= seen.floor) & (data[:, 1] <= SEP_TOP_GAUGES * gauge)]
    if len(data) < SEP_MIN_POINTS:
        return None
    near = float(data[int(np.argmin(data[:, 1])), 0])
    matched = fit_design(data, sign, designs) if designs else None
    design: str | None = None
    if matched is not None and matched[2] <= DESIGN_FIT_MM:
        known, points, deviation = matched
        assert known.radius is not None
        radius = known.radius
        design = known.id
    else:
        arc = fit_arc(data, sign)
        if arc is None:
            return None
        points, radius, deviation = arc
    latest = fit_tips(data, sign)
    tips: float | None = None
    spread = 0.0
    if latest is not None:
        # The blade tips lie between the arc's tangent point (the earliest the diverging rail
        # can leave) and where the rails' first visible slope meets the straight (the latest):
        # the middle, and half the span as how sure it is.
        latest = min(max(latest, points), near) if sign > 0 else max(min(latest, points), near)
        tips = (points + latest) / 2
        spread = abs(latest - points) / 2
    return SwitchRead(points, radius, deviation, len(data), tips, design, spread)


def _untangle(net: Network, paths: list[Path]) -> None:
    """Two switches toe to toe, with a short trunk between them, whose tangent points passed
    each other (each lies some way behind its blade tips): both are drawn MIN_PIECE_MM apart
    about the middle of the two, on their straights."""
    for edge in net.edges.values():
        a, b = net.nodes.get(edge.a), net.nodes.get(edge.b)
        if a is None or b is None or a.kind != "switch" or b.kind != "switch":
            continue
        if b.x - a.x >= MIN_PIECE_MM:
            continue
        middle = (a.x + b.x) / 2
        for node, x in ((a, middle - MIN_PIECE_MM / 2), (b, middle + MIN_PIECE_MM / 2)):
            fit = next(f for f in net.switches if f.node == node.id)
            node.x = x
            node.y = _y_at(paths[net.edges[fit.straight].pid], x)


def _crossings(net: Network, paths: list[Path]) -> None:
    """A short shared run between a join and a parting, where the two pairs swap sides, is a
    crossing: the join, the run and the parting become one crossing node where they cross."""
    for edge in list(net.edges.values()):
        if edge.id not in net.edges or len(edge.members) < 2:
            continue
        start, end = net.nodes.get(edge.a), net.nodes.get(edge.b)
        if start is None or end is None or start.kind != "switch" or end.kind != "switch":
            continue
        if end.x - start.x > CROSSING_SPAN_MM:
            continue
        before, _ = _edges_at(net, start.id)
        _, after = _edges_at(net, end.id)
        if len(before) != 2 or len(after) != 2:
            continue
        # Sides before and after, by y: which path leaves on which side.
        upper_before = min(before, key=lambda e: _y_at(paths[e.pid], start.x - 30))
        upper_after = min(after, key=lambda e: _y_at(paths[e.pid], end.x + 30))
        if upper_before.members & upper_after.members:
            continue  # same side: two switches toe to toe, or a gauntlet, not a crossing
        # The points of a join and a parting may pass each other: the span between them.
        lo, hi = sorted((start.x, end.x))
        x_cross = _cross_x(paths[upper_before.pid], paths[upper_after.pid], lo, hi)
        x = x_cross if x_cross is not None else (start.x + end.x) / 2
        y = (_y_at(paths[upper_before.pid], x) + _y_at(paths[upper_after.pid], x)) / 2
        cross = Node(f"X{start.id}", "crossing", x, y)
        net.nodes[cross.id] = cross
        net.switches = [s for s in net.switches if s.node not in (start.id, end.id)]
        del net.edges[edge.id]
        for e in net.edges.values():
            if e.b == start.id:
                e.b = cross.id
            if e.a == end.id:
                e.a = cross.id
        del net.nodes[start.id]
        del net.nodes[end.id]
        net.crossings.append(cross.id)


def _cross_x(p: Path, q: Path, lo: float, hi: float) -> float | None:
    """Where two paths cross, between lo and hi (extended a little): y_p - y_q changes sign."""
    xs = np.arange(lo - 40, hi + 41, 0.5)
    xs = xs[(xs >= max(p.xs[0], q.xs[0])) & (xs <= min(p.xs[-1], q.xs[-1]))]
    if len(xs) < 3:
        return None
    diff = np.interp(xs, p.xs, p.ys) - np.interp(xs, q.xs, q.ys)
    # Lines fitted on each side, away from where the two blur together.
    left = xs < lo - 5
    right = xs > hi + 5
    if left.sum() >= 5 and right.sum() >= 5:
        line = np.polyfit(
            np.concatenate([xs[left], xs[right]]), np.concatenate([diff[left], diff[right]]), 1
        )
        if abs(line[0]) > 1e-6:
            return float(-line[1] / line[0])
    signs = np.sign(diff)
    change = np.nonzero(np.diff(signs))[0]
    return float(xs[change[0]]) if len(change) else None
