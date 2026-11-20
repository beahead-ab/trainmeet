"""Från CAD i Studio (#89 del d2, STUDIO-01, STUDIO-03, CAD-10, CAD-15, CAD-20): a group of modules
from TrainMeet CAD, an assembly or a single module, becomes a proposal for the station model, and
a re-import shows the difference.

CAD sends the track graph only, in mm, with ids it never changes (contracts.cad.StudioGraph).
Studio knows the rules (the border between CAD and Studio, TKL10):

- A piece is the model's piece with the same id and its real shape (Foto draws it, STV-06); an
  arc becomes points every SAMPLE_MM. Its origin keeps CAD's id as ref, so that Rita's splits
  keep it on both parts.
- A track that ends at a free gable is a line exit, named Väst 1, Öst 1 … from the top; one that
  ends inside a module is a buffer stop, named Stoppbock 1 … from the west, as Rita names them.
  Signals, boundaries and routes are Studio's to add and work out (CAD-09).
- A switch is the model's switch with its legs, and its number if it is free; a crossing gets
  its two ways through. A track's number in CAD makes a station track.
- Everything carries the origin assumed, not confirmed, with the note FROM_CAD: yellow in Rita
  until the owner confirms it, and Använd ritningen is refused until then. CAD never makes a
  station (TKL8, CAD-15).

A re-import is the same proposal laid over what the station has, by CAD's ids (CAD-20): a piece
whose id is kept and whose shape is the same keeps the owner's splits, signals, boundaries and
confirmation; one that moved gets the new shape, split where the owner had split it, and is
yellow again; a new one is added; one that is gone goes, and what hung on it is listed as lost.
Switch numbers, exit names, station tracks, levers and the owner's own tracks stay where what
they name is still there. The owner's panel plan stays when nothing was added or removed;
otherwise the engine lays the panel out again (TKL81).

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Final

from contracts.cad import ArcSegment, GraphPiece, StudioGraph, StudioSourceKind
from contracts.station_model import (
    Lever,
    LineExit,
    Node,
    NodeType,
    Origin,
    Point,
    Signal,
    Source,
    StationModel,
    StationTrack,
    Switch,
    SwitchPath,
    SwitchType,
    TrackPiece,
)
from contracts.tkl import TklCadDiff, TklCadPiece
from tkl.studio.rita import FROM_CAD

SAMPLE_MM: Final = 20.0
"""An arc becomes points this many mm apart: Foto rolls trains on them."""
SAME_WITHIN: Final = 1.0
"""A piece whose ends, middle and length move less than this many mm is the same shape."""
ENDS: Final = frozenset(
    {NodeType.BUFFER_STOP, NodeType.LINE_EXIT, NodeType.STOP_POINT, NodeType.TURNTABLE}
)
MARKS: Final = frozenset({NodeType.SIGNAL_POINT, NodeType.BLOCK_BOUNDARY, NodeType.STOP_POINT})
KINDS: Final = {StudioSourceKind.ASSEMBLY: "Anläggningen", StudioSourceKind.MODULE: "Modulen"}


def from_cad(origin: Origin | None) -> bool:
    return origin is not None and origin.note == FROM_CAD and origin.ref is not None


def _origin(ref: str | None) -> Origin:
    return Origin(source=Source.ASSUMED, confirmed=False, ref=ref, note=FROM_CAD)


def _round(p: Point) -> Point:
    return (round(p[0], 1), round(p[1], 1))


def _points(piece: GraphPiece) -> list[Point]:
    """The piece's shape as points: its lines' ends, and its arcs every SAMPLE_MM."""
    found: list[Point] = [_round(piece.segments[0].start)]
    for segment in piece.segments:
        if isinstance(segment, ArcSegment):
            cx, cy = segment.center
            a0 = math.atan2(segment.start[1] - cy, segment.start[0] - cx)
            a1 = math.atan2(segment.end[1] - cy, segment.end[0] - cx)
            sweep = a1 - a0
            # With y down, clockwise on the screen is a growing angle.
            if segment.clockwise and sweep < 0:
                sweep += 2 * math.pi
            if not segment.clockwise and sweep > 0:
                sweep -= 2 * math.pi
            steps = max(2, math.ceil(abs(sweep) * segment.radius / SAMPLE_MM))
            for k in range(1, steps):
                t = a0 + sweep * k / steps
                found.append(
                    _round((cx + segment.radius * math.cos(t), cy + segment.radius * math.sin(t)))
                )
        found.append(_round(segment.end))
    return found


def _length(points: Sequence[Point]) -> float:
    return sum(math.dist(a, b) for a, b in itertools.pairwise(points))


def _at(points: Sequence[Point], distance: float) -> Point:
    walked = 0.0
    for a, b in itertools.pairwise(points):
        step = math.dist(a, b)
        if walked + step >= distance and step > 0:
            t = (distance - walked) / step
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        walked += step
    return points[-1]


def _split(points: Sequence[Point], fractions: Sequence[float]) -> list[list[Point]]:
    """The shape cut at the given shares of its length, in order."""
    total = _length(points)
    cuts = [total * f for f in fractions]
    parts: list[list[Point]] = []
    current: list[Point] = [points[0]]
    walked = 0.0
    for a, b in itertools.pairwise(points):
        step = math.dist(a, b)
        while cuts and cuts[0] <= walked + step:
            t = (cuts.pop(0) - walked) / step if step else 0.0
            q = _round((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            current.append(q)
            parts.append(current)
            current = [q]
        current.append(b)
        walked += step
    parts.append(current)
    while len(parts) < len(fractions) + 1:
        parts.append([points[-1], points[-1]])
    return parts


def _ways(node: str, pieces: Sequence[TrackPiece]) -> list[SwitchPath]:
    """A crossing's two ways through: each piece with the one most nearly opposite it."""
    legs: list[tuple[str, Point]] = []
    for p in pieces:
        if len(p.geometry) < 2 or node not in (p.start, p.end):
            continue
        at, far = (
            (p.geometry[0], p.geometry[1]) if p.start == node else (p.geometry[-1], p.geometry[-2])
        )
        dx, dy = far[0] - at[0], far[1] - at[1]
        n = math.hypot(dx, dy) or 1.0
        legs.append((p.id, (dx / n, dy / n)))
    ways: list[SwitchPath] = []
    while len(legs) >= 2:
        first = legs.pop(0)
        other = min(legs, key=lambda x: first[1][0] * x[1][0] + first[1][1] * x[1][1])
        legs.remove(other)
        ways.append(SwitchPath(between=(first[0], other[0])))
    return ways


