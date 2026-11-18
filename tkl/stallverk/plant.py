"""What the interlocking derives once from a station model (#84), and never stores (STD-07).

Sections. The interlocking locks, releases and moves train numbers per section. A section is a
track circuit (STV-29). A piece that no track circuit holds, as on a station whose model has no
track circuits at all, gets a section of its own, joined with its neighbours through joints and
module joints that mean nothing else: the pieces between two switches, signals, block
boundaries, stop points or ends (spårdelarna mellan växlarna). Such a section is named after
its first piece in the model. Conflicts between routes are still judged per piece by the
engine (tkl.standard.conflicts); here the same pieces are locked and released section by
section, so a station without track circuits locks and releases exactly the pieces its routes
use, with a joint as the only thing that ties two pieces together.

Ways. A way is one of the engine's routes as the interlocking uses it: its sections in order,
where a train stands to take it, and which sections hold each lock. A switch on the route's
own path is held by the sections at its node; a switch the route lays without running over
it, coupled on the same lever or dragged along (TKL104), is held as long as the switch it
protects (STV-20, a Förslag: the simplest safe choice, see protection_holds). A signal the
route guards is held by the sections at its node, the end signal by the last section.

Exits. An exit's box is the line outside the entry signal: the pieces from the line exit in to
the first signal or switch. They belong to the line, never to a route at level 2 (STV-54). A
train on its way here stands there. A route leads out when the walk on from its end reaches a
line exit without passing a switch or a signal in its own direction; past its end is the line
and the clearance (STV-33). A route comes in from an exit when the walk back from its start
signal reaches one the same way.

Functions. The panel functions from the catalogue (STV-04) as the interlocking uses them, made
from the model's own parameters: the area's sections, the signals, the local switches and the
protection switches' positions, the track a function applies to and its modes. A turntable in
the model that no function names gets one of its own, so that its bridge can always be turned.

Addresses (level 3, #85). Every switch part, signal and track circuit has its state from
Koppla in: grey, yellow, green or Utan adress (STUDIO-17, tkl.loconet.objects). With LocoNet
the interlocking runs only green and Utan adress objects (STV-17).

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from threading import Lock
from typing import Final, Literal

from contracts.station_model import (
    Address,
    NodeType,
    PanelFunction,
    PanelFunctionType,
    Position,
    Signal,
    SignalType,
    StationModel,
    SwitchControl,
    SwitchType,
    to_json,
)
from contracts.tkl import AddressState, ObjectKind
from tkl.loconet.objects import states
from tkl.standard import PointKind, Route, RouteKind, alternatives, chains
from tkl.standard.graph import Graph, Step, opposite, parts
from tkl.standard.levers import Levers, own_parts
from tkl.standard.outside import exit_ids, track_ids

PLAIN: Final = frozenset({NodeType.JOINT, NodeType.MODULE_JOINT})
"""Nodes that join two pieces and mean nothing else: a section without a circuit goes on."""
ALONG: Final = frozenset(
    {NodeType.JOINT, NodeType.MODULE_JOINT, NodeType.BLOCK_BOUNDARY, NodeType.SIGNAL_POINT}
)
"""Nodes a walk to the line goes through: two pieces, no switch, no end."""
MOST_STEPS: Final = 200
MOST_CHAIN_PARTS: Final = 6
CACHED: Final = 8

Spot = tuple[Literal["section", "exit"], str]
"""Where a train is: a section, or the line outside an exit."""


def fingerprint(model: StationModel) -> str:
    """The model's fingerprint: a saved state belongs to exactly this model."""
    return hashlib.sha256(to_json(model).encode("utf-8")).hexdigest()


MINUS_SIGN: Final = "\N{MINUS SIGN}"


def sign(position: Position) -> str:
    """A position as the panel writes it: a plus, or a minus sign."""
    return "+" if position == Position.PLUS else MINUS_SIGN


