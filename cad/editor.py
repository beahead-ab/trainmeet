"""Ritningen's editing operations on the track graph (CAD-03), and the ids that stay (CAD-20).

A change set is a list of operations (contracts.cad.EditOp) on top of a saved version. The
service replays the whole list on that version every time, so the result is the same for the
same list, undo is the list one shorter, and nothing is kept between calls. Each operation is
checked, and the graph is validated after it: a refused operation says why, in Swedish.

The ids (CAD-20, bildkedjan step 12):
- a node, piece, switch or label that is moved, reshaped or recomputed keeps its id;
- only new things get new ids, from graph.issued, which only grows, so a deleted id is never
  used again;
- a piece that is split keeps its id on the first part (from its start, or from gable A in Lås
  mått), and the version records the split (old ids → new ids) in DrawingState.ids, so that
  Studio can follow the owner's additions along. A switch removed joins its two through pieces
  back into the first, and that is recorded too.

Reshaping: when a node moves, every piece on it is turned and scaled about its other end (a
similarity), so a LINE stays a LINE and an ARC an ARC, and the piece keeps its shape. A node at a
gable (a module joint) moves only along its gable.

A switch is a node where a diverging leg leaves a through track tangentially (lärdomarna,
Växlar): the trunk is the through piece behind the points and the straight the one ahead, seen
toward the gable the diverging leg heads for. The diverging leg is an arc of the switch's radius
and angle, and a straight after it.
"""

from __future__ import annotations

import functools
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from cad import curves, geometry, graph, lock, profiles, smoothing, switches
from cad.curves import Arc, Line, Seg
from contracts.cad import (
    POSITION_TOLERANCE,
    UNKNOWN_DESIGN,
    AddArc,
    AddLine,
    AddPolyline,
    AddSwitch,
    AnswerCheck,
    Certainty,
    CheckAnswer,
    Cut,
    Delete,
    DrawingSource,
    DrawingState,
    DrawnLine,
    EditOp,
    Gable,
    GableEnd,
    GableProfile,
    GraphLabel,
    GraphNode,
    GraphOrigin,
    GraphPiece,
    GraphSource,
    GraphSwitch,
    IdChange,
    Join,
    LockedMeasure,
    LockMeasures,
    LockRadii,
    Move,
    MoveSwitch,
    Scale,
    SetEnd,
    SetLabel,
    SetSmoothing,
    SetSwitch,
    Shape,
    Smoothing,
    TrackGraph,
)
from contracts.station_model import NodeType, Point, SwitchType

SNAP = 1.0
"""A new end within 1 mm of a free end is joined to it, and a point within 1 mm of a gable lies
on it."""
MIN_LENGTH = 1.0
"""The shortest piece the drawing makes, in mm."""
SAMPLE_STEP = 10.0
DRAWN = GraphOrigin(source=GraphSource.DRAWN, certainty=Certainty.CONFIRMED)
"""What the owner draws is theirs: confirmed (bildkedjan, principle 4)."""


class EditError(Exception):
    """An operation that cannot be done; the message says why, in Swedish."""


@dataclass
class Node:
    id: str
    type: NodeType
    at: Point
    gable: GableEnd | None = None
    track: int | None = None


@dataclass
class Piece:
    id: str
    start: str
    end: str
    segs: list[Seg]
    track: str | None = None
    origin: GraphOrigin | None = None


@dataclass
class Switch:
    id: str
    node: str
    type: SwitchType
    trunk: str | None
    straight: str | None
    diverging: str | None
    radius: float | None = None
    angle: float | None = None
    origin: GraphOrigin | None = None
    number: str | None = None
    design: str | None = None
    toward: GableEnd | None = None
    locked: bool = False


@dataclass
class Label:
    id: str
    text: str
    at: Point
    ref: str | None = None
    origin: GraphOrigin | None = None


@dataclass(frozen=True)
class LockPlan:
    """What Lås mått would do: the track, its ends, the old line and the new geometry."""

    chain: list[str]
    a_node: str
    b_node: str
    a: float
    b: float
    a_line: float
    b_line: float
    track_a: int
    track_b: int
    old: list[Point]
    radii: LockRadii
    solution: lock.Solution | None
    why: str


@functools.lru_cache(maxsize=256)
def _smoothed(
    points: tuple[Point, ...], level: Smoothing, scale: Scale, head: float | None
) -> tuple[Seg, ...]:
    return tuple(smoothing.smooth(points, level, scale, head))


@functools.lru_cache(maxsize=64)
def _locked(
    ends: lock.Ends, old: tuple[Point, ...], min_radius: float, same: bool
) -> lock.Solution | str:
    try:
        return lock.solve(ends, old, min_radius, same)
    except lock.NoSolution as no:
        return str(no)