def _free(taken: Iterable[str], pattern: Callable[[int], str]) -> Iterator[str]:
    used = set(taken)
    for k in itertools.count(1):
        name = pattern(k)
        if name not in used:
            used.add(name)
            yield name


def _exit_name(at: Point, centre: float, taken: Iterable[str]) -> str:
    side = "Väst" if at[0] < centre else "Öst"
    return next(_free(taken, lambda k: f"{side} {k}"))


def proposal(studio: StudioGraph, station_id: str, name: str) -> StationModel:
    """The station model Studio proposes from CAD's track graph, everything assumed."""
    graph = studio.graph
    source = studio.source
    ends = Counter(e for p in graph.pieces for e in (p.start, p.end))
    at = {n.id: n.at for n in graph.nodes}
    kinds: dict[str, NodeType] = {}
    for n in graph.nodes:
        if not ends[n.id]:
            continue
        if ends[n.id] == 1 and n.type in (NodeType.MODULE_JOINT, NodeType.JOINT):
            kinds[n.id] = (
                NodeType.LINE_EXIT if n.type == NodeType.MODULE_JOINT else NodeType.BUFFER_STOP
            )
        elif n.type in (NodeType.SWITCH, NodeType.CROSSING, NodeType.BUFFER_STOP):
            kinds[n.id] = n.type
        elif n.type == NodeType.MODULE_JOINT:
            kinds[n.id] = NodeType.MODULE_JOINT
        else:
            kinds[n.id] = NodeType.JOINT
    # A buffer stop is named as Rita names one: Stoppbock 1 … from the west.
    stops = sorted((n for n, k in kinds.items() if k == NodeType.BUFFER_STOP), key=lambda n: at[n])
    rename = {old: f"Stoppbock {k + 1}" for k, old in enumerate(stops)}

    def node(ident: str) -> str:
        return rename.get(ident, ident)

    nodes = [Node(id=node(n), type=k) for n, k in kinds.items()]
    pieces = [
        TrackPiece(
            id=p.id,
            start=node(p.start),
            end=node(p.end),
            track=p.track,
            geometry=_points(p),
            origin=_origin(p.id),
        )
        for p in graph.pieces
    ]
    switches: list[Switch] = []
    taken = {s.number for s in graph.switches if s.number}
    numbers = _free(taken, str)
    given: set[str] = set()
    for s in graph.switches:
        number = s.number if s.number and s.number not in given else next(numbers)
        given.add(number)
        switches.append(
            Switch(
                number=number,
                type=SwitchType.Y if s.type == SwitchType.Y else SwitchType.ORDINARY,
                node=node(s.node),
                trunk=s.trunk,
                straight=s.straight,
                diverging=s.diverging,
                design=_design(s.radius, s.angle),
                origin=_origin(s.id),
            )
        )
    with_switch = {s.node for s in graph.switches}
    for ident, kind in kinds.items():
        if kind == NodeType.CROSSING and ident not in with_switch:
            switches.append(
                Switch(
                    number=next(numbers),
                    type=SwitchType.CROSSING,
                    node=ident,
                    paths=_ways(ident, pieces),
                    origin=_origin(ident),
                )
            )
    exits: list[LineExit] = []
    xs = [p[0] for p in at.values()] or [0.0]
    centre = (min(xs) + max(xs)) / 2
    outer = sorted(
        (i for i, k in kinds.items() if k == NodeType.LINE_EXIT),
        key=lambda i: (at[i][0] >= centre, at[i][1]),
    )
    for end in outer:
        name_ = _exit_name(at[end], centre, (e.id for e in exits))
        exits.append(LineExit(id=name_, node=end, origin=_origin(end)))
    tracks: dict[str, list[str]] = defaultdict(list)
    for p in pieces:
        if p.track:
            tracks[p.track].append(p.id)
    return StationModel(
        station_id=station_id,
        name=name,
        level=1,
        origin=_origin(None),
        basis=[
            f"{KINDS[source.kind]} {source.name} i TrainMeet CAD, version {source.revision}: "
            "ett förslag att bekräfta."
        ],
        nodes=nodes,
        pieces=pieces,
        switches=switches,
        station_tracks=[
            StationTrack(id=t, label=f"Spår {t}", pieces=ids) for t, ids in tracks.items()
        ],
        line_exits=exits,
    )


