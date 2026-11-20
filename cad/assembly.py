"""Anläggningen (CAD-06, CAD9, CAD-10, CAD-20, CAD-21): modules placed gable to gable, the joints
checked, and the track graph of the whole, as pure functions without I/O.

Placement. The first module lies where the owner put it (at and angle, counterclockwise on the
screen, with y down as in the drawing), and so does the first module of any group that no joint
reaches. Every other module is placed by the first joint that reaches it: its gable turned to
face the other's, and moved so that the gables meet frame to frame, Kant 1 to Kant 1 when one is
A and the other B. A joint of A to A or B to B turns the second module round, so that its Kant 1
lies on the other side: its far edge meets the first's Kant 1, and its tracks are measured from
there. A curve gives its angle by its gable B; the joint's own angle turns the second module
about the middle of the joint's tracks. A joint between two modules that are already placed
closes a loop and is checked as it lies.

The joint check (CAD9): the same number of tracks, the same norm where both gables have one, and
each pair of tracks within JOINT_TOLERANCE of each other where they meet; a closing joint also
within CLOSING_TURN of its angle. What does not fit is a problem with its reason, and keeps the
assembly from Studio; the joint is still drawn where it lies.

The graph (CAD-10, CAD-20): every module's graph placed in the assembly's mm, its ids prefixed
with the module's id, and at every joint that fits each pair of tracks one node: the smaller of
the two ids, in the middle between them, with the pieces' ends moved there. The ids depend only
on the modules' own ids and which gables meet, so they stay when the assembly is changed, and
when a module is redrawn with its ids kept.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from cad import geometry
from contracts.cad import (
    CLOSING_TURN,
    JOINT_TOLERANCE,
    NORM_NAMES,
    ArcSegment,
    Gable,
    GableAt,
    GableEnd,
    GraphLabel,
    GraphNode,
    GraphPiece,
    GraphSwitch,
    GraphSymbol,
    Joint,
    JointCheck,
    LineSegment,
    Scale,
    Segment,
    Shape,
    TrackGraph,
)
from contracts.station_model import NodeType, Point

Placed = Literal["first", "joint", "free"]


@dataclass(frozen=True)
class Member:
    """A module in the assembly, at its pinned version, as the assembly uses it."""

    module: UUID
    version: int
    number: str
    name: str
    scale: Scale
    shape: Shape
    gables: tuple[Gable, ...]
    graph: TrackGraph
    labels: tuple[str, str] = ("Gavel A", "Gavel B")
    seen: bool = True

    @property
    def title(self) -> str:
        return f"{self.number} {self.name}" if self.seen else "En modul du inte ser"

    def gable(self, end: GableEnd) -> Gable:
        return next(g for g in self.gables if g.end == end)

    def line(self, end: GableEnd) -> geometry.GableLine:
        return geometry.gable_line(self.shape, geometry.track1_of(self.gables[0].tracks), end)

    def track_points(self, end: GableEnd) -> list[Point]:
        """Where the gable's tracks are, in the module, spår 1 first: the graph's module joints,
        or the gable's positions when the graph has not all of them."""
        gable = self.gable(end)
        nodes = sorted(
            (n for n in self.graph.nodes if n.type == NodeType.MODULE_JOINT and n.gable == end),
            key=lambda n: n.track or 0,
        )
        if [n.track for n in nodes] == list(range(1, len(gable.tracks) + 1)):
            return [n.at for n in nodes]
        line = self.line(end)
        return [line.point(t) for t in gable.tracks]

    def track_nodes(self, end: GableEnd) -> list[str] | None:
        """The graph's node ids of the gable's tracks, spår 1 first; None without all of them."""
        gable = self.gable(end)
        nodes = sorted(
            (n for n in self.graph.nodes if n.type == NodeType.MODULE_JOINT and n.gable == end),
            key=lambda n: n.track or 0,
        )
        if [n.track for n in nodes] != list(range(1, len(gable.tracks) + 1)):
            return None
        return [n.id for n in nodes]


@dataclass(frozen=True)
class Pose:
    """Where a module lies: its origin and its turn, counterclockwise on the screen (y down)."""

    at: Point = (0.0, 0.0)
    angle: float = 0.0

    def turn(self, v: Point) -> Point:
        return turn(self.angle, v)

    def point(self, p: Point) -> Point:
        x, y = self.turn(p)
        return (self.at[0] + x, self.at[1] + y)


