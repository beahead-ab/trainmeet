"""Rita i Studio (#85 del a): the station drawn on the grid becomes the station model.

The drawing (contracts.tkl.TklDrawing) is the station model with its panel plan. The owner draws
tracks from cell to cell, horizontally, vertically or at 45°, and puts the other five objects on
them: switches, signals, track-circuit boundaries, buffer stops and line exits (STUDIO-02). The
web app (apps/tkl, Studio, Rita) does the drawing; here it becomes the model, and everything
that is not drawn is computed:

- A node's type follows what stands there: a switch or a crossing, a line exit, a signal.
- The track circuits are the runs of track between the boundaries. A signal stands at a block
  stroke, as the drawing template draws it, so it is a boundary too, and so are the ends. They
  are made only where the drawing has a boundary mark or circuits of its own. A run that is the
  same as a circuit before keeps it, name and all; one that has changed keeps the name of the
  circuit it shares most track with; a new one is named after its track, with the direction
  when the track has more than one (STUDIO-19).
- The signals that lead out onto the line at an exit are the exit's (§6, TKL28).
- The panel shows every signal at its node, every exit at its track's end and every station
  track's name mid-track, where the plan does not already say otherwise.
- The level follows the drawing: 2 with signals, else 1; 3 stays 3. What has no source of its
  own is drawn, and confirmed (RS5).

drawing_of is the other way: a station's model opened for redrawing its panel (STUDIO-30). A
model with a plan of its own is the drawing as it is. One without is drawn on the engine's
layout, the first proposal (STD-09): every node in its cell and every piece a track of its own.
The same model, opened and saved without a change, comes back as it was.

view is what Rita shows besides the drawing: the model, the loose ends (red dots, RS7), the
checks with the object each is about, and the routes the engine derives (STUDIO-16).

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Final

from contracts.station_model import (
    Cell,
    LineExit,
    Node,
    NodeType,
    Origin,
    PanelFunction,
    PanelGrid,
    PanelPiece,
    PanelPlacement,
    PanelPlan,
    PanelTrack,
    PanelTrackName,
    PanelTurntable,
    Source,
    StationModel,
    SwitchType,
    TrackCircuit,
    TrackPiece,
)
from contracts.tkl import (
    Panel,
    PanelAngle,
    RouteKind,
    TklDrawing,
    TklDrawingState,
    TklFinding,
    TklObjectKind,
    TklObjectRef,
    TklRita,
    TklRoute,
)
from tkl.standard import Route, checks, derive, lay_out
from tkl.standard.graph import Graph, Step, parts
from tkl.standard.grid import cell_text
from tkl.standard.layout import CELL_PX
from tkl.standard.routes import TRAIN_ENDS, TRAIN_STARTS

DRAWN: Final = Origin(source=Source.DRAWN, confirmed=True)
GRID: Final = PanelGrid(dx=CELL_PX, dy=CELL_PX)
"""A drawn station's grid: the engine's cell, 24 px (STD-20)."""
BASIS: Final = "Ritad i Studio."
PROPOSAL: Final = "Motorns förslag (STD-09), ritat om i Studio."
ENDS: Final = frozenset(
    {NodeType.BUFFER_STOP, NodeType.LINE_EXIT, NodeType.STOP_POINT, NodeType.TURNTABLE}
)
"""Nodes where a track may end."""
CUTS: Final = frozenset({*ENDS, NodeType.BLOCK_BOUNDARY, NodeType.SIGNAL_POINT})
"""Where one track circuit ends and the next begins."""
POINTS: Final = frozenset({NodeType.BUFFER_STOP, NodeType.STOP_POINT})
"""Named points the engine labels at a track's end."""
READ: Final = "Förslag ur en uppladdad ritning"
"""The note on everything Studio proposed from a drawing read by CAD (tkl/studio/ritning.py):
yellow, assumed, until the owner confirms it (TKL27, RS5)."""


# --- The drawing and the model -------------------------------------------------------------