def _design(radius: float | None, angle: float | None) -> str | None:
    if radius is None:
        return None
    text = f"R {radius:.0f}"
    if angle is not None:
        text += f" · {angle:.1f}°".replace(".", ",")
    return text


# --- The re-import (STUDIO-03, CAD-20) -----------------------------------------------------


def modules_of(studio: StudioGraph) -> dict[str, str]:
    """The source's modules by id, as the owner sees them: "M-002 Linje"."""
    return {str(m.id): f"{m.number} {m.name}" for m in studio.source.modules}


def describer(
    studio: StudioGraph, earlier: Mapping[str, str] | None = None
) -> Callable[[TrackPiece], TklCadPiece]:
    """How the owner sees a piece of CAD's: its module, and its track or its own id. earlier:
    the modules of the import before, for a piece whose module is no longer in the source."""
    modules = {**(earlier or {}), **modules_of(studio)}

    def describe(piece: TrackPiece) -> TklCadPiece:
        ref = piece.origin.ref if piece.origin and piece.origin.ref else piece.id
        module, _, own = ref.partition(":")
        where = modules.get(module, "En modul som inte är med längre")
        what = f"spår {piece.track}" if piece.track else f"spårbit {own or ref}"
        return TklCadPiece(id=ref, text=f"{where} · {what}")

    return describe


def _chain(parts: Sequence[TrackPiece], ref: str) -> list[TrackPiece] | None:
    """The owner's parts of one CAD piece in order from its start, or None when they do not
    hang together as Rita's splits leave them."""
    first = next((p for p in parts if p.id == ref), None)
    if first is None:
        ends = {p.end for p in parts}
        starts = [p for p in parts if p.start not in ends]
        if len(starts) != 1:
            return None
        first = starts[0]
    chain = [first]
    left = [p for p in parts if p is not first]
    while left:
        after = next((p for p in left if p.start == chain[-1].end), None)
        if after is None:
            return None
        chain.append(after)
        left.remove(after)
    return chain


def _joined(chain: Sequence[TrackPiece]) -> list[Point]:
    found: list[Point] = []
    for part in chain:
        found += part.geometry if not found else part.geometry[1:]
    return found


def _same(old: Sequence[Point], new: Sequence[Point]) -> bool:
    if len(old) < 2 or len(new) < 2:
        return len(old) == len(new)
    lo, ln = _length(old), _length(new)
    return (
        math.dist(old[0], new[0]) <= SAME_WITHIN
        and math.dist(old[-1], new[-1]) <= SAME_WITHIN
        and abs(lo - ln) <= SAME_WITHIN
        and math.dist(_at(old, lo / 2), _at(new, ln / 2)) <= SAME_WITHIN
    )