@dataclass(frozen=True)
class Section:
    name: str
    pieces: tuple[str, ...]
    circuit: bool
    detector: str
    """Two track circuits on the same detector are one for locking (conflicts.detectors)."""

    @property
    def said(self) -> str:
        return f"spårledningen {self.name}" if self.circuit else f"spårdelen {self.name}"


@dataclass(frozen=True)
class ExitPlace:
    id: str
    outside: str
    node: str
    pieces: tuple[str, ...]
    """The line outside the entry signal, from the exit inwards (STV-54)."""


@dataclass(frozen=True)
class Way:
    """One of the engine's routes as the interlocking sets, locks and releases it."""

    route: Route
    sections: tuple[tuple[str, tuple[str, ...]], ...]
    starts: frozenset[Spot]
    holds: Mapping[str, frozenset[int]]
    """Every switch the route lays -> the sections that hold its lock."""
    crossing_holds: Mapping[str, frozenset[int]]
    guard_holds: Mapping[str, frozenset[int]]
    passed_at: Mapping[str, int]
    """A signal the route passes -> the section the train has passed it in."""
    protection: frozenset[str]
    turntable: tuple[str, str] | None
    """The turntable and the track its bridge must point at."""
    turntable_hold: frozenset[int]
    leaves: str | None
    enters: str | None

    @property
    def kind(self) -> RouteKind:
        return self.route.kind

    @property
    def start(self) -> str:
        return self.route.start.name

    @property
    def end(self) -> str:
        return self.route.end.name

    @property
    def name(self) -> str:
        return self.route.name

    @property
    def last(self) -> int:
        return len(self.sections) - 1

    @property
    def pieces(self) -> tuple[str, ...]:
        return self.route.pieces


Chain = tuple[Way, ...]

DWARFS: Final = frozenset({SignalType.DVSI, SignalType.HDVSI})
"""Signals with a dwarf part: they show shunting in a locally released area (FR41)."""
MAINS: Final = frozenset({SignalType.HSI, SignalType.HDVSI})
TRACTION_MODES: Final = ("2R", "3R")
"""The catalogue's example modes, when a traction current function names none."""


@dataclass(frozen=True)
class Function:
    """A panel function as the interlocking uses it (STV-04): the model's parameters, resolved
    against the plant. Names the model has but the plant does not know are left out."""

    name: str
    type: PanelFunctionType
    sections: frozenset[str]
    """The area: the sections of its track circuits and pieces."""
    pieces: tuple[str, ...]
    """What the panel colours: the area's pieces, or the track the function applies to."""
    signals: tuple[str, ...]
    """Signal stop: the signals held at stop. Local release: those that show shunting."""
    blocked: tuple[str, ...]
    """Local release: the entry signals to the area, blocked at stop while it is on (FR41)."""
    switches: tuple[str, ...]
    """Local release: the local switch parts, laid with the modules' buttons (TKL44)."""
    locked: Mapping[str, Position]
    """Local release: the protection levers and the side they are locked in."""
    locked_parts: Mapping[str, Position]
    """The switch parts those levers lay, with their positions."""
    modes: tuple[tuple[str, str], ...]
    """Traction current: its modes. Turntable: its tracks, as (piece, label)."""
    turntable: str | None
    at: str | None
    codes: Mapping[str, str]
    note: str | None

    def touches(self, way: Way) -> bool:
        """A route touches a local release's area: it runs over it, starts or ends at one of
        its signals, or lays one of its local switches (TKL44, FR41)."""
        return (
            any(name in self.sections for name, _ in way.sections)
            or way.start in self.signals
            or way.end in self.signals
            or any(part in self.switches for part in way.route.positions)
        )