def empty(station_id: str, name: str) -> TklDrawing:
    """A new station's drawing: the grid and nothing on it."""
    model = StationModel(
        station_id=station_id,
        name=name,
        level=1,
        origin=DRAWN,
        nodes=[],
        pieces=[],
        panel=PanelPlan(basis=BASIS, grid=GRID, nodes={}, tracks=[]),
    )
    return TklDrawing(model=model)


def drawing_of(model: StationModel) -> TklDrawing:
    """The station's model as a drawing, to redraw its panel (STUDIO-30). Raises LayoutError
    when the station has no plan and the engine cannot lay it out."""
    if model.panel is not None:
        return TklDrawing(model=model)
    plan = plan_of(model, lay_out(model))
    return TklDrawing(model=model.model_copy(update={"panel": plan}), proposal=True)


def plan_of(model: StationModel, panel: Panel) -> PanelPlan:
    """The engine's layout as a track plan: every node in its cell, every piece a track of its
    own over the cells where it turns, and the labels where the engine puts them.

    A plan's tracks run at 45° on its grid, so the flat angle, 6 cells sideways per row of 3,
    becomes a grid of cells twice as wide: the panel looks the same (TKL81)."""
    graph = Graph(model)
    wide = 2 if panel.angle == PanelAngle.FLAT else 1

    def cell(c: Cell) -> Cell:
        return (round(c[0] / wide, 4), c[1])

    cells = {n.id: cell(n.cell) for n in panel.nodes}
    tracks: list[PanelTrack] = []
    for line in panel.lines:
        piece = graph.pieces.get(line.piece)
        if piece is None or piece.start not in cells or piece.end not in cells:
            continue
        way = [cell(c) for c in line.cells]
        if way and _same(way[0], cells[piece.start]):
            way = way[1:]
        if way and _same(way[-1], cells[piece.end]):
            way = way[:-1]
        tracks.append(
            PanelTrack(
                start=piece.start,
                end=piece.end,
                pieces=[PanelPiece(id=piece.id)],
                via=way,
                free=line.free,
            )
        )
    signals = _placements(model, graph, {})
    for node in model.nodes:
        touching = graph.touching.get(node.id, [])
        if node.type in POINTS and len(touching) == 1 and node.id not in signals:
            signals[node.id] = _at(graph.pieces[touching[0]], node.id, facing=False)
    table = panel.tables[0] if panel.tables else None
    dx, dy = panel.cell
    return PanelPlan(
        basis=PROPOSAL,
        grid=PanelGrid(dx=dx * wide, dy=dy),
        turntable=PanelTurntable(node=table.node, radius=table.radius * dx) if table else None,
        nodes=cells,
        tracks=tracks,
        signals=signals,
        track_names=_track_names(model, []),
    )


def model_of(drawing: TklDrawing) -> StationModel:
    """The station model the drawing becomes, with everything that is not drawn computed.
    Pure: the same drawing always gives the same model."""
    given = drawing.model
    typed = given.model_copy(update={"nodes": _typed(given, Graph(given))})
    graph = Graph(typed)
    pieces = set(graph.pieces)
    made = typed.model_copy(
        update={
            "level": 3 if given.level == 3 else 2 if given.signals else 1,
            "origin": given.origin or DRAWN,
            "track_circuits": _circuits(typed, graph, given.panel),
            "station_tracks": [
                t.model_copy(update={"pieces": [p for p in t.pieces if p in pieces]})
                for t in given.station_tracks
            ],
            "turntables": [
                t.model_copy(update={"tracks": [r for r in t.tracks if r.piece in pieces]})
                for t in given.turntables
                if t.node in graph.node_type
            ],
        }
    )
    made = made.model_copy(
        update={
            "line_exits": _exits(made, graph),
            "functions": [_function(f, made, graph) for f in made.functions],
        }
    )
    plan = given.panel
    panel = None if drawing.proposal or plan is None else _plan(made, graph, plan)
    return made.model_copy(update={"panel": panel})