@dataclass
class Drawing:
    """A module's drawing being edited: the graph as plain objects, and its drawing state."""

    scale: Scale
    shape: Shape
    gables: list[Gable]
    known: dict[str, GableProfile]
    nodes: dict[str, Node] = field(default_factory=dict)
    pieces: dict[str, Piece] = field(default_factory=dict)
    switches: dict[str, Switch] = field(default_factory=dict)
    labels: dict[str, Label] = field(default_factory=dict)
    issued: int = 0
    geometry_kind: str = "mm"
    source: DrawingSource = DrawingSource.MEASURES
    smoothing: Smoothing = Smoothing.NORMAL
    answers: dict[str, CheckAnswer] = field(default_factory=dict)
    lines: dict[str, DrawnLine] = field(default_factory=dict)
    locks: list[LockedMeasure] = field(default_factory=list)
    ids: list[IdChange] = field(default_factory=list)
    plan_approved: bool = False
    changed: bool = False

    # --- From and to the contracts -----------------------------------------------------------

    @classmethod
    def of(
        cls,
        scale: Scale,
        shape: Shape,
        gables: Sequence[Gable],
        built: TrackGraph,
        state: DrawingState,
        known: dict[str, GableProfile] | None = None,
    ) -> Drawing:
        made = cls(
            scale=scale,
            shape=shape,
            gables=list(gables),
            known=dict(known or profiles.SEEDED_BY_ID),
            issued=built.issued,
            geometry_kind=built.geometry,
            source=state.source,
            smoothing=state.smoothing,
            answers={a.key: a for a in state.answers},
            lines={line.piece: line for line in state.lines},
            locks=list(state.locks),
            ids=list(state.ids),
            plan_approved=state.plan_approved,
        )
        for n in built.nodes:
            made.nodes[n.id] = Node(n.id, n.type, n.at, n.gable, n.track)
        for p in built.pieces:
            made.pieces[p.id] = Piece(
                p.id,
                p.start,
                p.end,
                [curves.from_segment(s) for s in p.segments],
                p.track,
                p.origin,
            )
        for s in built.switches:
            made.switches[s.id] = Switch(
                s.id,
                s.node,
                s.type,
                s.trunk,
                s.straight,
                s.diverging,
                s.radius,
                s.angle,
                s.origin,
                s.number,
                s.design,
                s.toward,
                s.locked,
            )
        for x in built.labels:
            made.labels[x.id] = Label(x.id, x.text, x.at, x.ref, x.origin)
        return made

    def graph(self) -> TrackGraph:
        """The graph as the contract, validated."""
        joints = [n for n in self.nodes.values() if n.type == NodeType.MODULE_JOINT]
        try:
            return TrackGraph(
                geometry="mm" if self.geometry_kind == "mm" else "schema",
                nodes=[
                    GraphNode(id=n.id, type=n.type, at=_r(n.at), gable=n.gable, track=n.track)
                    for n in self.nodes.values()
                ],
                pieces=[
                    GraphPiece(
                        id=p.id,
                        start=p.start,
                        end=p.end,
                        segments=[curves.segment(s) for s in p.segs],
                        track=p.track,
                        origin=p.origin,
                    )
                    for p in self.pieces.values()
                ],
                switches=[
                    GraphSwitch(
                        id=s.id,
                        node=s.node,
                        type=s.type,
                        trunk=s.trunk,
                        straight=s.straight,
                        diverging=s.diverging,
                        radius=round(s.radius, 1) if s.radius else None,
                        angle=round(s.angle, 2) if s.angle else None,
                        origin=s.origin,
                        number=s.number,
                        design=s.design,
                        toward=s.toward,
                        locked=s.locked,
                    )
                    for s in self.switches.values()
                ],
                labels=[
                    GraphLabel(id=x.id, text=x.text, at=_r(x.at), ref=x.ref, origin=x.origin)
                    for x in self.labels.values()
                ],
                complete=all(self.count(n.id) > 0 for n in joints) if self.pieces else not joints,
                issued=self.issued,
            )
        except ValidationError as error:
            raise EditError(_first_error(error)) from error

    def state(self, keep_answers: set[str] | None = None) -> DrawingState:
        answers = [a for k, a in self.answers.items() if keep_answers is None or k in keep_answers]
        return DrawingState(
            source=self.source,
            smoothing=self.smoothing,
            answers=answers,
            lines=[line for p, line in self.lines.items() if p in self.pieces],
            locks=self.locks,
            ids=self.ids,
            plan_approved=self.plan_approved,
        )

    # --- Looking things up -------------------------------------------------------------------

    @property
    def track1(self) -> float:
        return geometry.track1_of(self.gables[0].tracks)

    def gable(self, end: GableEnd) -> Gable:
        return self.gables[0] if end == GableEnd.A else self.gables[1]

    def gable_line(self, end: GableEnd) -> geometry.GableLine:
        return geometry.gable_line(self.shape, self.track1, end)

    def from_a(self, p: Point) -> float:
        return geometry.from_a(self.shape, self.track1, p)

    def on(self, node: str) -> list[str]:
        """The pieces that start or end at the node."""
        return [p.id for p in self.pieces.values() if node in (p.start, p.end)]

    def count(self, node: str) -> int:
        return sum((p.start == node) + (p.end == node) for p in self.pieces.values())

    def away(self, piece: str, node: str) -> list[Seg]:
        """The piece's segments, running away from the node."""
        p = self.pieces[piece]
        return list(p.segs) if p.start == node else curves.reverse_path(p.segs)

    def other(self, piece: str, node: str) -> str:
        p = self.pieces[piece]
        return p.end if p.start == node else p.start

    def outward(self, node: str) -> float | None:
        """The heading out of a free end, continuing its one piece."""
        found = self.on(node)
        if len(found) != 1:
            return None
        toward = curves.reverse_path(self.away(found[0], node))
        return curves.end_heading(toward[-1])

    def switch_at(self, node: str) -> Switch | None:
        return next((s for s in self.switches.values() if s.node == node), None)

    def switch_of(self, piece: str) -> list[Switch]:
        return [s for s in self.switches.values() if piece in (s.trunk, s.straight, s.diverging)]

    def new_id(self, prefix: str) -> str:
        self.issued += 1
        return f"{prefix}{self.issued}"

    def name(self, ident: str) -> str:
        """A part as people say it."""
        if ident in self.switches:
            return f"växel {self.switches[ident].number or ident}"
        if ident in self.nodes:
            n = self.nodes[ident]
            if n.gable is not None and n.track is not None:
                return f"gavel {n.gable.value} spår {n.track}"
            return "änden"
        if ident in self.pieces and self.pieces[ident].track:
            return f"spår {self.pieces[ident].track}"
        return "spårbiten"

    # --- Applying -------------------------------------------------------------------------

    def apply_all(self, operations: Sequence[EditOp]) -> None:
        for index, op in enumerate(operations, start=1):
            try:
                self.apply(op)
            except EditError as error:
                raise EditError(f"Ändring {index} går inte: {error}") from error

    def apply(self, op: EditOp) -> None:
        handlers = {
            "line": self._line,
            "arc": self._arc,
            "polyline": self._polyline,
            "switch": self._switch,
            "move_switch": self._move_switch,
            "move": self._move,
            "delete": self._delete,
            "join": self._join,
            "cut": self._cut,
            "label": self._label,
            "end": self._end,
            "set_switch": self._set_switch,
            "answer": self._answer,
            "smoothing": self._smoothing,
            "lock": self._lock,
        }
        handlers[op.op](op)  # type: ignore[operator]
        self.changed = True
        self.validate()

    def validate(self) -> None:
        """The graph holds together after an operation, or EditError with why."""
        for p in self.pieces.values():
            if not p.segs or curves.path_length(p.segs) < 0.5:
                raise EditError("En spårbit blev för kort.")
        for n in list(self.nodes.values()):
            count = self.count(n.id)
            if n.type == NodeType.JOINT and count == 0:
                del self.nodes[n.id]
            elif n.type == NodeType.JOINT and count > 2:
                raise EditError("Tre spår möts i en punkt utan växel. Lägg en växel i stället.")
            elif n.type == NodeType.BUFFER_STOP and count != 1:
                raise EditError("En stoppbock sitter i änden av ett spår.")
            elif n.type == NodeType.MODULE_JOINT and count > 1:
                raise EditError(f"Bara ett spår går ut genom {self.name(n.id)}.")
            elif n.type == NodeType.SWITCH and count != 3:
                raise EditError("En växel har tre ben.")
        for s in self.switches.values():
            for leg in (s.trunk, s.straight, s.diverging):
                if (
                    leg is None
                    or leg not in self.pieces
                    or s.node
                    not in (
                        self.pieces[leg].start,
                        self.pieces[leg].end,
                    )
                ):
                    raise EditError(f"{self.name(s.id).capitalize()} har tappat ett ben.")
        self.graph()

    # --- Ends and nodes -------------------------------------------------------------------

    def _free(self, node: str) -> bool:
        n = self.nodes[node]
        count = self.count(node)
        if n.type == NodeType.JOINT:
            return count <= 1
        if n.type == NodeType.MODULE_JOINT:
            return count == 0
        return False

    def snap(self, p: Point, avoid: set[str] | None = None) -> str | None:
        found = [
            (math.dist(n.at, p), n.id)
            for n in self.nodes.values()
            if n.id not in (avoid or set()) and self._free(n.id) and math.dist(n.at, p) <= SNAP
        ]
        return min(found)[1] if found else None

    def _end(self, op: SetEnd) -> None:
        node = self.nodes.get(op.node)
        if node is None or node.type not in (NodeType.JOINT, NodeType.BUFFER_STOP):
            raise EditError("Bara en fri ände kan vara stoppbock.")
        if self.count(op.node) != 1:
            raise EditError("Bara en fri ände kan vara stoppbock.")
        node.type = NodeType.BUFFER_STOP if op.type == "buffer_stop" else NodeType.JOINT

    def _node_for(self, p: Point, node: str | None, avoid: set[str] | None = None) -> str:
        """The node a new piece ends in: the one named, a free end within SNAP, a new module
        joint on a gable, or a new end."""
        if node is not None:
            if node not in self.nodes:
                raise EditError("Änden finns inte.")
            if not self._free(node):
                n = self.nodes[node]
                if n.type == NodeType.SWITCH:
                    raise EditError("Växelns ben är upptagna. Lägg en ny växel i stället.")
                raise EditError(f"{self.name(node).capitalize()} är redan ihopkopplad.")
            return node
        snapped = self.snap(p, avoid)
        if snapped is not None:
            return snapped
        for end in (GableEnd.A, GableEnd.B):
            line = self.gable_line(end)
            offset = line.offset(p)
            if abs(line.depth(p)) <= SNAP and -SNAP <= offset <= line.width + SNAP:
                offset = min(max(offset, 0.0), line.width)
                track = self.gable_track(end, offset)
                made = self.new_id("n")
                self.nodes[made] = Node(made, NodeType.MODULE_JOINT, line.point(offset), end, track)
                return made
        if not geometry.inside(self.shape, self.track1, p):
            raise EditError("Spåret går utanför modulen.")
        made = self.new_id("n")
        self.nodes[made] = Node(made, NodeType.JOINT, p)
        return made

    def gable_track(self, end: GableEnd, offset: float) -> int | None:
        taken = {n.track for n in self.nodes.values() if n.gable == end}
        for number, position in enumerate(self.gable(end).tracks, start=1):
            if abs(position - offset) <= POSITION_TOLERANCE:
                if number in taken:
                    raise EditError(f"Gavel {end.value} spår {number} har redan ett spår.")
                return number
        return None

    def _inside(self, segs: Sequence[Seg]) -> None:
        for p in curves.sample_path(segs, SAMPLE_STEP):
            if not geometry.inside(self.shape, self.track1, p):
                raise EditError("Spåret går utanför modulen.")

    def add_piece(
        self,
        segs: list[Seg],
        start_node: str | None,
        end_node: str | None,
        origin: GraphOrigin = DRAWN,
        *,
        own_start: bool = False,
    ) -> Piece:
        """A new piece from the segments, its ends joined or made. own_start: the start node is
        the caller's, a switch being made."""
        if curves.path_length(segs) < MIN_LENGTH:
            raise EditError("Spåret är för kort.")
        if own_start and start_node is not None:
            start = start_node
        else:
            start = self._node_for(segs[0].start, start_node)
        end = self._node_for(segs[-1].end, end_node, avoid={start})
        if start == end:
            raise EditError("Spåret börjar och slutar i samma punkt.")
        segs = curves.reshaped(segs, self.nodes[start].at, self.nodes[end].at)
        self._inside(segs)
        piece = Piece(self.new_id("s"), start, end, segs, None, origin)
        self.pieces[piece.id] = piece
        self.source = DrawingSource.DRAWN if self.source == DrawingSource.MEASURES else self.source
        return piece

    def _start_heading(self, node: str | None, p: Point) -> float | None:
        """The heading a new track from the node continues with: its other piece's, or at a
        gable at right angles into the module."""
        target = node if node is not None else self.snap(p)
        if target is None:
            for end in (GableEnd.A, GableEnd.B):
                line = self.gable_line(end)
                if abs(line.depth(p)) <= SNAP and 0 <= line.offset(p) <= line.width:
                    return curves.heading((0.0, 0.0), line.inward)
            return None
        n = self.nodes[target]
        if n.type == NodeType.MODULE_JOINT and n.gable is not None:
            return curves.heading((0.0, 0.0), self.gable_line(n.gable).inward)
        return self.outward(target)

    # --- Drawing tracks -------------------------------------------------------------------

    def _line(self, op: AddLine) -> None:
        start = self.nodes[op.start_node].at if op.start_node in self.nodes else op.start
        end = self.nodes[op.end_node].at if op.end_node in self.nodes else op.end
        self.add_piece([Line(start, end)], op.start_node, op.end_node)

    def _arc(self, op: AddArc) -> None:
        start = self.nodes[op.start_node].at if op.start_node in self.nodes else op.start
        if op.through is not None and op.end is not None:
            end = self.nodes[op.end_node].at if op.end_node in self.nodes else op.end
            made = curves.arc_through(start, op.through, end)
            if made is None:
                raise EditError("Bågens tre punkter måste vara olika.")
            self.add_piece([made], op.start_node, op.end_node)
            return
        assert op.radius is not None and op.angle is not None
        head = (
            math.radians(op.heading)
            if op.heading is not None
            else self._start_heading(op.start_node, start)
        )
        if head is None:
            raise EditError("Ange riktningen, eller börja bågen i änden av ett spår.")
        made = curves.arc_turning(start, head, op.radius, math.radians(op.angle))
        self.add_piece([made], op.start_node, op.end_node)

    def _polyline(self, op: AddPolyline) -> None:
        points = list(op.points)
        if op.start_node in self.nodes:
            points[0] = self.nodes[op.start_node].at
        if op.end_node in self.nodes:
            points[-1] = self.nodes[op.end_node].at
        head = self._start_heading(op.start_node, points[0])
        segs = self._smooth(points, head)
        piece = self.add_piece(segs, op.start_node, op.end_node)
        self.lines[piece.id] = DrawnLine(piece=piece.id, points=[_r(p) for p in op.points])

    def _smooth(self, points: Sequence[Point], head: float | None) -> list[Seg]:
        try:
            return list(
                _smoothed(
                    tuple(points),
                    self.smoothing,
                    self.scale,
                    round(head, 9) if head is not None else None,
                )
            )
        except ValueError as error:
            raise EditError(str(error)) from error

    def _smoothing(self, op: SetSmoothing) -> None:
        """The level, and every drawn line made again at it; the pieces keep their ids."""
        self.smoothing = op.level
        for piece_id, line in list(self.lines.items()):
            piece = self.pieces.get(piece_id)
            if piece is None or line.source != "hand":
                continue
            points = list(line.points)
            points[0] = self.nodes[piece.start].at
            points[-1] = self.nodes[piece.end].at
            head = self._continuing(piece.start, piece.id)
            segs = self._smooth(points, head)
            piece.segs = curves.reshaped(segs, points[0], points[-1])

    def _continuing(self, node: str, piece: str) -> float | None:
        """The heading a piece leaving the node should start with: the other piece's there,
        or at right angles into the module at a gable."""
        n = self.nodes[node]
        if n.type == NodeType.MODULE_JOINT and n.gable is not None:
            return curves.heading((0.0, 0.0), self.gable_line(n.gable).inward)
        others = [p for p in self.on(node) if p != piece]
        if len(others) != 1 or n.type == NodeType.SWITCH:
            return None
        before = curves.reverse_path(self.away(others[0], node))
        return curves.end_heading(before[-1])

    # --- Splitting and joining pieces -----------------------------------------------------

    def _split(self, piece_id: str, s: float, why: str) -> tuple[Piece, Piece, Node]:
        """The piece cut s mm from its start, at a new node: the first part keeps the id."""
        piece = self.pieces[piece_id]
        total = curves.path_length(piece.segs)
        if s < MIN_LENGTH or s > total - MIN_LENGTH:
            raise EditError("För nära spårbitens ände.")
        first, second = curves.split_path(piece.segs, s)
        at = first[-1].end
        node = Node(self.new_id("n"), NodeType.JOINT, at)
        self.nodes[node.id] = node
        rest = Piece(self.new_id("s"), node.id, piece.end, second, piece.track, piece.origin)
        old_end = piece.end
        piece.segs = first
        piece.end = node.id
        self.pieces[rest.id] = rest
        for sw in self.switches.values():
            if sw.node == old_end:
                for leg in ("trunk", "straight", "diverging"):
                    if getattr(sw, leg) == piece.id:
                        setattr(sw, leg, rest.id)
        self.lines.pop(piece.id, None)
        self.ids.append(IdChange(old=[piece.id], new=[piece.id, rest.id], why=why))  # type: ignore[arg-type]
        return piece, rest, node

    def _cut(self, op: Cut) -> None:
        if op.piece not in self.pieces:
            raise EditError("Spårbiten finns inte.")
        s, off = curves.project_path(self.pieces[op.piece].segs, op.at)
        if off > 20:
            raise EditError("Klipp på spåret.")
        self._split(op.piece, s, "cut")

    def _join(self, op: Join) -> None:
        if op.a == op.b or op.a not in self.nodes or op.b not in self.nodes:
            raise EditError("Välj två olika ändar.")
        a, b = self.nodes[op.a], self.nodes[op.b]
        for n in (a, b):
            if n.type not in (NodeType.JOINT, NodeType.MODULE_JOINT, NodeType.BUFFER_STOP):
                raise EditError("Bara fria ändar kan kopplas ihop.")
        on_a, on_b = self.on(a.id), self.on(b.id)
        if len(on_a) + len(on_b) != 2 or len(on_a) > 1 or len(on_b) > 1:
            raise EditError("Bara fria ändar kan kopplas ihop.")
        if on_a and on_b and on_a[0] == on_b[0]:
            raise EditError("Ändarna hör till samma spårbit.")
        if math.dist(a.at, b.at) > 200:
            raise EditError("Ändarna ligger mer än 200 mm isär. Rita ett spår mellan dem.")
        keep, drop = (a, b)
        if b.type == NodeType.MODULE_JOINT:
            keep, drop = b, a
        if keep.type == NodeType.MODULE_JOINT and self.count(keep.id) > 0:
            raise EditError(f"{self.name(keep.id).capitalize()} är redan ihopkopplad.")
        if drop.type == NodeType.MODULE_JOINT:
            raise EditError("Två gavelspår kopplas ihop med ett spår emellan.")
        meet = keep.at if keep.type == NodeType.MODULE_JOINT else _mid(a.at, b.at)
        for n in (keep, drop):
            self._move_node_to(n.id, meet)
        for p in self.pieces.values():
            if p.start == drop.id:
                p.start = keep.id
            if p.end == drop.id:
                p.end = keep.id
        del self.nodes[drop.id]
        if keep.type == NodeType.BUFFER_STOP:
            keep.type = NodeType.JOINT

    # --- Moving -----------------------------------------------------------------------------

    def _reshape(self, piece_id: str, node: str, to: Point) -> None:
        p = self.pieces[piece_id]
        start = to if p.start == node else p.segs[0].start
        end = to if p.end == node else p.segs[-1].end
        if math.dist(start, end) < MIN_LENGTH:
            raise EditError("Spårbiten blir för kort.")
        how = curves.mapping(p.segs[0].start, p.segs[-1].end, start, end)
        p.segs = [curves.moved(s, how) for s in p.segs]
        line = self.lines.get(piece_id)
        if line is not None:
            self.lines[piece_id] = line.model_copy(
                update={"points": [_r(how(q)) for q in line.points]}
            )

    def _move_node_to(self, node: str, to: Point) -> None:
        n = self.nodes[node]
        if n.type == NodeType.MODULE_JOINT and n.gable is not None:
            line = self.gable_line(n.gable)
            to = line.point(min(max(line.offset(to), 0.0), line.width))
        for piece in self.on(node):
            self._reshape(piece, node, to)
        n.at = to

    def _move(self, op: Move) -> None:
        target = op.target
        if target in self.labels:
            x = self.labels[target]
            x.at = curves.add(x.at, op.by)
            return
        if target in self.switches or (target in self.nodes and self.switch_at(target)):
            sw = self.switches.get(target) or self.switch_at(target)
            assert sw is not None
            self._move_switch_rigid(sw, op.by)
            return
        if target in self.nodes:
            n = self.nodes[target]
            self._move_node_to(target, curves.add(n.at, op.by))
            for piece in self.on(target):
                self._inside(self.pieces[piece].segs)
            return
        if target in self.pieces:
            p = self.pieces[target]
            for end in (p.start, p.end):
                if self.nodes[end].type == NodeType.SWITCH:
                    raise EditError("Spårbiten sitter i en växel. Flytta växeln i stället.")
            moves = {end: curves.add(self.nodes[end].at, op.by) for end in (p.start, p.end)}
            for end, to in moves.items():
                n = self.nodes[end]
                if n.type == NodeType.MODULE_JOINT and n.gable is not None:
                    edge = self.gable_line(n.gable)
                    moves[end] = edge.point(min(max(edge.offset(to), 0.0), edge.width))
            how = curves.mapping(p.segs[0].start, p.segs[-1].end, moves[p.start], moves[p.end])
            p.segs = [curves.moved(s, how) for s in p.segs]
            drawn = self.lines.get(p.id)
            if drawn is not None:
                self.lines[p.id] = drawn.model_copy(
                    update={"points": [_r(how(q)) for q in drawn.points]}
                )
            for end, to in moves.items():
                for other in self.on(end):
                    if other != p.id:
                        self._reshape(other, end, to)
                self.nodes[end].at = to
            for end in moves:
                for piece in self.on(end):
                    self._inside(self.pieces[piece].segs)
            return
        raise EditError("Det finns inget sådant att flytta.")

    def _move_switch_rigid(self, sw: Switch, by: Point) -> None:
        """The switch moved as it is: its points and diverging leg, the through pieces
        reshaped to meet it."""
        node = self.nodes[sw.node]
        to = curves.add(node.at, by)
        assert sw.diverging is not None
        far = self.other(sw.diverging, sw.node)
        free = self._free_far(sw.diverging, far)
        for leg in (sw.trunk, sw.straight):
            assert leg is not None
            self._reshape(leg, sw.node, to)
        d = self.pieces[sw.diverging]
        if free:
            shift = curves.shift(by)
            d.segs = [curves.moved(s, shift) for s in d.segs]
            self.nodes[far].at = curves.add(self.nodes[far].at, by)
        else:
            self._reshape(sw.diverging, sw.node, to)
        node.at = to
        for leg in (sw.trunk, sw.straight, sw.diverging):
            assert leg is not None
            self._inside(self.pieces[leg].segs)

    def _free_far(self, piece: str, far: str) -> bool:
        n = self.nodes[far]
        return (
            n.type in (NodeType.JOINT, NodeType.BUFFER_STOP)
            and self.count(far) == 1
            and (piece in self.on(far))
        )

    # --- Switches ---------------------------------------------------------------------------

    def _s_from_a(self, segs: Sequence[Seg], target: float) -> float:
        """How far along the chain the point target mm from gable A lies."""
        total = curves.path_length(segs)
        f0 = self.from_a(curves.path_point(segs, 0)) - target
        f1 = self.from_a(curves.path_point(segs, total)) - target
        if f0 * f1 > 0:
            low, high = sorted((target - f0, target - f1))
            raise EditError(
                f"Spåret går från {low:.0f} till {high:.0f} mm från gavel A; växeln hamnar utanför."
            )
        lo, hi = 0.0, total
        for _ in range(60):
            mid = (lo + hi) / 2
            fm = self.from_a(curves.path_point(segs, mid)) - target
            if (fm <= 0) == (f0 <= 0):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def _next_number(self) -> str:
        numbers = [int(s.number) for s in self.switches.values() if s.number and s.number.isdigit()]
        return str(max(numbers, default=0) + 1)

    def _forward_is_b(self, segs: Sequence[Seg], s: float) -> bool:
        total = curves.path_length(segs)
        a = self.from_a(curves.path_point(segs, max(0.0, s - 1)))
        b = self.from_a(curves.path_point(segs, min(total, s + 1)))
        return b >= a

    def _leg(
        self, at: Point, head: float, radius: float, angle: float, right: bool, tail: float
    ) -> list[Seg]:
        turn = math.radians(angle) * (1 if right else -1)
        arc = curves.arc_turning(at, head, radius, turn)
        segs: list[Seg] = [arc]
        if tail > 0:
            segs.append(curves.line_from(arc.end, curves.end_heading(arc), tail))
        return segs

    def _switch(self, op: AddSwitch) -> None:
        if op.piece not in self.pieces:
            raise EditError("Spårbiten finns inte.")
        design = switches.BY_ID.get(op.design or UNKNOWN_DESIGN)
        if design is None or (design.scale not in (None, self.scale)):
            raise EditError("Växeltypen finns inte i skalan.")
        piece = self.pieces[op.piece]
        s = self._s_from_a(piece.segs, op.from_a)
        at = curves.path_point(piece.segs, s)
        forward_b = self._forward_is_b(piece.segs, s)
        radius = design.radius or op.radius
        target: Point | None = None
        if op.to is not None:
            target = self.nodes[op.to_node].at if op.to_node in self.nodes else op.to
            toward = GableEnd.B if self.from_a(target) >= self.from_a(at) else GableEnd.A
        else:
            toward = op.toward
        forward = forward_b == (toward == GableEnd.B)
        head = curves.path_heading(piece.segs, s)
        if not forward:
            head = curves.wrap(head + math.pi)
        if target is not None:
            right = curves.cross(curves.unit(head), curves.sub(target, at)) > 0
            found = curves.arc_then_line(at, head, radius, right, target)
            if found is None:
                raise EditError(f"Benet når inte dit med radien {radius:.0f} mm.")
            turn, tail = found
            angle = math.degrees(abs(turn))
            if not 0.1 < angle < 90:
                raise EditError("Benet lämnar spåret för brant: mer än 90°.")
            arc = curves.arc_turning(at, head, radius, turn)
            leg: list[Seg] = [arc] + ([Line(arc.end, target)] if tail > 1e-6 else [])
        else:
            assert op.angle is not None and op.side is not None
            angle = design.angle or op.angle
            leg = self._leg(at, head, radius, angle, op.side == "right", op.tail)
        first, rest, node = self._split(op.piece, s, "switch")
        node.type = NodeType.SWITCH
        diverging = self.add_piece(leg, node.id, op.to_node, own_start=True)
        sw = Switch(
            id=self.new_id("v"),
            node=node.id,
            type=SwitchType.ORDINARY,
            trunk=first.id if forward else rest.id,
            straight=rest.id if forward else first.id,
            diverging=diverging.id,
            radius=radius,
            angle=angle,
            origin=DRAWN,
            number=self._next_number(),
            design=None if design.id == UNKNOWN_DESIGN else design.id,
            toward=toward,
        )
        self.switches[sw.id] = sw

    def _through(self, sw: Switch) -> tuple[list[Seg], float]:
        """The switch's through track, trunk then straight, as one chain toward the gable the
        diverging leg heads for, and where the points lie on it."""
        assert sw.trunk is not None and sw.straight is not None
        behind = curves.reverse_path(self.away(sw.trunk, sw.node))
        ahead = self.away(sw.straight, sw.node)
        return behind + ahead, curves.path_length(behind)

    def _set_through(self, sw: Switch, chain: list[Seg], s: float) -> None:
        """The through track cut at s again: the trunk and straight keep their ids and ends."""
        assert sw.trunk is not None and sw.straight is not None
        behind, ahead = curves.split_path(chain, s)
        trunk, straight = self.pieces[sw.trunk], self.pieces[sw.straight]
        trunk.segs = behind if trunk.end == sw.node else curves.reverse_path(behind)
        straight.segs = ahead if straight.start == sw.node else curves.reverse_path(ahead)
        for leg in (sw.trunk, sw.straight):
            self.lines.pop(leg, None)

    def _place_leg(self, sw: Switch, at: Point, head: float) -> None:
        """The diverging leg from the points: moved as it is when its far end is free, else
        bent to keep its far end (arc of the switch's radius, then straight)."""
        assert sw.diverging is not None
        d = self.pieces[sw.diverging]
        far = self.other(sw.diverging, sw.node)
        segs = self.away(sw.diverging, sw.node)
        old_head = curves.start_heading(segs[0])
        right = curves.turn_of(segs[0]) >= 0
        if self._free_far(sw.diverging, far):
            how = curves.Similarity(
                complex(math.cos(head - old_head), math.sin(head - old_head)), 0j
            )
            turned = [curves.moved(x, how) for x in segs]
            shift = curves.sub(at, turned[0].start)
            new = [curves.moved(x, curves.shift(shift)) for x in turned]
            self.nodes[far].at = new[-1].end
        else:
            radius = sw.radius or (segs[0].radius if isinstance(segs[0], Arc) else 500.0)
            found = curves.arc_then_line(at, head, radius, right, self.nodes[far].at)
            if found is None:
                raise EditError(
                    f"Det avvikande benet når inte fram till {self.name(far)} med radien "
                    f"{radius:.0f} mm."
                )
            turn, tail = found
            arc = curves.arc_turning(at, head, radius, turn)
            new = [arc]
            if tail > 1e-6:
                new.append(Line(arc.end, self.nodes[far].at))
            sw.angle = math.degrees(abs(turn))
        d.segs = new if d.start == sw.node else curves.reverse_path(new)
        self.lines.pop(sw.diverging, None)
        self._inside(d.segs)

    def _move_switch(self, op: MoveSwitch) -> None:
        sw = self.switches.get(op.switch)
        if sw is None:
            raise EditError("Växeln finns inte.")
        chain, _ = self._through(sw)
        s = self._s_from_a(chain, op.from_a)
        total = curves.path_length(chain)
        if s < MIN_LENGTH or s > total - MIN_LENGTH:
            raise EditError("Växeln kan inte flyttas förbi spårets ände.")
        at = curves.path_point(chain, s)
        head = curves.path_heading(chain, s)
        self._set_through(sw, chain, s)
        self.nodes[sw.node].at = at
        self._place_leg(sw, at, head)

    def _set_switch(self, op: SetSwitch) -> None:
        sw = self.switches.get(op.switch)
        if sw is None:
            raise EditError("Växeln finns inte.")
        if op.locked is not None:
            sw.locked = op.locked
        radius = op.radius
        angle = None
        if op.design is not None:
            design = switches.BY_ID.get(op.design)
            if design is None or design.scale not in (None, self.scale):
                raise EditError("Växeltypen finns inte i skalan.")
            sw.design = None if design.id == UNKNOWN_DESIGN else design.id
            if design.radius is not None:
                radius, angle = design.radius, design.angle
        if radius is None:
            return
        assert sw.diverging is not None
        segs = self.away(sw.diverging, sw.node)
        far = self.other(sw.diverging, sw.node)
        sw.radius = radius
        if self._free_far(sw.diverging, far):
            tail = sum(curves.length(x) for x in segs[1:])
            right = curves.turn_of(segs[0]) >= 0
            use = angle or sw.angle or math.degrees(abs(curves.turn_of(segs[0])))
            new = self._leg(segs[0].start, curves.start_heading(segs[0]), radius, use, right, tail)
            d = self.pieces[sw.diverging]
            d.segs = new if d.start == sw.node else curves.reverse_path(new)
            self.nodes[far].at = new[-1].end
            sw.angle = use
            self.lines.pop(sw.diverging, None)
            self._inside(d.segs)
        else:
            self._place_leg(sw, segs[0].start, curves.start_heading(segs[0]))

    # --- Deleting ---------------------------------------------------------------------------

    def _delete(self, op: Delete) -> None:
        target = op.target
        if target in self.labels:
            del self.labels[target]
        elif target in self.switches:
            self._remove_switch(self.switches[target])
        elif target in self.pieces:
            for sw in self.switch_of(target):
                if sw.diverging == target:
                    self._remove_switch(sw)
                    return
                raise EditError(f"Spårbiten går genom {self.name(sw.id)}. Ta bort växeln först.")
            self._remove_piece(target)
        elif target in self.nodes:
            n = self.nodes[target]
            if n.type == NodeType.SWITCH:
                found = self.switch_at(target)
                assert found is not None
                self._remove_switch(found)
            elif n.type == NodeType.MODULE_JOINT:
                raise EditError("Gavelns spår ändras i måtten, under Ändra måtten.")
            else:
                for piece in self.on(target):
                    self._delete(Delete(target=piece))
        else:
            raise EditError("Det finns inget sådant att ta bort.")

    def _remove_piece(self, piece_id: str) -> None:
        piece = self.pieces.pop(piece_id)
        self.lines.pop(piece_id, None)
        for x in [x for x in self.labels.values() if x.ref == piece_id]:
            del self.labels[x.id]
        for end in (piece.start, piece.end):
            n = self.nodes.get(end)
            if n is not None and n.type == NodeType.BUFFER_STOP and self.count(end) == 0:
                del self.nodes[end]

    def _remove_switch(self, sw: Switch) -> None:
        """The switch gone: its diverging leg removed and its through pieces one again."""
        assert sw.trunk and sw.straight and sw.diverging
        self._remove_piece(sw.diverging)
        trunk, straight = self.pieces[sw.trunk], self.pieces[sw.straight]
        first, second = (trunk, straight) if trunk.end == sw.node else (straight, trunk)
        if first.end != sw.node:
            first.segs = curves.reverse_path(first.segs)
            first.start, first.end = first.end, first.start
        tail = self.away(second.id, sw.node)
        first.segs = [*first.segs, *tail]
        first.end = self.other(second.id, sw.node)
        for other in self.switches.values():
            if other.id != sw.id:
                for leg in ("trunk", "straight", "diverging"):
                    if getattr(other, leg) == second.id:
                        setattr(other, leg, first.id)
        del self.pieces[second.id]
        self.lines.pop(first.id, None)
        self.lines.pop(second.id, None)
        for x in [x for x in self.labels.values() if x.ref in (sw.id, second.id)]:
            del self.labels[x.id]
        del self.switches[sw.id]
        del self.nodes[sw.node]
        self.ids.append(IdChange(old=[first.id, second.id], new=[first.id], why="switch_removed"))

    # --- Text -------------------------------------------------------------------------------

    def _label(self, op: SetLabel) -> None:
        text = op.text.strip()
        target = op.target
        if target in self.pieces:
            self.pieces[target].track = text or None
            return
        if target in self.switches:
            self.switches[target].number = text or self._next_number()
            return
        if target in self.labels:
            if text:
                self.labels[target].text = text
            else:
                del self.labels[target]
            return
        if target is not None:
            raise EditError("Det finns inget sådant att skriva på.")
        if op.at is None or not text:
            raise EditError("Skriv texten och var den står.")
        made = Label(self.new_id("e"), text, op.at, None, DRAWN)
        self.labels[made.id] = made

    # --- Att kolla -------------------------------------------------------------------------

    def _answer(self, op: AnswerCheck) -> None:
        from cad import checks  # the rules read this module's drawing

        found = {c.key: c for c in checks.find(self)}
        item = found.get(op.key)
        if item is None:
            raise EditError("Den saken att kolla finns inte längre.")
        choice = next((c for c in item.choices if c.id == op.answer and c.closes), None)
        if choice is None:
            raise EditError("Svaret finns inte.")
        self.answers[op.key] = CheckAnswer(key=op.key, answer=op.answer)
        checks.effect(self, item, op.answer)

    # --- Lås mått ---------------------------------------------------------------------------

    def _chain(self, piece_id: str | None) -> tuple[list[str], str, str]:
        """The track from gable A to gable B through the piece: its pieces from A, and the
        nodes at A and B. Null piece: the first such track without a switch."""
        if piece_id is not None:
            if piece_id not in self.pieces:
                raise EditError("Spårbiten finns inte.")
            found = self._chain_through(piece_id)
            if isinstance(found, str):
                raise EditError(found)
            return found
        for start in self.pieces:
            tried = self._chain_through(start)
            if not isinstance(tried, str):
                return tried
        raise EditError("Inget spår utan växlar går från gavel A till gavel B.")

    def _chain_through(self, start: str) -> tuple[list[str], str, str] | str:
        ends: list[tuple[list[str], str]] = []
        for node in (self.pieces[start].start, self.pieces[start].end):
            walked: list[str] = []
            current_piece, current = start, node
            seen = {start}
            while True:
                n = self.nodes[current]
                if n.type == NodeType.SWITCH:
                    sw = self.switch_at(current)
                    assert sw is not None
                    return (
                        f"Spåret har {self.name(sw.id)} mellan gavlarna. Lås mått räknar om ett "
                        "spår utan växlar: lås måttet innan växeln läggs, eller ta bort växeln "
                        "och lägg den igen efteråt."
                    )
                following = [p for p in self.on(current) if p != current_piece]
                if n.type != NodeType.JOINT or len(following) != 1 or following[0] in seen:
                    break
                current_piece = following[0]
                seen.add(current_piece)
                walked.append(current_piece)
                current = self.other(current_piece, current)
            ends.append((walked, current))
        (back, first_end), (ahead, second_end) = ends
        a, b = self.nodes[first_end], self.nodes[second_end]
        chain = [*reversed(back), start, *ahead]
        if a.gable == GableEnd.B and b.gable == GableEnd.A:
            a, b, chain = b, a, list(reversed(chain))
        if a.gable != GableEnd.A or b.gable != GableEnd.B:
            return "Spåret går inte från gavel A till gavel B."
        if a.track is None or b.track is None:
            return "Spåret når gavlarna där gavlarna inte har något spår."
        return chain, a.id, b.id

    def _chain_segs(self, chain: Sequence[str], a_node: str) -> list[Seg]:
        segs: list[Seg] = []
        at = a_node
        for piece in chain:
            segs.extend(self.away(piece, at))
            at = self.other(piece, at)
        return segs

    def locked_default(self, end: GableEnd, track: int) -> float:
        """The value Lås mått offers: the profile's fixed position, else the gable's measure."""
        gable = self.gable(end)
        profile = self.known.get(gable.profile) if gable.profile else None
        if profile is not None:
            fixed = profiles.positions(profile)
            if track <= len(fixed) and fixed[track - 1] is not None:
                value = fixed[track - 1]
                assert value is not None
                return value
        return gable.tracks[track - 1]

    def lock_plan(self, op: LockMeasures) -> LockPlan:
        chain, a_node, b_node = self._chain(op.piece)
        na, nb = self.nodes[a_node], self.nodes[b_node]
        assert na.track is not None and nb.track is not None
        a = op.a if op.a is not None else self.locked_default(GableEnd.A, na.track)
        b = op.b if op.b is not None else self.locked_default(GableEnd.B, nb.track)
        line_a, line_b = self.gable_line(GableEnd.A), self.gable_line(GableEnd.B)
        for end, value, line in ((GableEnd.A, a, line_a), (GableEnd.B, b, line_b)):
            if not 0 < value < line.width:
                raise EditError(f"Gavel {end.value}: {value:g} mm ligger utanför gaveln.")
        old = curves.sample_path(self._chain_segs(chain, a_node), SAMPLE_STEP)
        ends = lock.Ends(
            line_a.point(a),
            curves.heading((0.0, 0.0), line_a.inward),
            line_b.point(b),
            curves.heading((0.0, 0.0), (-line_b.inward[0], -line_b.inward[1])),
        )
        limits = switches.limits(self.scale)
        try:
            self._check_gable(GableEnd.A, na.track, a)
            self._check_gable(GableEnd.B, nb.track, b)
        except EditError as refused:
            found: lock.Solution | str = str(refused)
        else:
            found = _locked(ends, tuple(old), limits.min_radius, op.radii == LockRadii.SAME)
        solution = found if isinstance(found, lock.Solution) else None
        why = found if isinstance(found, str) else ""
        return LockPlan(
            chain=chain,
            a_node=a_node,
            b_node=b_node,
            a=a,
            b=b,
            a_line=line_a.offset(na.at),
            b_line=line_b.offset(nb.at),
            track_a=na.track,
            track_b=nb.track,
            old=old,
            radii=op.radii,
            solution=solution,
            why=why,
        )

    def _lock(self, op: LockMeasures) -> None:
        plan = self.lock_plan(op)
        if plan.solution is None:
            raise EditError(plan.why)
        parts = plan.solution.segs
        first = self.pieces[plan.chain[0]]
        # Locked by the owner: confirmed (bildkedjan, principle 4).
        track, origin = first.track, DRAWN
        for piece in plan.chain:
            self.lines.pop(piece, None)
            gone = self.pieces.pop(piece)
            for end in (gone.start, gone.end):
                n = self.nodes.get(end)
                if n is not None and n.type == NodeType.JOINT and self.count(end) == 0:
                    del self.nodes[end]
        self.nodes[plan.a_node].at = parts[0].start
        self.nodes[plan.b_node].at = parts[-1].end
        # One piece per part, the tangent points between them. A part under a hundredth of a mm
        # is nothing to draw (the next starts there); one shorter than a piece goes with the one
        # before, as a segment of it.
        kept = [x for x in parts if curves.length(x) >= 0.01] or parts
        groups: list[list[Seg]] = []
        for seg in kept:
            if groups and (
                curves.length(seg) < MIN_LENGTH or curves.path_length(groups[-1]) < MIN_LENGTH
            ):
                groups[-1].append(seg)
            else:
                groups.append([seg])
        made: list[str] = []
        at = plan.a_node
        for index, group in enumerate(groups):
            if index == len(groups) - 1:
                end = plan.b_node
            else:
                end = self.new_id("n")
                self.nodes[end] = Node(end, NodeType.JOINT, group[-1].end)
            ident = first.id if index == 0 else self.new_id("s")
            self.pieces[ident] = Piece(ident, at, end, group, track, origin)
            made.append(ident)
            at = end
        self.ids.append(IdChange(old=list(plan.chain), new=made, why="lock"))
        for end, number, value, said in (
            (GableEnd.A, plan.track_a, plan.a, plan.a_line),
            (GableEnd.B, plan.track_b, plan.b, plan.b_line),
        ):
            self._set_gable(end, number, value)
            self.locks = [x for x in self.locks if (x.gable, x.track) != (end, number)]
            self.locks.append(
                LockedMeasure(gable=end, track=number, value=value, line=round(said, 1))
            )
        self.source = DrawingSource.DRAWN if self.source == DrawingSource.MEASURES else self.source

    def _check_gable(self, end: GableEnd, track: int, value: float) -> None:
        gable = self.gable(end)
        tracks = list(gable.tracks)
        tracks[track - 1] = value
        if any(b <= a for a, b in itertools.pairwise(tracks)):
            raise EditError(f"Gavel {end.value}: spåren räknas från Kant 1 i ordning.")
        profile = self.known.get(gable.profile) if gable.profile else None
        if profile is not None:
            why = profiles.check(gable.model_copy(update={"tracks": tracks}), profile)
            if why is not None:
                raise EditError(why)

    def _set_gable(self, end: GableEnd, track: int, value: float) -> None:
        index = 0 if end == GableEnd.A else 1
        gable = self.gables[index]
        tracks = list(gable.tracks)
        tracks[track - 1] = round(value, 1)
        self.gables[index] = gable.model_copy(update={"tracks": tracks})

    # --- The measures changed (Ändra måtten) ---------------------------------------------

    def remeasure(self, shape: Shape, gables: Sequence[Gable]) -> None:
        """New measures under a drawn graph: each gable track's node moves to its new place
        and its piece is reshaped; a track gone leaves a free end, a new one a new node."""
        self.shape = shape
        self.gables = list(gables)
        for n in list(self.nodes.values()):
            if n.type != NodeType.MODULE_JOINT or n.gable is None:
                continue
            tracks = self.gable(n.gable).tracks
            if n.track is not None and n.track <= len(tracks):
                to = graph.gable_point(shape, self.gables, n.gable, tracks[n.track - 1])
                for piece in self.on(n.id):
                    self._reshape(piece, n.id, to)
                n.at = to
            elif self.count(n.id):
                n.type, n.gable, n.track = NodeType.JOINT, None, None
            else:
                del self.nodes[n.id]
        for end in (GableEnd.A, GableEnd.B):
            have = {n.track for n in self.nodes.values() if n.gable == end}
            for number, offset in enumerate(self.gable(end).tracks, start=1):
                if number not in have:
                    made = self.new_id("n")
                    at = graph.gable_point(shape, self.gables, end, offset)
                    self.nodes[made] = Node(made, NodeType.MODULE_JOINT, at, end, number)
        self.validate()

    def confirm(self) -> None:
        """Godkänn spårplanen: everything in the graph confirmed by the owner (CAD-17)."""
        for p in self.pieces.values():
            source = p.origin.source if p.origin else GraphSource.DRAWN
            p.origin = GraphOrigin(source=source, certainty=Certainty.CONFIRMED)
        for s in self.switches.values():
            source = s.origin.source if s.origin else GraphSource.DRAWN
            s.origin = GraphOrigin(source=source, certainty=Certainty.CONFIRMED)


def _r(p: Point) -> Point:
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


def _mid(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _first_error(error: ValidationError) -> str:
    found = error.errors()
    if not found:
        return "Ritningen hänger inte ihop."
    message = str(found[0].get("msg", "Ritningen hänger inte ihop."))
    return message.removeprefix("Value error, ")
