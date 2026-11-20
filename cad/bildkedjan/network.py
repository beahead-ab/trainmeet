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
d = (s - s0)² / 2R (lärdomarna, Växlar), which gives s0 and the radius R from the leg's own path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from cad.bildkedjan.camera import Array
from cad.bildkedjan.paths import Path, Terminal

SHARE_GAUGES = 0.18
"""Two paths closer than this many gauges are on the same track (3 mm in H0)."""
TIDY_MM = 8
"""Shorter partings and joinings than this are noise and are smoothed away."""
CROSSING_SPAN_MM = 160.0
"""Two groups joined for less than this, that part with their sides swapped, crossed."""
FIT_DEPTH_GAUGES = 0.75
"""The leg's distance from the straight is fitted up to this many gauges."""
FIT_MIN_DEPTH = 0.4


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
    """The fit's median deviation from the leg's path, mm."""
    points: int


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
            close = np.abs(yp - yq) * np.cos(np.arctan(slope)) < limit
            found[(i, j)] = (lo, _tidy(close))
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


def build(paths: list[Path], terminals: list[Terminal], gauge: float) -> Network:
    """The network of the accepted paths: nodes, the pieces between them, the switches with
    their points and radii, and the crossings."""
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
    _classify(net, paths, gauge)
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


def _classify(net: Network, paths: list[Path], gauge: float) -> None:
    """Each event node made a switch, a crossing or an uncertain part, and the switches' points
    found from the leg's path."""
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
    base = _heading(trunk_path, node.x - sign * 60, node.x - sign * 4)
    turns = [
        abs(_heading(paths[leg.pid], node.x + sign * 4, node.x + sign * 60) - base) for leg in legs
    ]
    straight, diverging = (legs[0], legs[1]) if turns[0] <= turns[1] else (legs[1], legs[0])
    node.kind = "switch"
    fit = fit_points(paths[straight.pid], paths[diverging.pid], node.x, toward, gauge)
    if fit is not None:
        s0_x, radius, deviation, count = fit
        node.x = s0_x
        node.y = _y_at(paths[straight.pid], s0_x)
    else:
        radius, deviation, count = None, math.inf, 0
    net.switches.append(
        SwitchFit(node.id, trunk.id, straight.id, diverging.id, toward, radius, deviation, count)
    )


def fit_points(
    straight: Path, leg: Path, x_part: float, toward: str, gauge: float
) -> tuple[float, float, float, int] | None:
    """The points (as x) and the radius from d = (s - s0)² / 2R: the leg's distance from the
    straight path, as the square root, grows linearly from the points. The fit takes the leg
    from where it is FIT_MIN_DEPTH mm off to FIT_DEPTH_GAUGES gauges off, and trims what lies
    more than two deviations from the line."""
    sign = 1.0 if toward == "B" else -1.0
    span = 400.0
    lo, hi = sorted((x_part - sign * span, x_part + sign * span))
    lo = max(lo, straight.xs[0], leg.xs[0])
    hi = min(hi, straight.xs[-1], leg.xs[-1])
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
        x_cross = _cross_x(paths[upper_before.pid], paths[upper_after.pid], start.x, end.x)
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