def _typed(model: StationModel, graph: Graph) -> list[Node]:
    """Each node's type, from what stands there."""
    switch_at = {s.node: s for s in model.switches}
    exits = {e.node for e in model.line_exits}
    signalled = {s.node for s in model.signals}
    found: list[Node] = []
    for node in model.nodes:
        kind = node.type
        switch = switch_at.get(node.id)
        if switch is not None:
            kind = NodeType.CROSSING if switch.type == SwitchType.CROSSING else NodeType.SWITCH
        elif kind in (NodeType.SWITCH, NodeType.CROSSING):
            kind = NodeType.JOINT
        elif node.id in exits:
            kind = NodeType.LINE_EXIT
        elif (
            kind == NodeType.JOINT
            and node.id in signalled
            and len(graph.touching.get(node.id, [])) == 2
        ):
            kind = NodeType.SIGNAL_POINT
        found.append(node if kind == node.type else node.model_copy(update={"type": kind}))
    return found


def _circuits(model: StationModel, graph: Graph, plan: PanelPlan | None) -> list[TrackCircuit]:
    """The runs of track between the boundaries, the signals and the ends."""
    types = graph.node_type
    if not model.track_circuits and NodeType.BLOCK_BOUNDARY not in types.values():
        return []
    parent = {p: p for p in graph.pieces}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for node, touching in graph.touching.items():
        if types.get(node) in CUTS:
            continue
        for other in touching[1:]:
            parent[find(other)] = find(touching[0])
    grouped: dict[str, list[str]] = defaultdict(list)
    for piece in model.pieces:
        grouped[find(piece.id)].append(piece.id)
    runs = list(grouped.values())
    drawn = list(model.track_circuits)
    taken: dict[int, tuple[int, TrackCircuit]] = {}
    used: set[int] = set()
    exact = {frozenset(c.pieces): i for i, c in reversed(list(enumerate(drawn)))}
    for r, run in enumerate(runs):
        i = exact.get(frozenset(run))
        if i is not None and i not in used:
            taken[r] = (i, drawn[i])
            used.add(i)
    for r, run in enumerate(runs):
        if r in taken:
            continue
        shared = [(len(set(run) & set(c.pieces)), -i) for i, c in enumerate(drawn) if i not in used]
        best = max(shared, default=(0, 0))
        if best[0] > 0:
            i = -best[1]
            taken[r] = (i, drawn[i].model_copy(update={"pieces": run}))
            used.add(i)
    fresh = [r for r in range(len(runs)) if r not in taken]
    names = _circuit_names(
        model, graph, plan, [runs[r] for r in fresh], {c.name for _, c in taken.values()}
    )
    for r, name in zip(fresh, names, strict=True):
        taken[r] = (len(drawn) + r, TrackCircuit(name=name, pieces=runs[r], origin=DRAWN))
    return [circuit for _, circuit in sorted(taken.values(), key=lambda pair: pair[0])]


def _circuit_names(
    model: StationModel,
    graph: Graph,
    plan: PanelPlan | None,
    runs: Sequence[list[str]],
    taken: set[str],
) -> list[str]:
    """A new circuit is named as the drawing template writes a block (STUDIO-19): a switch's
    block Vx and its number, else S and its track's number, or the exit it reaches. Two or
    more on one track get their direction, v (väster) and ö (öster), or a number from the
    west."""
    track_of: dict[str, str] = {p.id: p.track for p in model.pieces if p.track}
    for track in model.station_tracks:
        for piece in track.pieces:
            track_of.setdefault(piece, track.id)
    exits = {e.node: e.id for e in model.line_exits}
    cells = node_cells(model, plan) if plan is not None else {}
    bases: list[str] = []
    wests: list[float] = []
    for run in runs:
        ends = [n for p in run for n in (graph.pieces[p].start, graph.pieces[p].end)]
        counted = Counter(track_of[p] for p in run if p in track_of)
        inside = [s.number for s in model.switches if s.node in ends]
        reached = sorted({exits[n] for n in ends if n in exits})
        if inside:
            base = "Vx" + "/".join(inside)
        elif counted:
            base = "S" + counted.most_common(1)[0][0]
        elif reached:
            base = "S" + reached[0]
        else:
            base = "S" + run[0]
        bases.append(base)
        xs = [cells[n][0] for n in ends if n in cells]
        wests.append(sum(xs) / len(xs) if xs else 0.0)
    names = list(bases)
    for base, count in Counter(bases).items():
        if count < 2:
            continue
        same = sorted((wests[i], i) for i, b in enumerate(bases) if b == base)
        for k, (_, i) in enumerate(same):
            suffix = ("v" if k == 0 else "ö") if count == 2 else str(k + 1)
            names[i] = base + suffix
    found: list[str] = []
    for name in names:
        made, k = name, 2
        while made in taken or made in found:
            made, k = f"{name}.{k}", k + 1
        found.append(made)
    return found