def turn(angle: float, v: Point) -> Point:
    """v turned angle degrees counterclockwise as the screen shows it, with y down."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return (c * v[0] + s * v[1], -s * v[0] + c * v[1])


def _heading(v: Point) -> float:
    return math.degrees(math.atan2(v[1], v[0]))


def _normal(angle: float) -> float:
    """The angle in (-180, 180]."""
    found = math.fmod(angle, 360.0)
    if found <= -180:
        found += 360
    elif found > 180:
        found -= 360
    return found


def _between(a: Point, b: Point) -> float:
    """The angle between two directions, in degrees, 0–180."""
    return abs(_normal(_heading(a) - _heading(b)))


def _mid(points: Sequence[Point]) -> Point:
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


@dataclass(frozen=True)
class Placement:
    """Where every module lies, how it came there, and which joints close a loop."""

    poses: dict[UUID, Pose]
    placed: dict[UUID, Placed]
    closing: frozenset[int]


def place_from(
    pose_i: Pose, member_i: Member, end_i: GableEnd, member_j: Member, end_j: GableEnd, angle: float
) -> Pose:
    """Where module j lies when its gable end_j meets module i's end_i, turned angle degrees."""
    gi = member_i.line(end_i)
    corner = pose_i.point(gi.corner)
    along = pose_i.turn(gi.along)
    inward = pose_i.turn(gi.inward)
    gj = member_j.line(end_j)
    theta = _heading(gj.inward) - _heading((-inward[0], -inward[1]))
    # A to B meets Kant 1 to Kant 1; A to A or B to B meets j's Kant 1 at i's offset w_j.
    target = (
        corner
        if end_i != end_j
        else (
            corner[0] + along[0] * gj.width,
            corner[1] + along[1] * gj.width,
        )
    )
    origin = turn(theta, gj.corner)
    at = (target[0] - origin[0], target[1] - origin[1])
    if angle:
        tracks = [pose_i.point(p) for p in member_i.track_points(end_i)]
        pivot = (
            _mid(tracks)
            if tracks
            else (
                corner[0] + along[0] * gi.width / 2,
                corner[1] + along[1] * gi.width / 2,
            )
        )
        moved = turn(angle, (at[0] - pivot[0], at[1] - pivot[1]))
        at = (pivot[0] + moved[0], pivot[1] + moved[1])
        theta += angle
    return Pose(at=at, angle=_normal(theta))


def place(members: Sequence[Member], given: Sequence[Pose], joints: Sequence[Joint]) -> Placement:
    """Every module's pose: the first of each group as given, the others by their joints."""
    by_id = {m.module: m for m in members}
    poses: dict[UUID, Pose] = {}
    placed: dict[UUID, Placed] = {}
    used: set[int] = set()
    for member, pose in zip(members, given, strict=True):
        if member.module in poses:
            continue
        poses[member.module] = pose
        placed[member.module] = "first" if not placed else "free"
        grew = True
        while grew:
            grew = False
            for k, joint in enumerate(joints):
                if k in used:
                    continue
                a, b = joint.a, joint.b
                if a.module in poses and b.module not in poses:
                    i, end_i, j, end_j, angle = a.module, a.gable, b.module, b.gable, joint.angle
                elif b.module in poses and a.module not in poses:
                    i, end_i, j, end_j, angle = b.module, b.gable, a.module, a.gable, -joint.angle
                else:
                    continue
                poses[j] = place_from(poses[i], by_id[i], end_i, by_id[j], end_j, angle)
                placed[j] = "joint"
                used.add(k)
                grew = True
    closing = frozenset(k for k in range(len(joints)) if k not in used)
    return Placement(poses=poses, placed=placed, closing=closing)


# --- The joint check (CAD9) ---------------------------------------------------------------