def _reshaped(chain: Sequence[TrackPiece], new: TrackPiece) -> list[TrackPiece]:
    """The owner's parts with the new shape, cut where they were cut; yellow again."""
    lengths = [_length(p.geometry) for p in chain]
    total = sum(lengths)
    cuts = (
        [sum(lengths[: k + 1]) / total for k in range(len(chain) - 1)]
        if total > 0
        else [(k + 1) / len(chain) for k in range(len(chain) - 1)]
    )
    shapes = _split(new.geometry, cuts) if len(new.geometry) >= 2 else [[] for _ in chain]
    made: list[TrackPiece] = []
    for k, (part, shape) in enumerate(zip(chain, shapes, strict=True)):
        origin = (part.origin or _origin(new.id)).model_copy(update={"confirmed": False})
        made.append(
            part.model_copy(
                update={
                    "start": new.start if k == 0 else part.start,
                    "end": new.end if k == len(chain) - 1 else part.end,
                    "geometry": shape,
                    "origin": origin,
                }
            )
        )
    return made


def reimport(
    old: StationModel | None,
    fresh: StationModel,
    studio: StudioGraph,
    earlier: Mapping[str, str] | None = None,
) -> tuple[StationModel, TklCadDiff]:
    """The proposal laid over what the station has, by CAD's ids, and the difference. earlier:
    the modules of the import before, to name what is gone."""
    describe = describer(studio, earlier)
    cad_old = [p for p in old.pieces if from_cad(p.origin)] if old is not None else []
    if old is None or not cad_old:
        return fresh, TklCadDiff(
            first=True,
            added=[describe(p) for p in fresh.pieces],
            replaced=old is not None and bool(old.pieces),
        )
    parts: dict[str, list[TrackPiece]] = defaultdict(list)
    for p in cad_old:
        assert p.origin is not None and p.origin.ref is not None
        parts[p.origin.ref].append(p)
    chains = {ref: _chain(found, ref) for ref, found in parts.items()}
    old_types = {n.id: n.type for n in old.nodes}
    fresh_types = {n.id: n.type for n in fresh.nodes}
    # A buffer stop keeps the name the station gave it; a new one gets the next free name.
    rename: dict[str, str] = {}
    for new in fresh.pieces:
        chain = chains.get(new.origin.ref if new.origin and new.origin.ref else "")
        if not chain:
            continue
        for mine, theirs in ((new.start, chain[0].start), (new.end, chain[-1].end)):
            if fresh_types.get(mine) == NodeType.BUFFER_STOP and old_types.get(theirs) in ENDS:
                rename[mine] = theirs
    stops = _free(set(old_types) | set(rename.values()), lambda k: f"Stoppbock {k}")
    for n, kind in fresh_types.items():
        if kind == NodeType.BUFFER_STOP and n not in rename:
            rename[n] = next(stops)

    def node(ident: str) -> str:
        return rename.get(ident, ident)

    added: list[TklCadPiece] = []
    moved: list[TklCadPiece] = []
    pieces: list[TrackPiece] = []
    confirmed = 0
    for new in fresh.pieces:
        new = new.model_copy(update={"start": node(new.start), "end": node(new.end)})
        ref = new.origin.ref if new.origin and new.origin.ref else new.id
        chain = chains.get(ref)
        if ref not in parts:
            added.append(describe(new))
            pieces.append(new)
        elif chain is None:
            moved.append(describe(new))
            pieces.append(new)
        elif (
            chain[0].start == new.start
            and chain[-1].end == new.end
            and _same(_joined(chain), new.geometry)
        ):
            pieces += chain
            confirmed += sum(1 for p in chain if p.origin and p.origin.confirmed)
        else:
            moved.append(describe(new))
            pieces += _reshaped(chain, new)
    fresh_refs = {p.origin.ref for p in fresh.pieces if p.origin}
    removed = [describe(found[0]) for ref, found in parts.items() if ref not in fresh_refs]
    lost: list[str] = []
    # The owner's own tracks, drawn in Studio, stay where their ends still are.
    known = {node(n.id) for n in fresh.nodes} | {e for p in pieces for e in (p.start, p.end)}
    for p in old.pieces:
        if from_cad(p.origin):
            continue
        if p.start in known and p.end in known:
            pieces.append(p)
        else:
            lost.append(f"Spåret {p.id}, som du ritade i Studio")
    piece_ids = {p.id for p in pieces}
    used = {e for p in pieces for e in (p.start, p.end)}
    nodes: list[Node] = []
    placed: set[str] = set()
    for candidate in [*(Node(id=node(x.id), type=x.type) for x in fresh.nodes), *old.nodes]:
        if candidate.id not in used or candidate.id in placed:
            continue
        placed.add(candidate.id)
        was = old_types.get(candidate.id)
        kind = candidate.type
        if was is not None and (
            (kind in ENDS and was in ENDS)
            or (kind in (NodeType.JOINT, NodeType.MODULE_JOINT) and was in MARKS)
        ):
            kind = was
        nodes.append(Node(id=candidate.id, type=kind))
    node_ids = {n.id for n in nodes}
    kinds = {n.id: n.type for n in nodes}

    def leg(piece: str | None, at: str) -> str | None:
        """The part of a CAD piece that reaches the node, after the owner's splits."""
        if piece is None:
            return None
        if piece in piece_ids:
            touching = [p for p in pieces if p.id == piece and at in (p.start, p.end)]
            if touching:
                return piece
        found = next(
            (p.id for p in pieces if p.origin and p.origin.ref == piece and at in (p.start, p.end)),
            None,
        )
        return found if found is not None else piece

    old_switches: dict[str, Switch] = {
        s.origin.ref: s
        for s in old.switches
        if s.origin is not None and s.origin.ref and from_cad(s.origin)
    }
    switches: list[Switch] = []
    numbers_kept = 0
    for s in fresh.switches:
        s = s.model_copy(update={"node": node(s.node)})
        legs = {
            "trunk": leg(s.trunk, s.node),
            "straight": leg(s.straight, s.node),
            "diverging": leg(s.diverging, s.node),
            "paths": [
                path.model_copy(
                    update={"between": (leg(path.between[0], s.node), leg(path.between[1], s.node))}
                )
                for path in s.paths
            ],
        }
        had = old_switches.get(s.origin.ref if s.origin and s.origin.ref else "")
        if had is None:
            switches.append(s.model_copy(update=legs))
            continue
        same = (
            had.node == s.node
            and had.trunk == legs["trunk"]
            and had.straight == legs["straight"]
            and had.diverging == legs["diverging"]
        )
        origin = had.origin if same else s.origin
        if (had.number, had.address, had.control, had.feedback) != (
            s.number,
            s.address,
            s.control,
            s.feedback,
        ):
            numbers_kept += 1
        switches.append(had.model_copy(update={**legs, "node": s.node, "origin": origin}))
    for s in old.switches:
        if from_cad(s.origin):
            continue
        if s.node in node_ids:
            switches.append(s)
        else:
            lost.append(f"Växel {s.number}")
    # Numbers stay unique: the station's own first, new ones get the next free.
    taken_numbers = [s.number for s in switches]
    duplicate = {n for n, c in Counter(taken_numbers).items() if c > 1}
    free = _free(taken_numbers, str)
    seen: set[str] = set()
    for k, s in enumerate(switches):
        if s.number in duplicate and s.number in seen:
            switches[k] = s.model_copy(update={"number": next(free)})
        seen.add(switches[k].number)
    switch_numbers = {s.number for s in switches}
    signals: list[Signal] = []
    for signal in old.signals:
        if signal.node in node_ids and signal.approach in piece_ids:
            signals.append(signal)
        else:
            lost.append(f"Signal {signal.name}")
    levers: list[Lever] = []
    for lever in old.levers:
        if set(lever.plus) | set(lever.minus) <= switch_numbers:
            levers.append(lever)
        else:
            lost.append(f"Spak {lever.id}")
    station_tracks: list[StationTrack] = []
    for track in old.station_tracks:
        still = [p for p in track.pieces if p in piece_ids]
        if still:
            station_tracks.append(track.model_copy(update={"pieces": still}))
        else:
            lost.append(f"Stationsspår {track.label}")
    for track in fresh.station_tracks:
        same_track = next((t for t in station_tracks if t.id == track.id), None)
        if same_track is None:
            station_tracks.append(track)
            continue
        extra = [p for p in track.pieces if p not in same_track.pieces and p in piece_ids]
        if extra:
            station_tracks[station_tracks.index(same_track)] = same_track.model_copy(
                update={"pieces": [*same_track.pieces, *extra]}
            )

    def ends_at(found: Sequence[TrackPiece]) -> dict[str, Point]:
        return {
            e: (piece.geometry[0] if piece.start == e else piece.geometry[-1])
            for piece in found
            for e in (piece.start, piece.end)
            if piece.geometry
        }

    def middle(found: Sequence[TrackPiece]) -> float:
        xs = [p[0] for piece in found for p in piece.geometry] or [0.0]
        return (min(xs) + max(xs)) / 2

    exits: list[LineExit] = []
    gone: list[tuple[bool, Point, LineExit]] = []
    """An exit whose track now runs on: its side, its place and itself, to move outward."""
    old_at, old_centre = ends_at(old.pieces), middle(old.pieces)
    for exit_ in old.line_exits:
        if kinds.get(exit_.node) == NodeType.LINE_EXIT:
            exits.append(exit_)
        else:
            place = old_at.get(exit_.node, (0.0, 0.0))
            gone.append((place[0] < old_centre, place, exit_))
    centre, where = middle(pieces), ends_at(pieces)
    covered = {e.node for e in exits}
    for exit_ in fresh.line_exits:
        if exit_.node in covered or kinds.get(exit_.node) != NodeType.LINE_EXIT:
            continue
        place = where.get(exit_.node, (0.0, 0.0))
        same_side = [g for g in gone if g[0] == (place[0] < centre)]
        if same_side:
            # The track runs on to a new end on the same side: the exit moves out with its name.
            nearest = min(same_side, key=lambda g: abs(g[1][1] - place[1]))
            gone.remove(nearest)
            exits.append(
                nearest[2].model_copy(
                    update={"node": exit_.node, "origin": exit_.origin, "tracks": []}
                )
            )
            continue
        name = _exit_name(place, centre, (e.id for e in exits))
        exits.append(exit_.model_copy(update={"id": name}))
    lost += [f"Linjeutfarten {g[2].id}" for g in gone]
    circuits = [
        c.model_copy(update={"pieces": [p for p in c.pieces if p in piece_ids]})
        for c in old.track_circuits
        if any(p in piece_ids for p in c.pieces)
    ]
    functions = [
        f.model_copy(update={"pieces": [p for p in f.pieces if p in piece_ids]})
        for f in old.functions
    ]
    turntables = [t for t in old.turntables if t.node in node_ids]
    changed = bool(added or removed)
    parts_kept = old.parts if not removed and not lost else []
    if old.parts and not parts_kept:
        lost += [f"Delställverket {p.name}" for p in old.parts]
    panel = old.panel if not changed and not lost else None
    model = old.model_copy(
        update={
            "basis": fresh.basis,
            "nodes": nodes,
            "pieces": pieces,
            "switches": switches,
            "levers": levers,
            "signals": signals,
            "track_circuits": circuits,
            "station_tracks": station_tracks,
            "line_exits": exits,
            "turntables": turntables,
            "functions": functions,
            "parts": parts_kept,
            "panel": panel,
        }
    )
    kept: list[str] = []
    """The owner's own additions that stay: what CAD sends again is not counted."""
    marks = sum(1 for n in nodes if n.type in MARKS and n.id not in fresh_types)
    fresh_exits = {e.node: e for e in fresh.line_exits}
    own_exits = [
        e
        for e in exits
        if e.node in {x.node for x in old.line_exits}
        and (e.neighbour or (e.node in fresh_exits and fresh_exits[e.node].id != e.id))
    ]
    fresh_tracks = {t.id: t.label for t in fresh.station_tracks}
    own_tracks = [t for t in station_tracks if fresh_tracks.get(t.id) != t.label]
    for count, one, many in (
        (len(signals), "en signal", "signaler"),
        (marks, "ett blockstreck", "blockstreck"),
        (numbers_kept, "en växel med ditt nummer", "växlar med dina nummer"),
        (len(own_exits), "en linjeutfart med ditt namn", "linjeutfarter med dina namn"),
        (len(own_tracks), "ett stationsspår", "stationsspår"),
        (confirmed, "en bekräftad spårbit", "bekräftade spårbitar"),
    ):
        if count:
            kept.append(one if count == 1 else f"{count} {many}")
    if panel is not None:
        kept.append("panelens spårplan")
    return StationModel.model_validate(model.model_dump(mode="json")), TklCadDiff(
        first=False,
        added=added,
        removed=removed,
        moved=moved,
        kept=kept,
        lost=lost,
        panel=panel is not None,
    )