def _exits(model: StationModel, graph: Graph) -> list[LineExit]:
    """Each exit's signals: the ones it had that are still there, and every main signal whose
    train route leads out onto the line there (§6)."""
    signals = {s.name for s in model.signals}
    stations = {t.id for t in model.station_tracks}
    leading = _leading_out(model, graph)
    found: list[LineExit] = []
    for line in model.line_exits:
        kept = [s for s in line.signals if s in signals]
        kept += [s for s in leading.get(line.id, []) if s not in kept]
        tracks = [t for t in line.tracks if t in stations]
        found.append(line.model_copy(update={"signals": kept, "tracks": tracks}))
    return found


def _leading_out(model: StationModel, graph: Graph) -> dict[str, list[str]]:
    """The main signals whose way forward reaches a line exit before a signal in their
    direction or a buffer stop, by exit: what the check for train routes asks for (§6)."""
    if model.level == 1:
        return {}
    exits = {e.node: e.id for e in model.line_exits}
    found: dict[str, list[str]] = defaultdict(list)
    for signal in model.signals:
        if signal.type not in TRAIN_STARTS or signal.planned:
            continue
        if signal.node not in graph.touching or signal.approach not in graph.pieces:
            continue
        stack: list[tuple[Step, frozenset[str]]] = [
            (graph.arriving(signal.approach, signal.node), frozenset())
        ]
        while stack:
            step, seen = stack.pop()
            for move in graph.moves(step):
                if not graph.laid_by_tkl(move.switch) or move.step.piece in seen:
                    continue
                node = graph.end_node(move.step)
                ahead = [
                    s
                    for s in graph.signals_at.get(node, [])
                    if s.approach == move.step.piece and s.type in TRAIN_ENDS
                ]
                if ahead or graph.node_type.get(node) == NodeType.BUFFER_STOP:
                    continue
                if graph.node_type.get(node) == NodeType.LINE_EXIT:
                    exit_id = exits.get(node)
                    if exit_id is not None and signal.name not in found[exit_id]:
                        found[exit_id].append(signal.name)
                    continue
                stack.append((move.step, seen | {move.step.piece}))
    return found


def _function(function: PanelFunction, model: StationModel, graph: Graph) -> PanelFunction:
    """A panel function names only what is still in the drawing."""
    circuits = {c.name for c in model.track_circuits}
    switches = {n for s in model.switches for n in {s.number, *parts(s)}}
    signals = {s.name for s in model.signals}
    levers = {lever.id for lever in model.levers} | switches
    update: dict[str, Any] = {
        "track_circuits": [c for c in function.track_circuits if c in circuits],
        "switches": [s for s in function.switches if s in switches],
        "locked": {s: p for s, p in function.locked.items() if s in levers},
        "signals": [s for s in function.signals if s in signals],
        "pieces": [p for p in function.pieces if p in graph.pieces],
        "at": function.at if function.at in graph.node_type else None,
    }
    if all(getattr(function, key) == value for key, value in update.items()):
        return function
    return function.model_copy(update=update)