def _mm(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _tracks(count: int) -> str:
    return "ett spår" if count == 1 else f"{count} spår" if count else "inga spår"


def check(
    index: int, joint: Joint, members: dict[UUID, Member], placement: Placement
) -> JointCheck:
    """Whether the joint's gables fit, and why not (CAD9)."""
    mi, mj = members[joint.a.module], members[joint.b.module]
    ei, ej = joint.a.gable, joint.b.gable
    gi, gj = mi.gable(ei), mj.gable(ej)
    pi, pj = placement.poses[mi.module], placement.poses[mj.module]
    closing = index in placement.closing
    problems: list[str] = []
    if len(gi.tracks) != len(gj.tracks):
        problems.append(
            f"Gavel {ei} på {mi.title} har {_tracks(len(gi.tracks))} och gavel {ej} på "
            f"{mj.title} har {_tracks(len(gj.tracks))}."
        )
    if gi.norm is not None and gj.norm is not None and gi.norm != gj.norm:
        problems.append(
            f"Gavlarna följer olika normer: {NORM_NAMES[gi.norm]} och {NORM_NAMES[gj.norm]}."
        )
    gap = 0.0
    if len(gi.tracks) == len(gj.tracks):
        here = [pi.point(p) for p in mi.track_points(ei)]
        there = [pj.point(p) for p in mj.track_points(ej)]
        if ei == ej:
            there.reverse()
        for n, (p, q) in enumerate(zip(here, there, strict=True), start=1):
            apart = math.dist(p, q)
            gap = max(gap, apart)
            if apart > JOINT_TOLERANCE:
                problems.append(
                    f"Spår {n} möts inte: {_mm(apart)} mm isär, högst {_mm(JOINT_TOLERANCE)} mm."
                )
    # The second gable faces the first, turned by the joint's angle.
    facing = pi.turn(mi.line(ei).inward)
    expected = turn(joint.angle, (-facing[0], -facing[1]))
    off = _between(pj.turn(mj.line(ej).inward), expected)
    if closing and off > CLOSING_TURN:
        problems.append(
            f"Skarven sluter inte: vinkeln är {_mm(off)}° fel, högst {_mm(CLOSING_TURN)}°."
        )
    return JointCheck(
        joint=index,
        fits=not problems,
        problems=problems,
        gap=round(gap, 2),
        turn=round(off, 2) if closing else 0,
        closing=closing,
    )


# --- What the page draws -------------------------------------------------------------------


def _round(p: Point) -> Point:
    return (round(p[0], 3), round(p[1], 3))


def gables_at(member: Member, pose: Pose, joined: Iterable[GableEnd]) -> list[GableAt]:
    """The module's two gables in the assembly."""
    taken = set(joined)
    found: list[GableAt] = []
    for gable, label in zip(member.gables, member.labels, strict=True):
        line = member.line(gable.end)
        found.append(
            GableAt(
                end=gable.end,
                corner=_round(pose.point(line.corner)),
                far=_round(pose.point(line.point(line.width))),
                tracks=[_round(pose.point(p)) for p in member.track_points(gable.end)],
                label=label,
                norm=gable.norm,
                joined=gable.end in taken,
            )
        )
    return found


def outline(member: Member, pose: Pose) -> list[Point]:
    track1 = geometry.track1_of(member.gables[0].tracks)
    return [_round(pose.point(p)) for p in geometry.outline(member.shape, track1, steps=24)]


# --- The track graph Till TKL Studio sends (CAD-10, CAD-20) --------------------------------


def _segment(segment: Segment, pose: Pose) -> Segment:
    if isinstance(segment, LineSegment):
        return LineSegment(
            start=_round(pose.point(segment.start)), end=_round(pose.point(segment.end))
        )
    return ArcSegment(
        start=_round(pose.point(segment.start)),
        end=_round(pose.point(segment.end)),
        center=_round(pose.point(segment.center)),
        radius=segment.radius,
        clockwise=segment.clockwise,
    )


def _snapped(segment: Segment, *, start: Point | None = None, end: Point | None = None) -> Segment:
    """The segment with an end moved onto a joint's node: a line's exactly, an arc's with its
    radius between its ends' distances from the centre, so that both stay on it."""
    a = start if start is not None else segment.start
    b = end if end is not None else segment.end
    if isinstance(segment, LineSegment):
        return LineSegment(start=a, end=b)
    radius = (math.dist(a, segment.center) + math.dist(b, segment.center)) / 2
    return ArcSegment(
        start=a, end=b, center=segment.center, radius=radius, clockwise=segment.clockwise
    )


def prefixed(module: UUID, ident: str) -> str:
    """An id in the assembly's graph: the module's id, then the module's own (CAD-20)."""
    return f"{module}:{ident}"


def graph(
    members: Sequence[Member],
    placement: Placement,
    joints: Sequence[Joint],
    checks: Sequence[JointCheck],
) -> TrackGraph:
    """The modules' graphs joined at the joints that fit, in the assembly's mm."""
    nodes: dict[str, GraphNode] = {}
    pieces: dict[str, GraphPiece] = {}
    switches: list[GraphSwitch] = []
    labels: list[GraphLabel] = []
    symbols: list[GraphSymbol] = []
    shown = [m for m in members if m.seen and m.module in placement.poses]
    for member in shown:
        pose = placement.poses[member.module]

        def p(ident: str, m: UUID = member.module) -> str:
            return prefixed(m, ident)

        def q(ident: str | None, m: UUID = member.module) -> str | None:
            return prefixed(m, ident) if ident is not None else None

        for n in member.graph.nodes:
            nodes[p(n.id)] = n.model_copy(update={"id": p(n.id), "at": _round(pose.point(n.at))})
        for piece in member.graph.pieces:
            pieces[p(piece.id)] = GraphPiece(
                id=p(piece.id),
                start=p(piece.start),
                end=p(piece.end),
                segments=[_segment(s, pose) for s in piece.segments],
                track=piece.track,
                origin=piece.origin,
            )
        for s in member.graph.switches:
            switches.append(
                s.model_copy(
                    update={
                        "id": p(s.id),
                        "node": p(s.node),
                        "trunk": q(s.trunk),
                        "straight": q(s.straight),
                        "diverging": q(s.diverging),
                    }
                )
            )
        for label in member.graph.labels:
            labels.append(
                label.model_copy(
                    update={
                        "id": p(label.id),
                        "at": _round(pose.point(label.at)),
                        "ref": q(label.ref),
                    }
                )
            )
        for symbol in member.graph.symbols:
            symbols.append(
                symbol.model_copy(
                    update={
                        "id": p(symbol.id),
                        "at": _round(pose.point(symbol.at)),
                        "piece": q(symbol.piece),
                        "label": q(symbol.label),
                    }
                )
            )
    by_id = {m.module: m for m in shown}
    for joint, found in zip(joints, checks, strict=True):
        a, b = by_id.get(joint.a.module), by_id.get(joint.b.module)
        if not found.fits or a is None or b is None:
            continue
        here, there = a.track_nodes(joint.a.gable), b.track_nodes(joint.b.gable)
        if here is None or there is None or len(here) != len(there):
            continue
        if joint.a.gable == joint.b.gable:
            there = there[::-1]
        for x, y in zip(here, there, strict=True):
            _merge(nodes, pieces, prefixed(a.module, x), prefixed(b.module, y))
    return TrackGraph(
        geometry="mm",
        nodes=list(nodes.values()),
        pieces=list(pieces.values()),
        switches=switches,
        labels=labels,
        symbols=symbols,
        complete=bool(shown)
        and len(shown) == len(members)
        and all(m.graph.complete for m in shown),
        issued=0,
    )


def _merge(
    nodes: dict[str, GraphNode], pieces: dict[str, GraphPiece], first: str, second: str
) -> None:
    """Two gables' nodes for one track become one: the smaller id, halfway between them."""
    if first not in nodes or second not in nodes:
        return
    keep, drop = sorted((first, second))
    a, b = nodes[keep].at, nodes[drop].at
    at = _round(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    nodes[keep] = nodes[keep].model_copy(update={"at": at})
    del nodes[drop]
    for ident, piece in list(pieces.items()):
        start = keep if piece.start == drop else piece.start
        end = keep if piece.end == drop else piece.end
        if keep not in (start, end):
            continue
        segments = list(piece.segments)
        if start == keep:
            segments[0] = _snapped(segments[0], start=at)
        if end == keep:
            segments[-1] = _snapped(segments[-1], end=at)
        pieces[ident] = GraphPiece(
            id=piece.id,
            start=start,
            end=end,
            segments=segments,
            track=piece.track,
            origin=piece.origin,
        )