class Plant:
    """The station model's sections, ways, levers and exits, made once per model."""

    def __init__(self, model: StationModel) -> None:
        self.model = model
        self.fingerprint = fingerprint(model)
        self.graph = Graph(model)
        self.levers = Levers(model)
        self.signals: dict[str, Signal] = {s.name: s for s in model.signals}
        self.switch_by_number = {s.number: s for s in model.switches}
        self.control: dict[str, SwitchControl] = {
            part: s.control for s in model.switches for part in parts(s)
        }
        self.part_node: dict[str, str] = {part: s.node for s in model.switches for part in parts(s)}
        self.crossing_node: dict[str, str] = {
            s.number: s.node for s in model.switches if s.type in _CROSSINGS
        }
        self.sections: dict[str, Section] = {}
        self.section_of: dict[str, str] = {}
        self._make_sections()
        self.track_of: dict[str, str] = {}
        for track in model.station_tracks:
            for piece in track.pieces:
                if piece in self.section_of:
                    self.track_of.setdefault(self.section_of[piece], track.id)
        self.track_outside = track_ids(model)
        outside = exit_ids(model)
        self.exits: dict[str, ExitPlace] = {}
        self.exit_at: dict[str, str] = {}
        for line in model.line_exits:
            if line.id in self.exits or line.node not in self.graph.node_type:
                continue
            self.exits[line.id] = ExitPlace(
                line.id, outside[line.id], line.node, tuple(self._line_pieces(line.node))
            )
            self.exit_at[line.node] = line.id
        self.paths: dict[tuple[RouteKind, str, str], list[Route]] = alternatives(model)
        self.all_paths = [r for found in self.paths.values() for r in found]
        self._ways: dict[tuple[RouteKind, str, str, tuple[Step, ...]], Way] = {}
        for route in self.all_paths:
            self._ways[(route.kind, route.start.name, route.end.name, route.steps)] = self._way(
                route
            )
        self.points: set[str] = {name for (_, a, b) in self.paths for name in (a, b)}
        self._chains: dict[tuple[RouteKind, str, str], list[Chain]] = {}
        self._ends: dict[tuple[RouteKind, str], list[str]] = {}
        self._lock = Lock()
        self.functions: dict[str, Function] = {}
        self._make_functions()
        self.states: dict[tuple[ObjectKind, str], AddressState] = states(model)
        """Every object's state in Koppla in (STUDIO-17), for level 3."""

    # --- sections ---------------------------------------------------------------------------

    def _make_sections(self) -> None:
        graph = self.graph
        for circuit in self.model.track_circuits:
            own = tuple(p for p in circuit.pieces if p in graph.pieces)
            detector = (
                f"{circuit.detection.bus}:{circuit.detection.number}"
                if isinstance(circuit.detection, Address)
                else circuit.name
            )
            if circuit.name in self.sections:
                continue
            self.sections[circuit.name] = Section(circuit.name, own, True, detector)
            for piece in own:
                self.section_of.setdefault(piece, circuit.name)
        rest = [p.id for p in self.model.pieces if p.id not in self.section_of]
        free = set(rest)
        group = {p: p for p in rest}

        def root(piece: str) -> str:
            while group[piece] != piece:
                group[piece] = group[group[piece]]
                piece = group[piece]
            return piece

        for node, kind in graph.node_type.items():
            touching = graph.touching.get(node, [])
            if kind not in PLAIN or graph.signals_at.get(node) or len(touching) != 2:
                continue
            a, b = touching
            if a in free and b in free:
                group[root(a)] = root(b)
        members: dict[str, list[str]] = {}
        for piece in rest:
            members.setdefault(root(piece), []).append(piece)
        for found in members.values():
            name = found[0]
            while name in self.sections:
                name += "*"
            self.sections[name] = Section(name, tuple(found), False, name)
            for piece in found:
                self.section_of[piece] = name

    def said(self, section: str) -> str:
        found = self.sections.get(section)
        return found.said if found else f"spårledningen {section}"

    def exit_of_section(self, section: str) -> str | None:
        """The exit whose line a section lies on, when all its pieces are the line's."""
        pieces = set(self.sections[section].pieces)
        for place in self.exits.values():
            if pieces and pieces <= set(place.pieces):
                return place.id
        return None

    def touching(self, node: str) -> set[str]:
        """The sections of the pieces that meet at a node."""
        return {self.section_of[p] for p in self.graph.touching.get(node, [])}

    # --- walks to the line ------------------------------------------------------------------

    def _line_pieces(self, node: str) -> list[str]:
        graph = self.graph
        touching = graph.touching.get(node, [])
        if len(touching) != 1:
            return []
        step = graph.leaving(touching[0], node)
        found: list[str] = []
        for _ in range(MOST_STEPS):
            found.append(step.piece)
            here = graph.end_node(step)
            if self._stops_walk(here) or graph.signals_at.get(here):
                break
            others = [p for p in graph.touching.get(here, []) if p != step.piece]
            if len(others) != 1:
                break
            step = graph.leaving(others[0], here)
        return found

    def _stops_walk(self, node: str) -> bool:
        return self.graph.node_type.get(node) not in ALONG or node in self.graph.switch_at

    def _to_line(self, step: Step, *, ahead: bool) -> str | None:
        """The exit a walk reaches without a switch or a signal for the trains it is about.

        ahead: the walk goes the way the train goes, so a signal in its direction stops it.
        Otherwise it goes back from a start signal, and a signal for trains coming in stops it.
        """
        graph = self.graph
        for _ in range(MOST_STEPS):
            here = graph.end_node(step)
            if here in self.exit_at:
                return self.exit_at[here]
            if self._stops_walk(here):
                return None
            for signal in graph.signals_at.get(here, []):
                if (signal.approach == step.piece) == ahead:
                    return None
            others = [p for p in graph.touching.get(here, []) if p != step.piece]
            if len(others) != 1:
                return None
            step = graph.leaving(others[0], here)
        return None

    def _leaves(self, route: Route) -> str | None:
        if route.end.kind == PointKind.LINE_EXIT:
            return self.exit_at.get(route.end.node)
        if route.end.kind != PointKind.SIGNAL or not route.steps:
            return None
        last = route.steps[-1]
        node = self.graph.end_node(last)
        others = [p for p in self.graph.touching.get(node, []) if p != last.piece]
        if len(others) != 1 or node in self.graph.switch_at:
            return None
        return self._to_line(self.graph.leaving(others[0], node), ahead=True)

    def _starts(self, route: Route) -> frozenset[Spot]:
        graph = self.graph
        start = route.start
        spots: set[Spot] = set()
        if start.kind == PointKind.SIGNAL:
            signal = self.signals[start.name]
            if signal.approach in graph.pieces:
                spots.add(("section", self.section_of[signal.approach]))
                found = self._to_line(graph.leaving(signal.approach, signal.node), ahead=False)
                if found is not None:
                    spots.add(("exit", found))
        elif start.kind == PointKind.LINE_EXIT:
            if start.node in self.exit_at:
                spots.add(("exit", self.exit_at[start.node]))
        else:
            spots |= {("section", s) for s in self.touching(start.node)}
        return frozenset(spots)

    # --- ways -------------------------------------------------------------------------------

    def _way(self, route: Route) -> Way:
        graph = self.graph
        found: list[tuple[str, list[str]]] = []
        for step in route.steps:
            name = self.section_of[step.piece]
            if found and found[-1][0] == name:
                found[-1][1].append(step.piece)
            else:
                found.append((name, [step.piece]))
        sections = tuple((name, tuple(pieces)) for name, pieces in found)
        every = frozenset(range(len(sections)))

        def at(node: str) -> frozenset[int]:
            touched = frozenset(
                i
                for i, (_, pieces) in enumerate(sections)
                for p in pieces
                if node in (graph.pieces[p].start, graph.pieces[p].end)
            )
            return touched or every

        holds: dict[str, frozenset[int]] = {
            part: at(self.part_node[part]) for part in route.switches if part in self.part_node
        }
        owners: dict[str, set[str]] = {}
        for part, position in route.switches.items():
            laid = self.levers.lay({part: position})
            for other in laid.positions if laid is not None else {part: position}:
                owners.setdefault(other, set()).add(part)
        for part in route.positions:
            if part not in holds:
                holds[part] = protection_holds(part, owners, holds, every)
        crossing_holds = {
            c: at(self.crossing_node[c]) for c in route.crossings if c in self.crossing_node
        }
        guard_holds = {
            g: at(self.signals[g].node) if g in self.signals else every for g in route.guards
        }
        passed_at: dict[str, int] = {}
        section_of_step = [i for i, (_, pieces) in enumerate(sections) for _ in pieces]
        for name in route.passed:
            signal = self.signals.get(name)
            if signal is None:
                continue
            for i in range(1, len(route.steps)):
                if graph.end_node(route.steps[i - 1]) == signal.node:
                    passed_at[name] = section_of_step[i]
                    break
        turntable = None
        turntable_hold: frozenset[int] = frozenset()
        if route.turntable is not None:
            for table in self.model.turntables:
                if any(t.piece == route.turntable for t in table.tracks):
                    turntable = (table.id, route.turntable)
                    turntable_hold = at(table.node)
                    break
        starts = self._starts(route)
        enters = next((name for kind, name in sorted(starts) if kind == "exit"), None)
        return Way(
            route=route,
            sections=sections,
            starts=starts,
            holds=holds,
            crossing_holds=crossing_holds,
            guard_holds=guard_holds,
            passed_at=passed_at,
            protection=frozenset(route.positions) - frozenset(route.switches),
            turntable=turntable,
            turntable_hold=turntable_hold,
            leaves=self._leaves(route),
            enters=enters,
        )

    def ways(self) -> list[Way]:
        """Every way, the preferred path first for each kind, start and end."""
        return [self._ways[(r.kind, r.start.name, r.end.name, r.steps)] for r in self.all_paths]

    def preferred(self) -> list[Way]:
        """The engine's route for each kind, start and end (tkl.standard.derive)."""
        return [
            self._ways[(r.kind, r.start.name, r.end.name, r.steps)]
            for r in (found[0] for found in self.paths.values())
        ]

    def find_way(self, kind: RouteKind, start: str, end: str, pieces: Iterable[str]) -> Way | None:
        """The way with exactly these pieces, or None: a saved route must still exist."""
        wanted = tuple(pieces)
        for route in self.paths.get((kind, start, end), []):
            if route.pieces == wanted:
                return self._ways[(route.kind, route.start.name, route.end.name, route.steps)]
        return None

    def kinds(self, start: str) -> list[RouteKind]:
        """The kinds of route from a start, a train route first (STV-24)."""
        return [k for k in (RouteKind.TRAIN, RouteKind.SHUNTING) if self._from(k, start)]

    def _from(self, kind: RouteKind, start: str) -> list[str]:
        return sorted({b for (k, a, b) in self.paths if k == kind and a == start})

    def candidates(self, kind: RouteKind, start: str, end: str) -> list[Chain]:
        """The ways from start to end, the preferred first: the direct route's paths where
        there is one, else the chains through the signals between (TKL53)."""
        key = (kind, start, end)
        with self._lock:
            known = self._chains.get(key)
        if known is not None:
            return known
        direct = self.paths.get(key)
        made: list[Chain]
        if direct:
            made = [(self._ways[(r.kind, r.start.name, r.end.name, r.steps)],) for r in direct]
        else:
            made = [
                tuple(self._ways[(r.kind, r.start.name, r.end.name, r.steps)] for r in chain)
                for chain in chains(self.all_paths, kind, start, end, most=MOST_CHAIN_PARTS)
                if len(chain) > 1
            ]
        with self._lock:
            self._chains[key] = made
        return made

    def ends(self, kind: RouteKind, start: str) -> list[str]:
        """The goals from a start: the direct ones and those a chain reaches."""
        key = (kind, start)
        with self._lock:
            known = self._ends.get(key)
        if known is not None:
            return known
        direct = self._from(kind, start)
        goals = sorted({b for (k, _, b) in self.paths if k == kind} - {start} - set(direct))
        made = direct + [g for g in goals if direct and self.candidates(kind, start, g)]
        with self._lock:
            self._ends[key] = made
        return made

    # --- panel functions (STV-04) ------------------------------------------------------------

    def _make_functions(self) -> None:
        given = list(self.model.functions)
        named = {f.at for f in given if f.type == PanelFunctionType.TURNTABLE and f.at}
        for table in self.model.turntables:
            if table.id not in named and table.node not in named:
                own = table.id.lower().startswith("vändskiva")
                name = table.id if own else f"Vändskivan {table.id}"
                turntable = PanelFunction(type=PanelFunctionType.TURNTABLE, name=name, at=table.id)
                given.append(turntable)
        for spec in given:
            name = spec.name
            count = 2
            while name in self.functions:
                name = f"{spec.name} {count}"
                count += 1
            self.functions[name] = self._function(name, spec)

    def _function(self, name: str, spec: PanelFunction) -> Function:
        sections = {c for c in spec.track_circuits if c in self.sections}
        sections |= {self.section_of[p] for p in spec.pieces if p in self.section_of}
        area = frozenset(sections)
        if spec.type in (PanelFunctionType.TRACTION_CURRENT, PanelFunctionType.PROGRAMMING_TRACK):
            own = [p for p in spec.pieces if p in self.graph.pieces]
            pieces = tuple(own) or tuple(p for s in sorted(area) for p in self.sections[s].pieces)
        else:
            pieces = tuple(p for s in sorted(area) for p in self.sections[s].pieces)
        switches: list[str] = []
        for number in spec.switches:
            switch = self.switch_by_number.get(number)
            for part in parts(switch) if switch is not None else [number]:
                if part in self.control and part not in switches:
                    switches.append(part)
        locked: dict[str, Position] = {}
        locked_parts: dict[str, Position] = {}
        for key, position in spec.locked.items():
            lever_id, _ = self.lever_of(key)
            if lever_id is None:
                continue
            lever = self.levers.levers[lever_id]
            laid = self.levers.lay(dict(lever.plus if position == Position.PLUS else lever.minus))
            if laid is None:
                continue
            locked[lever_id] = position
            for part, side in laid.positions.items():
                if self.control.get(part) == SwitchControl.TKL:
                    locked_parts[part] = side
        signals = [s for s in spec.signals if s in self.signals]
        if spec.type == PanelFunctionType.SIGNAL_STOP:
            signals += [
                s.name
                for s in self.model.signals
                if s.name not in signals and self.section_of.get(s.approach) in area
            ]
        modes: tuple[tuple[str, str], ...] = ()
        turntable = None
        if spec.type == PanelFunctionType.TRACTION_CURRENT:
            modes = tuple((m, m) for m in (spec.modes or TRACTION_MODES))
        if spec.type == PanelFunctionType.TURNTABLE:
            for table in self.model.turntables:
                if spec.at in (table.id, table.node):
                    turntable = table.id
                    modes = tuple(
                        (t.piece, self._towards(t.piece, table.node)) for t in table.tracks
                    )
        made = Function(
            name=name,
            type=spec.type,
            sections=area,
            pieces=pieces,
            signals=tuple(signals),
            blocked=(),
            switches=tuple(switches),
            locked=locked,
            locked_parts=locked_parts,
            modes=modes,
            turntable=turntable,
            at=spec.at,
            codes=dict(spec.codes),
            note=spec.note,
        )
        if spec.type != PanelFunctionType.LOCAL_RELEASE:
            return made
        # The entry signals: main signals outside the area whose routes go into it (FR41).
        blocked = sorted(
            {
                way.start
                for way in self.preferred()
                if way.start in self.signals
                and way.start not in made.signals
                and self.signals[way.start].type in MAINS
                and made.touches(way)
            }
        )
        return replace(made, blocked=tuple(blocked))

    def _towards(self, piece: str, node: str) -> str:
        """A turntable track as the panel names it: its track number, else where it leads."""
        found = self.graph.pieces.get(piece)
        if found is None:
            return piece
        if found.track:
            return f"Spår {found.track}"
        far = found.end if found.start == node else found.start
        if self.graph.node_type.get(far) == NodeType.CROSSING:
            return f"Korsning {far}"
        return f"Växel {far}" if far in self.graph.switch_at else far

    # --- levers -----------------------------------------------------------------------------

    def initial_positions(self) -> dict[str, Position]:
        """Every lever in its + position, the dragged switches with it, in the model's order."""
        positions: dict[str, Position] = {}
        for lever in self.levers.levers.values():
            for part in own_parts(lever):
                positions.setdefault(part, lever.plus[part])
        for lever in self.model.levers:
            laid = self.levers.lay(dict(lever.plus))
            if laid is not None:
                positions.update(laid.positions)
        return {p: v for p, v in positions.items() if self.control.get(p) == SwitchControl.TKL}

    def lever_side(self, lever_id: str, positions: Mapping[str, Position]) -> Position | None:
        lever = self.levers.levers[lever_id]
        own = own_parts(lever)
        for side, wanted in ((Position.PLUS, lever.plus), (Position.MINUS, lever.minus)):
            if own and all(positions.get(p) == wanted[p] for p in own):
                return side
        return None

    def lever_of(self, name: str) -> tuple[str | None, str | None]:
        """The lever a click on a switch lays (STV-01), or why there is none."""
        control = self.control.get(name)
        if control is not None and control != SwitchControl.TKL:
            return None, not_laid(name, control)
        if name in self.levers.own:
            return self.levers.own[name], None
        if name in self.levers.levers:
            return name, None
        switch = self.switch_by_number.get(name)
        if switch is not None:
            if switch.control != SwitchControl.TKL:
                return None, not_laid(name, switch.control)
            found = sorted({self.levers.own[p] for p in parts(switch) if p in self.levers.own})
            if len(found) == 1:
                return found[0], None
            if found:
                return None, (
                    f"Växel {name} har flera spakar: {', '.join(found)}. Klicka på en av delarna."
                )
            return None, f"Växel {name} läggs inte från ställverket."
        return None, f"Växel {name} finns inte i stationsmodellen."

    def alignment(self, turntable: str, piece: str) -> frozenset[str]:
        """The tracks a bridge pointing at `piece` joins: the piece and those opposite it."""
        for table in self.model.turntables:
            if table.id == turntable:
                angles = {t.piece: t.angle for t in table.tracks}
                mine = angles.get(piece)
                if mine is None:
                    return frozenset({piece})
                return frozenset(
                    {piece} | {p for p, a in angles.items() if p != piece and opposite(mine, a)}
                )
        return frozenset({piece})