def _plan(model: StationModel, graph: Graph, plan: PanelPlan) -> PanelPlan:
    """The plan with only what is still drawn, and the panel's places for what is new."""
    nodes = graph.node_type
    tracks: list[PanelTrack] = []
    for track in plan.tracks:
        kept = [p for p in track.pieces if p.id in graph.pieces]
        if not kept:
            continue
        same = len(kept) == len(track.pieces)
        tracks.append(track if same else track.model_copy(update={"pieces": kept}))
    update: dict[str, Any] = {
        "nodes": {n: c for n, c in plan.nodes.items() if n in nodes},
        "tracks": tracks,
        "signals": _placements(model, graph, plan.signals),
        "track_names": _track_names(model, plan.track_names),
    }
    if plan.turntable is not None and plan.turntable.node not in nodes:
        update["turntable"] = None
    if all(getattr(plan, key) == value for key, value in update.items()):
        return plan
    return plan.model_copy(update=update)


def _placements(
    model: StationModel, graph: Graph, given: Mapping[str, PanelPlacement]
) -> dict[str, PanelPlacement]:
    """Where the panel shows the signals and the named points: as the plan says, and every
    signal and exit it does not name at its node."""
    named = {s.name for s in model.signals} | {e.id for e in model.line_exits}
    named |= set(graph.node_type)
    kept = {n: p for n, p in given.items() if n in named and p.piece in graph.pieces}
    for signal in model.signals:
        piece = graph.pieces.get(signal.approach)
        if signal.name in kept or piece is None or signal.node not in (piece.start, piece.end):
            continue
        kept[signal.name] = _at(piece, signal.node, facing=True)
    for line in model.line_exits:
        touching = graph.touching.get(line.node, [])
        if line.id not in kept and len(touching) == 1:
            kept[line.id] = _at(graph.pieces[touching[0]], line.node, facing=False)
    return kept


def _at(piece: TrackPiece, node: str, *, facing: bool) -> PanelPlacement:
    """At the piece's end at the node; facing: towards the node, as a signal on its approach."""
    at_end = piece.end == node
    return PanelPlacement(piece=piece.id, at=1.0 if at_end else 0.0, reversed=facing and not at_end)


