"""Train routes and shunting routes, derived from the model and never stored (§2, STD-07).

Level 2 and 3, signal to signal (TKL28):
- A train route runs from a main or combined signal, in its direction, to the next main or
  combined signal in the same direction, to a stop lamp, or to a buffer stop. Dwarf signals in
  the same direction are passed, as tagvag_forbi says for two of them on one reference page,
  and so are all signals facing the other way and the stop points.
- A shunting route runs from a dwarf or combined signal to the next signal of any kind in the
  same direction, or to a buffer stop. It may go towards an occupied track.
- Where a station has no signals, a stop point and the turntable start and end shunting routes
  too: the next signal, stop point, buffer stop or the turntable ends them. A train route that
  reaches the turntable is not a route; the bridge is turned between two shunting routes.
- A stop lamp only ends routes, never starts one (RS3).

Level 1, without signals: routes go track to track, from every stop point, buffer stop, line
exit and the turntable to every other one the walk reaches without reversing, over the
stop points and over the turntable when the bridge joins two opposite tracks.

No route passes a switch that TKL does not lay. A route that needs a lever in both positions,
counting coupled switches and those that are dragged along, is rejected. Where several paths
join the same start and end, the one with fewest diverging switches is taken (TKL53), then the
one that leaves the most other routes possible, then the shortest.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from contracts.station_model import NodeType, Position, Signal, SignalType, StationModel
from tkl.standard.conflicts import conflict, detectors
from tkl.standard.flank import flank
from tkl.standard.graph import Graph, Move, Step
from tkl.standard.levers import Levers
from tkl.standard.route import PointKind, Route, RouteKind, RoutePoint

TRAIN_STARTS = frozenset({SignalType.HSI, SignalType.HDVSI})
SHUNTING_STARTS = frozenset({SignalType.HDVSI, SignalType.DVSI})
TRAIN_ENDS = frozenset({SignalType.HSI, SignalType.HDVSI, SignalType.STOP_LAMP})
SHUNTING_ENDS = frozenset({SignalType.HSI, SignalType.HDVSI, SignalType.DVSI, SignalType.STOP_LAMP})
ENDS_AT_LEVEL_1 = frozenset(
    {NodeType.STOP_POINT, NodeType.BUFFER_STOP, NodeType.LINE_EXIT, NodeType.TURNTABLE}
)


def kinds_from(signal: Signal) -> list[RouteKind]:
    """The kinds of route a signal starts. A planned signal starts none."""
    if signal.planned:
        return []
    found = []
    if signal.type in TRAIN_STARTS:
        found.append(RouteKind.TRAIN)
    if signal.type in SHUNTING_STARTS:
        found.append(RouteKind.SHUNTING)
    return found


def ends(kind: RouteKind) -> frozenset[SignalType]:
    return TRAIN_ENDS if kind == RouteKind.TRAIN else SHUNTING_ENDS


@dataclass
class _Walk:
    """A walk under way: the steps so far and what they need."""

    kind: RouteKind
    start: RoutePoint
    steps: list[Step]
    switches: dict[str, Position]
    passed: list[str] = field(default_factory=list)
    guards: list[str] = field(default_factory=list)
    crossings: list[str] = field(default_factory=list)
    turntable: str | None = None


class Engine:
    """Derives the routes of one model."""

    def __init__(self, model: StationModel) -> None:
        self.model = model
        self.graph = Graph(model)
        self.levers = Levers(model)

    # --- the walks --------------------------------------------------------------------

    def candidates(self) -> Iterator[Route]:
        """Every path that makes a route, before one path is chosen per start and end."""
        if self.model.level == 1:
            yield from self._level_1()
        else:
            yield from self._signal_routes()

    def _signal_routes(self) -> Iterator[Route]:
        graph = self.graph
        for signal in self.model.signals:
            if signal.approach not in graph.pieces:
                continue
            arriving = graph.arriving(signal.approach, signal.node)
            point = RoutePoint(PointKind.SIGNAL, signal.name, signal.node)
            for kind in kinds_from(signal):
                for move in graph.moves(arriving):
                    yield from self._walk(_Walk(kind, point, [], {}), move)
        # Where there are no signals: stop points and the turntable start shunting routes.
        for node, node_type in graph.node_type.items():
            if node_type == NodeType.STOP_POINT:
                point = RoutePoint(PointKind.STOP_POINT, node, node)
            elif node_type == NodeType.TURNTABLE and node in graph.turntable_at:
                point = RoutePoint(PointKind.TURNTABLE, graph.turntable_at[node].id, node)
            else:
                continue
            for piece in graph.touching.get(node, []):
                walk = _Walk(RouteKind.SHUNTING, point, [], {})
                if node_type == NodeType.TURNTABLE:
                    walk.turntable = piece
                yield from self._walk(walk, Move(graph.leaving(piece, node), node))

    def _extend(self, walk: _Walk, move: Move) -> _Walk | None:
        """The walk one step further, or None where it may not go: a switch TKL does not lay,
        a switch already needed the other way, or a piece it has already taken."""
        if not self.graph.laid_by_tkl(move.switch):
            return None
        switches = dict(walk.switches)
        for part, position in move.positions.items():
            if switches.setdefault(part, position) != position:
                return None
        if any(step.piece == move.step.piece for step in walk.steps):
            return None
        crossings = list(walk.crossings)
        if move.switch is not None and move.switch.paths:
            crossings.append(move.switch.number)
        return replace(
            walk,
            steps=[*walk.steps, move.step],
            switches=switches,
            passed=list(walk.passed),
            guards=list(walk.guards),
            crossings=crossings,
        )

    def _walk(self, walk: _Walk, move: Move) -> Iterator[Route]:
        graph = self.graph
        here = self._extend(walk, move)
        if here is None:
            return
        step = move.step
        node = graph.end_node(step)
        end: RoutePoint | None = None
        for signal in graph.signals_at.get(node, []):
            if signal.approach != step.piece:
                here.guards.append(signal.name)
            elif signal.type in ends(here.kind):
                end = RoutePoint(PointKind.SIGNAL, signal.name, node)
            else:
                here.passed.append(signal.name)
        node_type = graph.node_type.get(node)
        if end is None:
            if node_type == NodeType.BUFFER_STOP:
                end = RoutePoint(PointKind.BUFFER_STOP, node, node)
            elif node_type == NodeType.LINE_EXIT:
                return
            elif node_type == NodeType.TURNTABLE:
                if here.kind == RouteKind.TRAIN or node not in graph.turntable_at:
                    return
                end = RoutePoint(PointKind.TURNTABLE, graph.turntable_at[node].id, node)
                here.turntable = here.turntable or step.piece
            elif node_type == NodeType.STOP_POINT and here.kind == RouteKind.SHUNTING:
                end = RoutePoint(PointKind.STOP_POINT, node, node)
        if end is not None:
            route = self._route(here, end)
            if route is not None:
                yield route
            return
        for after in graph.moves(step):
            yield from self._walk(here, after)

    def _level_1(self) -> Iterator[Route]:
        graph = self.graph
        for node, node_type in graph.node_type.items():
            if node_type not in ENDS_AT_LEVEL_1:
                continue
            point = self._point(node)
            for piece in graph.touching.get(node, []):
                walk = _Walk(RouteKind.TRAIN, point, [], {})
                if node_type == NodeType.TURNTABLE:
                    walk.turntable = piece
                yield from self._walk_1(walk, Move(graph.leaving(piece, node), node))

    def _point(self, node: str) -> RoutePoint:
        graph = self.graph
        node_type = graph.node_type[node]
        if node_type == NodeType.TURNTABLE and node in graph.turntable_at:
            return RoutePoint(PointKind.TURNTABLE, graph.turntable_at[node].id, node)
        kind = {
            NodeType.STOP_POINT: PointKind.STOP_POINT,
            NodeType.BUFFER_STOP: PointKind.BUFFER_STOP,
            NodeType.LINE_EXIT: PointKind.LINE_EXIT,
        }[node_type]
        exits = {e.node: e.id for e in self.model.line_exits}
        return RoutePoint(kind, exits.get(node, node), node)

    def _walk_1(self, walk: _Walk, move: Move) -> Iterator[Route]:
        graph = self.graph
        here = self._extend(walk, move)
        if here is None:
            return
        step = move.step
        node = graph.end_node(step)
        node_type = graph.node_type.get(node)
        if node_type == NodeType.TURNTABLE:
            here.turntable = here.turntable or step.piece
        if node_type in ENDS_AT_LEVEL_1 and node != walk.start.node:
            route = self._route(here, self._point(node))
            if route is not None:
                yield route
        if node_type == NodeType.TURNTABLE:
            onward = [Move(s, node) for s in graph.across_turntable(step)]
        elif node_type in (NodeType.BUFFER_STOP, NodeType.LINE_EXIT):
            onward = []
        else:
            onward = graph.moves(step)
        for after in onward:
            yield from self._walk_1(here, after)

    def _route(self, walk: _Walk, end: RoutePoint) -> Route | None:
        laid = self.levers.lay(walk.switches)
        if laid is None:
            return None
        graph = self.graph
        protection = flank(graph, self.levers, walk.steps, walk.switches)
        flanked: dict[str, str] = {}
        if protection:
            wanted = {**walk.switches, **{p: v for p, (v, _) in protection.items()}}
            with_flank = self.levers.lay(wanted)
            if with_flank is None:  # pragma: no cover - flank() only takes what can be laid
                return None
            for part, (position, node) in sorted(protection.items()):
                alone = self.levers.lay({part: position})
                for other in alone.positions if alone is not None else {part: position}:
                    if other not in laid.positions:
                        flanked.setdefault(other, node)
            laid = with_flank
        circuits: list[str] = []
        for step in walk.steps:
            circuit = graph.circuit_of.get(step.piece)
            if circuit is not None and (not circuits or circuits[-1] != circuit):
                circuits.append(circuit)
        guards = list(walk.guards)
        if end.kind == PointKind.SIGNAL and end.name not in guards:
            guards.append(end.name)
        return Route(
            kind=walk.kind,
            start=walk.start,
            end=end,
            steps=tuple(walk.steps),
            switches=dict(walk.switches),
            positions=laid.positions,
            levers=laid.levers,
            track_circuits=tuple(circuits),
            passed=tuple(walk.passed),
            guards=tuple(dict.fromkeys(guards)),
            crossings=tuple(walk.crossings),
            turntable=walk.turntable,
            length=round(sum(graph.length(s) for s in walk.steps), 1),
            diverging=sum(1 for p in walk.switches.values() if p == Position.MINUS),
            flank=flanked,
        )


def preference(route: Route) -> tuple[int, float, tuple[Step, ...]]:
    """Fewest diverging switches (TKL53), then the shortest, then always the same."""
    return (route.diverging, route.length, route.steps)


def alternatives(model: StationModel) -> dict[tuple[RouteKind, str, str], list[Route]]:
    """Every path for every start and end, the preferred first.

    Fewest diverging switches first (TKL53). Among those, the path that leaves the most other
    movements possible, as the old interlocking chose (selectRoutePaths in cda-tkl), then the
    shortest. The order never depends on the order of the model's lists.
    """
    found: dict[tuple[RouteKind, str, str], list[Route]] = {}
    for route in Engine(model).candidates():
        found.setdefault(route.key, []).append(route)
    ordered = {key: sorted(paths, key=preference) for key, paths in sorted(found.items())}
    detector = detectors(model)

    def blocked(key: tuple[RouteKind, str, str], route: Route) -> int:
        return sum(
            1
            for other, paths in ordered.items()
            if other != key and all(conflict(route, p, detector) for p in paths)
        )

    for key, paths in ordered.items():
        fewest = paths[0].diverging
        tied = [p for p in paths if p.diverging == fewest]
        if len(tied) > 1:
            rest = paths[len(tied) :]
            tied.sort(key=lambda p: (blocked(key, p), preference(p)))
            ordered[key] = [*tied, *rest]
    return ordered


def derive(model: StationModel) -> list[Route]:
    """The station's routes: one per kind, start and end, in a fixed order."""
    return [paths[0] for paths in alternatives(model).values()]