_CROSSINGS: Final = frozenset({SwitchType.SINGLE_SLIP, SwitchType.DOUBLE_SLIP, SwitchType.CROSSING})


def protection_holds(
    part: str,
    owners: Mapping[str, set[str]],
    holds: Mapping[str, frozenset[int]],
    every: frozenset[int],
) -> frozenset[int]:
    """Where a switch the route locks without running over it is held (STV-20, a Förslag).

    The seam for flank protection: today such a switch, coupled on the same lever or dragged
    along, is held as long as the route's own switches that lay it, and with none of them
    known, until the whole route is released. When Benny's answer comes (trainmeet #62), the
    flank protection rule goes here.
    """
    found = frozenset(i for owner in owners.get(part, ()) for i in holds.get(owner, ()))
    return found or every


def not_laid(part: str, control: SwitchControl) -> str:
    """Why the interlocking does not lay a switch."""
    if control == SwitchControl.PLANNED:
        return f"Växel {part} är planerad och finns inte än."
    if control == SwitchControl.MANUAL:
        return f"Växel {part} läggs för hand. Ställverket lägger den aldrig."
    return f"Växel {part} läggs inte från ställverket."


_PLANTS: dict[str, Plant] = {}
_PLANTS_LOCK = Lock()


def plant_of(model: StationModel) -> Plant:
    """The plant of a model, made once and kept for the last few models."""
    key = fingerprint(model)
    with _PLANTS_LOCK:
        found = _PLANTS.get(key)
    if found is not None:
        return found
    made = Plant(model)
    with _PLANTS_LOCK:
        if len(_PLANTS) >= CACHED:
            _PLANTS.pop(next(iter(_PLANTS)))
        _PLANTS[key] = made
    return made