def _track_names(model: StationModel, given: Sequence[PanelTrackName]) -> list[PanelTrackName]:
    """Each station track's name, where the plan puts it, else mid-track."""
    pieces = {p.id for p in model.pieces}
    tracks = {t.id for t in model.station_tracks}
    kept = [t for t in given if t.piece in pieces and t.name in tracks]
    named = {t.name for t in kept}
    for track in model.station_tracks:
        drawn = [p for p in track.pieces if p in pieces]
        if track.id not in named and drawn:
            kept.append(PanelTrackName(name=track.id, piece=drawn[len(drawn) // 2], at=0.5))
    return kept


# --- Where things are on the grid ----------------------------------------------------------


def node_cells(model: StationModel, plan: PanelPlan | None) -> dict[str, Cell]:
    """Every node's cell: its own in the plan, or where it lies along its track, between two
    pieces, as the plan's joints say."""
    if plan is None:
        return {}
    cells: dict[str, Cell] = dict(plan.nodes)
    pieces = {p.id: p for p in model.pieces}
    table = plan.turntable.node if plan.turntable else None
    for track in plan.tracks:
        if track.start not in plan.nodes or track.end not in plan.nodes:
            continue
        way = [plan.nodes[track.start], *track.via, plan.nodes[track.end]]
        free = track.free or table in (track.start, track.end)
        for placed, joint in zip(track.pieces, track.joints, strict=False):
            piece = pieces.get(placed.id)
            if piece is None:
                break
            end = piece.start if placed.reversed else piece.end
            cells.setdefault(end, _along(way, joint, free, plan.grid))
    return cells


def _length(a: Cell, b: Cell, free: bool, grid: PanelGrid) -> float:
    if free:
        return math.hypot((b[0] - a[0]) * grid.dx, (b[1] - a[1]) * grid.dy) / grid.dx
    return max(abs(b[0] - a[0]), abs(b[1] - a[1]))


def _along(way: Sequence[Cell], t: float, free: bool, grid: PanelGrid) -> Cell:
    """The place t cells along the way, counted as a plan counts its joints."""
    gone = 0.0
    for a, b in pairwise(way):
        size = _length(a, b, free, grid)
        if t <= gone + size + 1e-9:
            f = 0.0 if size == 0 else (t - gone) / size
            return (round(a[0] + (b[0] - a[0]) * f, 4), round(a[1] + (b[1] - a[1]) * f, 4))
        gone += size
    return way[-1]


def _same(a: Cell, b: Cell) -> bool:
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


# --- What Rita shows ------------------------------------------------------------------------


def loose_ends(model: StationModel) -> list[str]:
    """The nodes where a track ends without reaching anything: no buffer stop, no exit, no
    stop point and no turntable (RS7). They are drawn as red dots."""
    graph = Graph(model)
    found: list[str] = []
    for node in model.nodes:
        count = len(graph.touching.get(node.id, []))
        if count == 0 or (count == 1 and node.type not in ENDS):
            found.append(node.id)
    return found


TARGETS: Final[tuple[tuple[TklObjectKind, tuple[str, ...]], ...]] = (
    (
        TklObjectKind.PIECE,
        (
            "Spårbiten",
            "spårbiten",
            "Spårbitarna",
            "Spåret",
            "Spåren",
            "benet",
            "glapp mellan",
            "spårbitar heter",
            "omkopplade spåret",
        ),
    ),
    (TklObjectKind.NODE, ("Noden", "noden", "Stoppunkten", "Knuten", "noder heter")),
    (
        TklObjectKind.SWITCH,
        ("Växel", "växel", "Korsningen", "Korsningsväxeln", "korsningen", "växlar har numret"),
    ),
    (TklObjectKind.SIGNAL, ("Signalen", "signalen", "Tågvägen från", "signaler heter")),
    (TklObjectKind.LEVER, ("Spaken", "spaken", "spakar heter")),
    (TklObjectKind.CIRCUIT, ("Spårledningen", "spårledningen", "spårledningar heter")),
    (TklObjectKind.EXIT, ("Linjeutfarten", "linjeutfarten", "linjeutfarter heter")),
)
"""How the checks name what they are about: the words before the name, per kind."""


def target_of(text: str, model: StationModel) -> TklObjectRef | None:
    """The object a check's text is about: the first one it names, to select in the drawing."""
    switch_of = {n: s.number for s in model.switches for n in {s.number, *parts(s)}}
    names: dict[TklObjectKind, list[str]] = {
        TklObjectKind.PIECE: [p.id for p in model.pieces],
        TklObjectKind.NODE: [n.id for n in model.nodes],
        TklObjectKind.SWITCH: list(switch_of),
        TklObjectKind.SIGNAL: [s.name for s in model.signals],
        TklObjectKind.LEVER: [lever.id for lever in model.levers],
        TklObjectKind.CIRCUIT: [c.name for c in model.track_circuits],
        TklObjectKind.EXIT: [e.id for e in model.line_exits],
    }
    best: tuple[int, TklObjectKind, str] | None = None
    for kind, words in TARGETS:
        longest = sorted(set(names[kind]), key=len, reverse=True)
        for word in words:
            at = text.find(word + " ")
            while at >= 0:
                rest = at + len(word) + 1
                name = next((n for n in longest if _named(text, rest, n)), None)
                if name is not None and (best is None or at < best[0]):
                    best = (at, kind, name)
                at = text.find(word + " ", at + 1)
    if best is None:
        return None
    _, kind, name = best
    if kind == TklObjectKind.SWITCH:
        name = switch_of[name]
    return TklObjectRef(kind=kind, id=name)


def _named(text: str, at: int, name: str) -> bool:
    """The text names `name` at `at`, as a whole name."""
    end = at + len(name)
    return text.startswith(name, at) and (end == len(text) or text[end] in " .,:;)–")


def unconfirmed(model: StationModel) -> int:
    """How many of the things proposed from an uploaded drawing the owner has not confirmed:
    a station is never made from a drawing without the owner's yes (TKL27, CAD6)."""
    items: list[Any] = [
        *model.pieces,
        *model.switches,
        *model.signals,
        *model.line_exits,
    ]
    return sum(
        1
        for item in items
        if item.origin is not None and item.origin.note == READ and not item.origin.confirmed
    )


def unconfirmed_problems(model: StationModel) -> list[str]:
    left = unconfirmed(model)
    if not left:
        return []
    return [
        f"{left} {'sak' if left == 1 else 'saker'} ur den uppladdade ritningen är inte "
        "bekräftade. Bekräfta dem en och en, eller alla med Bekräfta förslaget."
    ]


def findings(
    model: StationModel, loose: Sequence[str], plan: PanelPlan | None = None
) -> list[TklFinding]:
    """The checks' problems and notes, each with the object it is about, the loose ends first.
    plan: the drawing's plan, for where the loose ends are."""
    problems, notes = checks(model)
    graph = Graph(model)
    cells = node_cells(model, plan or model.panel)
    found: list[TklFinding] = []
    said: set[str] = set()
    for node in loose:
        count = len(graph.touching.get(node, []))
        said |= {
            f"Noden {node} ska ha två spårbitar men har {count}.",
            f"Noden {node} ska ha en spårbit men har {count}.",
        }
        where = f" i ruta {cell_text(cells[node])}" if node in cells else ""
        found.append(
            TklFinding(
                text=f"Spåret slutar utan att nå något{where}. Rita vidare och koppla ihop det, "
                "eller sätt en stoppbock eller en linjeutfart.",
                problem=True,
                target=TklObjectRef(kind=TklObjectKind.NODE, id=node),
            )
        )
    found += [
        TklFinding(text=t, problem=True, target=target_of(t, model))
        for t in problems
        if t not in said
    ]
    found += [TklFinding(text=t, problem=False, target=target_of(t, model)) for t in notes]
    found += [TklFinding(text=t, problem=True) for t in unconfirmed_problems(model)]
    return found


def view(drawing: TklDrawing, state: TklDrawingState, model: StationModel | None = None) -> TklRita:
    """What Rita shows: the drawing, the model it becomes, the red dots, the checks and the
    routes. The routes are derived while the drawing is being made, so that the owner sees
    them come; a drawing that does not hang together yet may give none."""
    made = model if model is not None else model_of(drawing)
    loose = loose_ends(made)
    try:
        routes = derive(made)
    except (KeyError, ValueError, IndexError):
        routes = []
    counted = Counter(r.kind.value for r in routes)
    return TklRita(
        drawing=drawing,
        state=state,
        model=made,
        loose=loose,
        findings=findings(made, loose, drawing.model.panel),
        routes={kind: counted.get(kind.value, 0) for kind in RouteKind},
        route_list=[_route(r) for r in routes],
    )


def _route(route: Route) -> TklRoute:
    return TklRoute(
        kind=RouteKind(route.kind.value),
        start=route.start.name,
        end=route.end.name,
        pieces=list(route.pieces),
        positions=dict(route.positions),
        turntable=route.turntable,
    )


# --- Keeping the file as it was -------------------------------------------------------------


def ordered_like(model: StationModel, base: StationModel) -> StationModel:
    """The model with its maps' keys in the base's order, new keys last, so that a changed
    model file differs from the one before only where it changed. A browser may reorder a
    map whose keys look like numbers, such as the plan's nodes named after their switches."""
    ordered = _ordered(model.model_dump(mode="json"), base.model_dump(mode="json"))
    return StationModel.model_validate(ordered)


def _ordered(new: Any, old: Any) -> Any:
    if isinstance(new, dict) and isinstance(old, dict):
        keys = [k for k in old if k in new] + [k for k in new if k not in old]
        return {k: _ordered(new[k], old.get(k)) for k in keys}
    if isinstance(new, list) and isinstance(old, list):
        olds = {_key(o): o for o in old if _key(o) is not None}
        return [_ordered(n, olds.get(_key(n)) if _key(n) is not None else None) for n in new]
    return new


def _key(item: Any) -> str | None:
    if isinstance(item, dict):
        for field in ("id", "name", "number", "piece", "start"):
            value = item.get(field)
            if isinstance(value, str):
                return f"{field}:{value}"
    return None


__all__ = [
    "drawing_of",
    "empty",
    "findings",
    "loose_ends",
    "model_of",
    "node_cells",
    "ordered_like",
    "plan_of",
    "target_of",
    "view",
]
