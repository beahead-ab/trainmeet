"""Ställverket at level 1–2 (#84): the interlocking's state machine over one station model.

It holds the state of the moment (STV-08): the switch positions and so the levers, the set
routes with their locks, the signal aspects that follow from them, the turntable's bridge and
the train numbers. It never holds the model, the clearance or the timetable (STV-09).

Every operation answers yes, or no with the reason in Swedish, and changes nothing on a no.
These functions are the one place where safety is checked: the panel, Stream Deck and a remote
request all call them (STV-43, STV-44). An unknown id is a no, never a guess.

- set_route: a train route or a shunting route from a start to a goal (STV-01, STV-14), the
  whole chain through the signals between when the goal is further away (STV-03, TKL53). Of the
  ways the engine offers, the first that can be set now is taken: the direct route's paths with
  the fewest diverging switches first, else the chains in the same order. All of it or nothing.
  Without a kind it is a train route where there is one (STV-24).
- release and emergency_release: lösa ut, and nödutlösa with a confirmation, logged (STV-01).
- lay_lever: a click on a switch lays its whole lever, the coupled switches and those it drags
  along with it (STV-52, TKL104). Refused when one that must move is locked or under a train.
- step (Kör): the train number moves one section along the route, and the section behind it is
  released (STV-06, STV-29). Past the end it takes the next set route, or leaves on the line.
- arrive (Ankommit): the train stands at the route's end; the route is released and the arrival
  goes up to Hubben (STV-16). depart (Avgått): the train has left on a route out.
- put_train and remove_train: a train number on a section or on the line at an exit.
- reset: every route released, confirmed and logged; the switches stay where they are.
- function: the panel functions from the catalogue (STV-04), each by its name in the model:
  - signal stop (signalstopp): the area's signals show stop, blocked, and no route is set from
    them. A route already set there keeps its locks but is held at stop (`held`) until it is
    set again after the stop is off: a signal never clears by itself (ported from cda-tkl's
    line barrier and all-stop, which never resumed a route).
  - local release (lokal frigivning, TKL44, STD-14, FR41): the protection levers are laid and
    locked, the local switches are laid with the modules' buttons (`lay`) and never by the
    interlocking, the area's dwarf signals show shunting, its entry signals are blocked, and
    no route touches the area. It is refused while a route touches the area. Taking it back
    is always allowed, as in the prototype: the local switches stay where they lie.
  - traction current (körström): the track's mode, 2R or 3R; it touches no route.
  - out of service (spår ur drift): no route over the track; a route already there is held.
  - emergency release (nödutlösning) of the function's track circuits, confirmed and logged:
    every lock in them is released, whatever route holds it.
  - turntable (vändskiva): the bridge turned to a track, refused while a route holds it
    pointing elsewhere.
  - programming track (programmeringsspår, STV-53, TKL106): the track switched over and back.
    The interlocking blocks no route.

Without detection the train number follows the buttons (STV-15): occupancy is where a train
number is, and it never frees anything by itself (STV-16). Only step, arrive, depart and the
releases do.

Two Förslag wait for Benny's answer (trainmeet #62) and have a seam each: the signals a route
passes (STV-19, `passed_showing`) and where the green number stands (STV-21, `green_numbers`).
Flank protection (STV-20) has its seam in plant.protection_holds.

Level 3 with LocoNet (#85, STV-11, STV-15–STV-17). The service (tkl.loconet.service) connects
the field with `field_connect`, passes the layout's reports to `field_reports` and the time to
`field_tick`, and sends what `take_orders` gives. Then:

- setting a route orders its switches and waits for their feedback: the signal shows stop
  until every switch has reported its position, and without feedback within six seconds the
  route is held with the reason (cda-tkl's commandTimeoutMs). A switch that reports another
  position under a set route holds it too. Setting it again orders the switches again;
- the signals' aspects are ordered as they change, and all stop when LocoNet connects;
- sensor reports set the track circuits' occupancy, and the train number follows it (STV-15):
  the front moves into the next section of its route, and a section behind it is released when
  its circuit becomes free (sectional release, after the train);
- arrival is the entry route released after passage (STV-16): the train is in the route's last
  section, every section behind it is released and the one it came from is free. A train route
  then reports the arrival with its track. A route out to the line is departed when the train
  has left its last section. Occupancy never frees anything by itself: a free circuit releases
  only behind a train that has moved on, and a train number stays where it is;
- only green and Utan adress objects run (STV-17): a route over a grey or a yellow one, or a
  lever that would lay one, is refused with the reason. Against the pretend LocoNet the yellow
  ones run too (Prova). The panel's state shows each object's state;
- a section on the line outside an exit reports its occupancy up as section.occupancy (STV-10);
- Kör, Ankommit and Avgått are refused: the track circuits do that.

Without LocoNet the interlocking is as at level 1–2, with the buttons ("LocoNet ej ansluten"
without the pretend LocoNet, or in the cloud).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from contracts.station import ExitSignalAspect
from contracts.station_model import PanelFunctionType, Position, SwitchControl
from contracts.tkl import (
    AddressState,
    ObjectKind,
    TklAspect,
    TklExitShown,
    TklField,
    TklFieldMode,
    TklFunctionAction,
    TklFunctionMode,
    TklFunctionShown,
    TklHappening,
    TklInterlocking,
    TklNumber,
    TklNumberColour,
    TklPieceShown,
    TklPieceState,
    TklReport,
    TklReportKind,
    TklSectionPart,
    TklSetRoute,
    TklSignalShown,
    TklSwitchShown,
    TklTarget,
    TklTargets,
    TklTrain,
)
from contracts.tkl import RouteKind as ShownKind
from tkl.loconet.objects import (
    RUNNING,
    STATE_WORD,
    FieldReport,
    SectionReported,
    SignalReported,
    SwitchReported,
)
from tkl.stallverk.plant import (
    DWARFS,
    MINUS_SIGN,
    Chain,
    Function,
    Plant,
    Spot,
    Way,
    not_laid,
    sign,
)
from tkl.standard import PointKind, RouteKind

KEPT_EVENTS: Final = 100
WORD: Final = {RouteKind.TRAIN: "tågväg", RouteKind.SHUNTING: "växlingsväg"}
STALE: Final = (
    "Ställverkets sparade läge gäller en annan version av stationsmodellen. Nollställ ställverket."
)
BROKEN: Final = "Ställverkets sparade läge går inte att läsa. Nollställ ställverket."
STOP, LOCAL, OUT, TRACTION, EMERGENCY, TURNTABLE, PROGRAMMING = (
    PanelFunctionType.SIGNAL_STOP,
    PanelFunctionType.LOCAL_RELEASE,
    PanelFunctionType.OUT_OF_SERVICE,
    PanelFunctionType.TRACTION_CURRENT,
    PanelFunctionType.EMERGENCY_RELEASE,
    PanelFunctionType.TURNTABLE,
    PanelFunctionType.PROGRAMMING_TRACK,
)
SWITCHED: Final = frozenset({STOP, LOCAL, OUT, PROGRAMMING})
"""The functions that are switched on and off."""
KOPPLA_IN: Final = "Studio \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Koppla in"
FEEDBACK_SECONDS: Final = 6
"""How long a route waits for its switches' feedback at level 3 (cda-tkl: commandTimeoutMs)."""
CONNECTED_HELD: Final = "LocoNet anslöts: lägg vägen på nytt när återrapporterna har kommit"
DISCONNECTED_HELD: Final = "LocoNet kopplades från: lägg vägen på nytt"
BY_CIRCUITS: Final = (
    "Med LocoNet följer tågnumret spårledningarna (STV-15): Kör, Ankommit och Avgått görs "
    "av tåget självt."
)


@dataclass(frozen=True)
class Outcome:
    """Ja, or no with the reason; and what goes up to Hubben."""

    accepted: bool
    message: str
    route: int | None = None
    reports: tuple[TklReport, ...] = ()


@dataclass(frozen=True)
class Order:
    """What the layout must do at level 3: a switch part to a position, or a signal to an
    aspect. The service makes the LocoNet message of it."""

    kind: ObjectKind
    name: str
    position: Position | None = None
    aspect: TklAspect | None = None


class UnknownStart(Exception):
    """No route starts or ends at that name."""


@dataclass
class _Route:
    id: int
    way: Way
    chain: int | None
    released: list[bool]
    set_at: datetime
    train: int | None = None
    at: int = -1
    held: str | None = None
    """Why the route's signals are held at stop: a signal stop, a track out of service, or at
    level 3 a switch's feedback that did not come."""
    waiting: dict[str, Position] = field(default_factory=dict)
    """Level 3: the switches it waits for, with the position each must report."""
    waiting_since: datetime | None = None
    came_from: str | None = None
    """Level 3: the section the train came from, which must be free for the passage."""

    @property
    def name(self) -> str:
        return f"{self.way.start} → {self.way.end}"

    def holding(self, hold: Iterable[int]) -> bool:
        return any(not self.released[i] for i in hold)

    def locked_pieces(self) -> Iterator[tuple[int, str]]:
        for i, (_, pieces) in enumerate(self.way.sections):
            if not self.released[i]:
                for piece in pieces:
                    yield i, piece

    def locked_sections(self) -> list[str]:
        return [name for i, (name, _) in enumerate(self.way.sections) if not self.released[i]]

    def locked_parts(self) -> dict[str, Position]:
        positions = self.way.route.positions
        return {p: positions[p] for p, hold in self.way.holds.items() if self.holding(hold)}

    def crossings(self) -> list[str]:
        return [c for c, hold in self.way.crossing_holds.items() if self.holding(hold)]

    def guards(self) -> list[str]:
        return [g for g, hold in self.way.guard_holds.items() if self.holding(hold)]

    def turntable(self) -> tuple[str, str] | None:
        if self.way.turntable is not None and self.holding(self.way.turntable_hold):
            return self.way.turntable
        return None

    def aspect(self) -> TklAspect:
        """The start signal: the route's aspect until the train has passed it, and stop while
        the route is held."""
        if self.at >= 0 or self.way.route.start.kind != PointKind.SIGNAL or self.held:
            return TklAspect.STOP
        if self.waiting:
            return TklAspect.STOP
        return TklAspect.PROCEED if self.way.kind == RouteKind.TRAIN else TklAspect.SHUNT

    def passed_showing(self) -> list[str]:
        """STV-19, a Förslag: the signals the route passes show its aspect until the train
        has passed them. The seam for Benny's answer (trainmeet #62)."""
        return [s for s, k in sorted(self.way.passed_at.items()) if self.at < k]

    def showing(self) -> dict[str, TklAspect]:
        """The signals this route holds at proceed or shunt: none while it is held."""
        if self.held:
            return {}
        kind = TklAspect.PROCEED if self.way.kind == RouteKind.TRAIN else TklAspect.SHUNT
        found = {s: kind for s in self.passed_showing()}
        if self.aspect() != TklAspect.STOP:
            found[self.way.start] = self.aspect()
        return found


@dataclass
class _Train:
    id: int
    number: str | None
    call: str | None
    section: str | None = None
    exit: str | None = None

    @property
    def spot(self) -> Spot:
        return ("section", self.section) if self.section is not None else ("exit", self.exit or "")

    @property
    def said(self) -> str:
        return f"Tåg {self.number}" if self.number else "Tåget utan nummer"


@dataclass
class _Field:
    """Level 3: what the layout has reported, and what TKL has ordered (TklField)."""

    mode: TklFieldMode
    since: datetime
    switches: dict[str, Position | None]
    sections: dict[str, bool | None]
    signals: dict[str, TklAspect | None] = field(default_factory=dict)
    ordered_switches: dict[str, Position | None] = field(default_factory=dict)
    ordered_signals: dict[str, TklAspect] = field(default_factory=dict)

    def shown(self) -> TklField:
        return TklField(
            mode=self.mode,
            since=self.since,
            switches=dict(self.switches),
            sections=dict(self.sections),
            signals=dict(self.signals),
            ordered_switches=dict(self.ordered_switches),
            ordered_signals=dict(self.ordered_signals),
        )


@dataclass
class _Locks:
    """Who holds what, from the set routes, for checking a new one."""

    pieces: dict[str, _Route] = field(default_factory=dict)
    detectors: dict[str, tuple[str, _Route]] = field(default_factory=dict)
    parts: dict[str, list[tuple[_Route, Position]]] = field(default_factory=dict)
    crossings: dict[str, _Route] = field(default_factory=dict)
    turntables: dict[str, tuple[str, _Route]] = field(default_factory=dict)
    showing: dict[str, _Route] = field(default_factory=dict)
    guards: dict[str, list[_Route]] = field(default_factory=dict)

    def add(self, route: _Route, plant: Plant) -> None:
        for _, piece in route.locked_pieces():
            self.pieces.setdefault(piece, route)
        for name in route.locked_sections():
            self.detectors.setdefault(plant.sections[name].detector, (name, route))
        for part, position in route.locked_parts().items():
            self.parts.setdefault(part, []).append((route, position))
        for crossing in route.crossings():
            self.crossings.setdefault(crossing, route)
        table = route.turntable()
        if table is not None:
            self.turntables.setdefault(table[0], (table[1], route))
        for signal in route.showing():
            self.showing.setdefault(signal, route)
        for signal in route.guards():
            self.guards.setdefault(signal, []).append(route)


class Interlocking:
    """The interlocking of one station: its state, and the operations on it."""

    def __init__(
        self,
        plant: Plant,
        saved: TklInterlocking | None = None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.plant = plant
        self.now = now
        self.revision = 0
        self.last_id = 0
        self.positions: dict[str, Position] = plant.initial_positions()
        self.turntables: dict[str, str | None] = {t.id: None for t in plant.model.turntables}
        self.routes: list[_Route] = []
        self.trains: list[_Train] = []
        self.events: list[TklHappening] = []
        self.problem: str | None = None
        self.on: dict[str, bool] = dict.fromkeys(plant.functions, False)
        self.modes: dict[str, str] = {
            name: f.modes[0][0]
            for name, f in plant.functions.items()
            if f.type == TRACTION and f.modes
        }
        self._saved: TklInterlocking | None = None
        self.field: _Field | None = None
        if saved is not None:
            self._restore(saved)

    # --- what is where ------------------------------------------------------------------------

    @property
    def level(self) -> int:
        return self.plant.model.level

    def _route(self, route_id: int) -> _Route | None:
        return next((r for r in self.routes if r.id == route_id), None)

    def _train(self, train_id: int | None) -> _Train | None:
        return next((t for t in self.trains if t.id == train_id), None)

    def _locks(self, routes: Iterable[_Route] | None = None) -> _Locks:
        locks = _Locks()
        for route in self.routes if routes is None else routes:
            locks.add(route, self.plant)
        return locks

    def _occupied(self) -> dict[str, _Train]:
        return {t.section: t for t in self.trains if t.section is not None}

    def _at_start(self, way: Way) -> list[_Train]:
        return [t for t in self.trains if t.spot in way.starts]

    def _route_of_train(self, train: _Train) -> _Route | None:
        """The set route the train is in: its front in one of the route's sections."""
        return next((r for r in self.routes if r.train == train.id and r.at >= 0), None)

    def _under_train(self, part: str, occupied: dict[str, _Train]) -> str | None:
        """The section at the switch with a train in it: its number, or at level 3 its
        circuit's occupancy."""
        node = self.plant.part_node.get(part)
        if node is None:
            return None
        for section in sorted(self.plant.touching(node)):
            if section in occupied:
                return section
            if self.field is not None and self.field.sections.get(section):
                return section
        return None

    def _next_id(self) -> int:
        self.last_id += 1
        return self.last_id

    def _log(self, text: str) -> None:
        self.events.insert(0, TklHappening(at=self.now(), text=text))
        del self.events[KEPT_EVENTS:]

    def note(self, text: str) -> None:
        """A line in the events that changes nothing else, such as how a report went."""
        self.revision += 1
        self._log(text)

    def _done(self, message: str, *, route: int | None = None, log: bool = True) -> Outcome:
        self.revision += 1
        if log:
            self._log(message)
        return Outcome(True, message, route)

    # --- checking a way before it is set ------------------------------------------------------

    def _hindrance(
        self, way: Way, locks: _Locks, occupied: dict[str, _Train], starting: set[str], last: bool
    ) -> str | None:
        """Why the way cannot be set on top of what `locks` holds, or None. A panel function
        that stops it is said first: it is the reason that stays when the rest is free."""
        plant = self.plant
        stopped = self._function_hindrance(way)
        if stopped is not None:
            return stopped
        if self.field is not None:
            not_running = self._not_running(way)
            if not_running is not None:
                return not_running
        for i, (name, pieces) in enumerate(way.sections):
            for piece in pieces:
                holder = locks.pieces.get(piece)
                if holder is not None:
                    return f"{_cap(plant.said(name))} är låst i vägen {holder.name}."
            taken = locks.detectors.get(plant.sections[name].detector)
            if taken is not None:
                return f"{_cap(plant.said(name))} är låst i vägen {taken[1].name}."
            train = occupied.get(name)
            towards = way.kind == RouteKind.SHUNTING and last and i == way.last
            if train is None and not towards and name not in starting:
                detected = self._detected(name)
                if detected is None:
                    return (
                        f"{_cap(plant.said(name))} har okänd beläggning: givaren har inte "
                        "rapporterat än."
                    )
                if detected:
                    return f"{_cap(plant.said(name))} är belagd."
            if train is None or name in starting:
                continue
            if towards:
                continue  # a shunting route may go towards an occupied track (TKL28)
            return f"{_cap(plant.said(name))} är belagd av {train.said.lower()}."
        for crossing in way.route.crossings:
            holder = locks.crossings.get(crossing)
            if holder is not None:
                return f"Korsningen {crossing} är låst i vägen {holder.name}."
        if way.turntable is not None:
            table, piece = way.turntable
            bridge = locks.turntables.get(table)
            if bridge is not None and piece not in plant.alignment(table, bridge[0]):
                return f"Vändskivan {table} står mot ett annat spår för vägen {bridge[1].name}."
        for part, position in way.route.positions.items():
            control = plant.control.get(part)
            if control is None:
                return f"Växel {part} finns inte i stationsmodellen."
            if control != SwitchControl.TKL:
                return not_laid(part, control)
            for holder, held in locks.parts.get(part, []):
                if held != position:
                    return f"Växel {part} är låst i läget {sign(held)} i vägen {holder.name}."
            if self.positions.get(part) != position and not locks.parts.get(part):
                under = self._under_train(part, occupied)
                if under is not None:
                    return f"Växel {part} kan inte läggas om: {plant.said(under)} är belagd."
        shown = [way.start] if way.route.start.kind == PointKind.SIGNAL else []
        for signal in [*shown, *way.route.passed]:
            holder = locks.showing.get(signal)
            if holder is not None:
                return f"Signalen {signal} visar redan kör för vägen {holder.name}."
            for guard in locks.guards.get(signal, []):
                continues = guard.way.end == signal and signal == way.start
                if not continues:
                    return f"Signalen {signal} ska visa stopp för vägen {guard.name}."
        for signal in way.route.guards:
            holder = locks.showing.get(signal)
            if holder is not None and not (signal == way.end and holder.way.start == signal):
                return f"Signalen {signal} visar kör för vägen {holder.name}."
        return None

    # --- level 3: what runs, and what the circuits say (STV-15, STV-17) ---------------------

    def _state(self, kind: ObjectKind, name: str) -> AddressState:
        return self.plant.states.get((kind, name), AddressState.GREY)

    def _runs(self, state: AddressState) -> bool:
        assert self.field is not None
        return state == AddressState.WITHOUT or state in RUNNING[self.field.mode]

    def _refused_state(self, kind: ObjectKind, name: str) -> str | None:
        """Why an object may not run with LocoNet (STV-17), or None."""
        state = self._state(kind, name)
        if self._runs(state):
            return None
        what = {
            ObjectKind.SWITCH: f"Växel {name}",
            ObjectKind.SIGNAL: f"Signalen {name}",
            ObjectKind.TRACK_CIRCUIT: f"Spårledningen {name}",
        }[kind]
        if state == AddressState.GREY:
            why = "den har ingen adress. Koppla in den"
        else:
            why = "adressen är inte bekräftad på banan. Bekräfta den"
        return f"{what} är {STATE_WORD[state]}: {why} i {KOPPLA_IN} (STV-17)."

    def _not_running(self, way: Way) -> str | None:
        """The first object on the way that may not run with LocoNet (STV-17)."""
        plant = self.plant
        for part in way.route.positions:
            if plant.control.get(part) == SwitchControl.TKL:
                why = self._refused_state(ObjectKind.SWITCH, part)
                if why is not None:
                    return why
        shown = [way.start] if way.route.start.kind == PointKind.SIGNAL else []
        for signal in [*shown, *way.route.passed]:
            why = self._refused_state(ObjectKind.SIGNAL, signal)
            if why is not None:
                return why
        for name, _ in way.sections:
            if not plant.sections[name].circuit:
                return (
                    f"{_cap(plant.said(name))} har ingen spårledning: med LocoNet går vägar bara "
                    "över spårledningar (STV-15)."
                )
            why = self._refused_state(ObjectKind.TRACK_CIRCUIT, name)
            if why is not None:
                return why
        return None

    def _detects(self, section: str) -> bool:
        """The section's circuit reports its occupancy now."""
        if self.field is None or not self.plant.sections[section].circuit:
            return False
        return self._state(ObjectKind.TRACK_CIRCUIT, section) in RUNNING[self.field.mode]

    def _detected(self, section: str) -> bool | None:
        """What the circuit says: occupied, free, or None when it has not reported. False
        without LocoNet and for a circuit without a sensor."""
        if not self._detects(section):
            return False
        assert self.field is not None
        return self.field.sections.get(section)

    def _active(self, *kinds: PanelFunctionType) -> Iterator[Function]:
        for name, function in self.plant.functions.items():
            if function.type in kinds and self.on.get(name):
                yield function

    def _function_hindrance(self, way: Way) -> str | None:
        """Why a panel function that is on stops the way (STV-04), or None."""
        shown = [way.start] if way.route.start.kind == PointKind.SIGNAL else []
        for function in self._active(STOP):
            for signal in [*shown, *way.route.passed]:
                if signal in function.signals:
                    return f"Signalen {signal} är i signalstopp ({function.name})."
        for function in self._active(OUT):
            for name, _ in way.sections:
                if name in function.sections:
                    return f"{_cap(self.plant.said(name))} är ur drift ({function.name})."
        for function in self._active(LOCAL):
            if function.touches(way):
                return f"Området för {function.name} är lokalt frigivet för växling."
            for part, position in way.route.positions.items():
                held = function.locked_parts.get(part)
                if held is not None and held != position:
                    return f"Växel {part} är låst i läget {sign(held)} av {function.name}."
        return None

    def _held_by(self, route: _Route) -> str | None:
        """The function that holds a set route at stop now, if any."""
        shown = [route.way.start] if route.way.route.start.kind == PointKind.SIGNAL else []
        for function in self._active(STOP):
            if any(s in function.signals for s in [*shown, *route.way.route.passed]):
                return function.name
        for function in self._active(OUT):
            if any(name in function.sections for name in route.locked_sections()):
                return function.name
        return None

    def _plan(self, chain: Chain) -> tuple[list[_Route], str | None]:
        """The chain as routes on top of the set ones, or why it cannot be set."""
        locks = self._locks()
        occupied = self._occupied()
        starting = {t.section for t in self._at_start(chain[0]) if t.section is not None}
        planned: list[_Route] = []
        for i, way in enumerate(chain):
            why = self._hindrance(
                way, locks, occupied, starting if i == 0 else set(), i == len(chain) - 1
            )
            if why is not None:
                return [], why
            route = _Route(0, way, None, [False] * len(way.sections), self.now())
            planned.append(route)
            locks.add(route, self.plant)
        return planned, None

    def _already(self, kind: RouteKind, start: str, end: str) -> _Route | None:
        """A set route, or the first part of a set chain, from start to end."""
        for route in self.routes:
            if route.way.kind != kind or route.way.start != start:
                continue
            if route.way.end == end:
                return route
            if route.chain == route.id:
                parts = [r for r in self.routes if r.chain == route.id]
                if parts and parts[-1].way.end == end:
                    return route
        return None

    # --- the operations -----------------------------------------------------------------------

    def _refuse_stale(self) -> Outcome | None:
        return Outcome(False, self.problem) if self.problem is not None else None

    def set_route(self, start: str, end: str, kind: RouteKind | None = None) -> Outcome:
        """Lägg en väg (STV-01, STV-03, STV-14, STV-24)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        plant = self.plant
        for name in (start, end):
            if name not in plant.points:
                return Outcome(False, _unknown_point(plant, name))
        if start == end:
            return Outcome(False, "Start och mål är samma.")
        kinds = [kind] if kind is not None else [RouteKind.TRAIN, RouteKind.SHUNTING]
        found: list[Chain] = []
        chosen = kinds[0]
        for k in kinds:
            found = plant.candidates(k, start, end)
            if found:
                chosen = k
                break
        if not found:
            what = f"Ingen {WORD[kind]}" if kind is not None else "Ingen väg"
            return Outcome(False, f"{what} går från {start} till {end}.")
        already = self._already(chosen, start, end)
        if already is not None:
            return self._again(chosen, already)
        reasons: list[str] = []
        for chain in found:
            planned, why = self._plan(chain)
            if why is None:
                return self._lay(chain, planned)
            reasons.append(why)
        return Outcome(False, reasons[0])

    def _again(self, kind: RouteKind, already: _Route) -> Outcome:
        """A route that is set already: held at stop, it is set again when nothing holds it
        any more, and its signal clears. A signal never clears by itself."""
        parts = [r for r in self.routes if r.chain == already.id] or [already]
        said = f"{_cap(WORD[kind])}en {already.way.start} → {parts[-1].way.end}"
        if not any(r.held for r in parts):
            return Outcome(True, f"{said} ligger redan.", already.id)
        for route in parts:
            holder = self._held_by(route)
            if holder is not None:
                return Outcome(False, f"{said} står i stopp: {holder} är på.")
        if self.field is not None:
            for route in parts:
                why = self._not_running(route.way)
                if why is not None:
                    return Outcome(False, why)
        before = self.exit_aspects()
        waiting: list[str] = []
        for route in parts:
            route.held = None
            if self.field is not None and route.at < 0:
                waiting += self._wait_for(route)
        if waiting:
            text = f"{said} lagd på nytt. Väntar på återrapport från växel "
            text += f"{_listed(sorted(set(waiting)))}."
        else:
            text = f"{said} lagd på nytt: signalen visar kör."
        outcome = self._done(text, route=already.id)
        return Outcome(True, outcome.message, already.id, self._exit_reports(before))

    def _lay(self, chain: Chain, planned: list[_Route]) -> Outcome:
        before = self.exit_aspects()
        starting = self._at_start(chain[0])
        for route in planned:
            route.id = self._next_id()
            route.chain = planned[0].id if len(planned) > 1 else None
            if len(starting) == 1:
                route.train = starting[0].id
            for part, position in route.way.route.positions.items():
                if self.plant.control.get(part) == SwitchControl.TKL:
                    self.positions[part] = position
            if route.way.turntable is not None:
                self.turntables[route.way.turntable[0]] = route.way.turntable[1]
        self.routes.extend(planned)
        waiting: list[str] = []
        if self.field is not None:
            for route in planned:
                waiting += self._wait_for(route)
        first, way = planned[0], chain[0]
        word = _cap(WORD[way.kind])
        if len(chain) > 1:
            via = ", ".join(w.end for w in chain[:-1])
            said = f"{word} {way.start} → {chain[-1].end} lagd genom {via} ({len(chain)} delar)"
        else:
            said = f"{word} {first.name} lagd"
        levers = self._levers_of(chain)
        if levers:
            said += f": {levers}"
        if len(starting) == 1:
            said += f". {starting[0].said} tar vägen"
        if waiting:
            said += f". Väntar på återrapport från växel {_listed(sorted(set(waiting)))}"
        outcome = self._done(said + ".", route=first.id)
        return Outcome(True, outcome.message, first.id, self._exit_reports(before))

    def _wait_for(self, route: _Route) -> list[str]:
        """Level 3: the route waits for every switch it lays that has not reported its
        position, and each is ordered again."""
        assert self.field is not None
        field_ = self.field
        route.waiting = {
            part: position
            for part, position in route.way.route.positions.items()
            if self.plant.control.get(part) == SwitchControl.TKL
            and field_.switches.get(part) != position
        }
        route.waiting_since = self.now() if route.waiting else None
        for part in route.waiting:
            field_.ordered_switches[part] = None
        return list(route.waiting)

    def _levers_of(self, chain: Chain) -> str:
        plant = self.plant
        found: dict[str, Position] = {}
        for way in chain:
            for part in way.route.positions:
                lever = plant.levers.own.get(part)
                if lever is not None and lever not in found:
                    side = plant.lever_side(lever, self.positions)
                    if side is not None:
                        found[lever] = side
        return ", ".join(f"{lever} {sign(side)}" for lever, side in found.items())

    def release(self, route_id: int) -> Outcome:
        """Lös ut: a route without a train in it, or with the train at its end."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre. Ingenting löstes ut.")
        train = self._train(route.train)
        if 0 <= route.at < route.way.last:
            who = train.said if train else "Tåget"
            return Outcome(
                False, f"{who} är i vägen {route.name}. Kör fram tåget, eller nödutlös vägen."
            )
        before = self.exit_aspects()
        self._complete(route)
        outcome = self._done(f"Vägen {route.name} är utlöst.")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def emergency_release(self, route_id: int, confirm: bool) -> Outcome:
        """Nödutlös: the route goes even with a train in it. The train stays where it is."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre. Ingenting löstes ut.")
        if not confirm:
            return Outcome(
                False,
                f"Bekräfta nödutlösningen av vägen {route.name}. Den löses ut fast ett tåg kan "
                "vara i den.",
            )
        before = self.exit_aspects()
        train = self._train(route.train) if route.at >= 0 else None
        self._complete(route)
        said = f"Nödutlösning av vägen {route.name}, bekräftad."
        if train is not None:
            where = self.plant.said(train.section) if train.section else "linjen"
            said += f" {train.said} står kvar i {where}."
        outcome = self._done(said)
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def lay_lever(self, switch: str, position: Position | None = None) -> Outcome:
        """Lägg hela spaken (STV-01, STV-52, TKL104)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        plant = self.plant
        lever_id, why = plant.lever_of(switch)
        if lever_id is None:
            return Outcome(False, why or f"Växel {switch} finns inte i stationsmodellen.")
        lever = plant.levers.levers[lever_id]
        current = plant.lever_side(lever_id, self.positions)
        if position is None:
            if current is None:
                return Outcome(
                    False, f"Spaken {lever_id} ligger i kors. Ange läget, + eller {MINUS_SIGN}."
                )
            side = Position.MINUS if current == Position.PLUS else Position.PLUS
        else:
            side = position
        laid = plant.levers.lay(dict(lever.plus if side == Position.PLUS else lever.minus))
        if laid is None:
            return Outcome(
                False,
                f"Spaken {lever_id} kan inte läggas i {sign(side)}: den behöver en växel åt "
                "båda hållen.",
            )
        own = set(lever.plus) & set(lever.minus)
        moving = {p: v for p, v in laid.positions.items() if self.positions.get(p) != v}
        locks = self._locks()
        occupied = self._occupied()
        for part in sorted(moving, key=lambda p: (p not in own, p)):
            control = plant.control.get(part)
            if control is None:
                return Outcome(False, f"Växel {part} finns inte i stationsmodellen.")
            if control != SwitchControl.TKL:
                return Outcome(False, not_laid(part, control))
            if self.field is not None:
                why = self._refused_state(ObjectKind.SWITCH, part)
                if why is not None:
                    return Outcome(False, why)
            held = locks.parts.get(part)
            if held:
                follow = "" if part in own else " och kan inte följa med"
                return Outcome(False, f"Växel {part} är låst i vägen {held[0][0].name}{follow}.")
            for function in self._active(LOCAL):
                if part in function.locked_parts:
                    return Outcome(False, f"Växel {part} är låst av {function.name}.")
                if part in function.switches:
                    return Outcome(
                        False,
                        f"Växel {part} är lokalt frigiven ({function.name}) och läggs om med "
                        "knappen på modulen.",
                    )
            under = self._under_train(part, occupied)
            if under is not None:
                return Outcome(
                    False, f"Växel {part} kan inte läggas om: {plant.said(under)} är belagd."
                )
        if not moving:
            return Outcome(True, f"Spaken {lever_id} ligger redan i {sign(side)}.")
        self.positions.update(moving)
        dragged = [f"{p} {sign(v)}" for p, v in sorted(moving.items()) if p not in own]
        said = f"Spaken {lever_id} lagd i {sign(side)}"
        if dragged:
            said += f", drar med {', '.join(dragged)}"
        return self._done(said + ".")

    def _train_for(self, route: _Route) -> tuple[_Train | None, str]:
        """The train that takes the route: the one bound to it if it is at the start, else
        the only one there."""
        bound = self._train(route.train)
        if bound is not None and bound.spot in route.way.starts and self._free(bound):
            return bound, ""
        at_start = self._at_start(route.way)
        found = [t for t in at_start if self._free(t)]
        if len(found) == 1:
            return found[0], ""
        if not found and at_start:
            inside = self._route_of_train(at_start[0])
            where = f" är i vägen {inside.name}" if inside is not None else " kan inte ta vägen"
            return None, f"{at_start[0].said}{where}."
        if not found:
            return None, f"Inget tåg står vid {route.way.start}. Sätt ut tågnumret först."
        numbers = ", ".join(t.number or "utan nummer" for t in found)
        return None, f"Flera tåg står vid {route.way.start}: {numbers}. Ta bort ett av dem."

    def _free(self, train: _Train) -> bool:
        """The train may take a new route: it is in none, or at the end of the one it is in."""
        inside = self._route_of_train(train)
        return inside is None or inside.at == inside.way.last

    def _enter(self, route: _Route, train: _Train) -> str:
        """The train takes the route: its front into the first section, or the second when it
        already stands in the first. A route it leaves behind is done."""
        behind = self._route_of_train(train)
        if behind is not None and behind is not route:
            self._complete(behind)
        first = route.way.sections[0][0]
        target = 1 if train.section == first and route.way.last >= 1 else 0
        route.train = train.id
        route.at = target
        for i in range(target):
            route.released[i] = True
        train.section, train.exit = route.way.sections[target][0], None
        return f"{train.said} kör {route.name}: i {self.plant.said(train.section)}."

    def step(self, route_id: int) -> Outcome:
        """Kör: the train number one section on, and the section behind released (STV-06)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        if self.field is not None:
            return Outcome(False, BY_CIRCUITS)
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre.")
        before = self.exit_aspects()
        reports: list[TklReport] = []
        if route.at < 0 and route.held:
            return Outcome(False, _held_said(route))
        if route.at < 0:
            train, why = self._train_for(route)
            if train is None:
                return Outcome(False, why)
            said = self._enter(route, train)
        elif route.at < route.way.last:
            train = self._train(route.train)
            if train is None:
                return Outcome(False, "Tåget i vägen finns inte längre. Nödutlös vägen.")
            behind = route.way.sections[route.at][0]
            route.released[route.at] = True
            route.at += 1
            train.section = route.way.sections[route.at][0]
            said = (
                f"{train.said} i {self.plant.said(train.section)}; "
                f"{self.plant.said(behind)} utlöst."
            )
        else:
            train = self._train(route.train)
            if train is None:
                return Outcome(False, "Tåget i vägen finns inte längre. Nödutlös vägen.")
            onward = self._onward(route, train)
            if onward is not None:
                said = self._enter(onward, train)
            elif route.way.leaves is not None:
                said, report = self._leave(route, train)
                reports.append(report)
            else:
                return Outcome(
                    False,
                    f"{train.said} står vid målet {route.way.end}. Tryck Ankommit, lös ut vägen "
                    "eller lägg nästa väg därifrån.",
                )
        outcome = self._done(said)
        return Outcome(True, outcome.message, None, (*reports, *self._exit_reports(before)))

    def _onward(self, route: _Route, train: _Train) -> _Route | None:
        """The set route the train takes on from where this one ends."""
        for other in self.routes:
            free = other.at < 0 and other.train in (None, train.id)
            if other is not route and free and train.spot in other.way.starts:
                return other
        return None

    def _leave(self, route: _Route, train: _Train) -> tuple[str, TklReport]:
        """The train leaves on the line: off the panel, and the departure goes up."""
        exit_id = route.way.leaves or ""
        self._complete(route)
        self.trains.remove(train)
        for other in self.routes:
            if other.train == train.id:
                other.train = None
        report = TklReport(
            kind=TklReportKind.DEPARTED,
            train_number=train.number,
            call=train.call,
            exit=self.plant.exits[exit_id].outside if exit_id in self.plant.exits else None,
        )
        return f"{train.said} har lämnat mot {exit_id}.", report

    def arrive(self, route_id: int) -> Outcome:
        """Ankommit (STV-16): the train stands at the route's end. The route is released and
        the arrival goes up to Hubben, with the track the train stands on."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        if self.field is not None:
            return Outcome(False, BY_CIRCUITS)
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre.")
        train = self._train(route.train)
        if route.at != route.way.last or train is None:
            who = train.said if train is not None and route.at >= 0 else "Inget tåg"
            return Outcome(False, f"{who} har inte kommit fram till {route.way.end} än.")
        before = self.exit_aspects()
        self._complete(route)
        track = self.plant.track_of.get(train.section or "")
        where = f"spår {track}" if track else self.plant.said(train.section or "")
        report = TklReport(
            kind=TklReportKind.ARRIVED,
            train_number=train.number,
            call=train.call,
            track=self.plant.track_outside.get(track) if track else None,
        )
        outcome = self._done(
            f"{train.said} har kommit fram till {where}. Vägen {route.name} är utlöst."
        )
        reports = (report,) if train.number or train.call else ()
        return Outcome(True, outcome.message, None, (*reports, *self._exit_reports(before)))

    def depart(self, route_id: int) -> Outcome:
        """Avgått: the train on a route out has left on the line (STV-10)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        if self.field is not None:
            return Outcome(False, BY_CIRCUITS)
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre.")
        if route.way.leaves is None:
            return Outcome(False, f"Vägen {route.name} går inte ut på linjen.")
        if route.at < 0 and route.held:
            return Outcome(False, _held_said(route))
        if route.at >= 0:
            train = self._train(route.train)
            if train is None:
                return Outcome(False, "Tåget i vägen finns inte längre. Nödutlös vägen.")
        else:
            train, why = self._train_for(route)
            if train is None:
                return Outcome(False, why)
            behind = self._route_of_train(train)
            if behind is not None:
                self._complete(behind)
        before = self.exit_aspects()
        said, report = self._leave(route, train)
        outcome = self._done(said)
        return Outcome(True, outcome.message, None, (report, *self._exit_reports(before)))

    def put_train(
        self,
        number: str | None,
        *,
        call: str | None = None,
        section: str | None = None,
        exit: str | None = None,
    ) -> Outcome:
        """Sätt ut ett tågnummer: on a section, or on the line at an exit (STV-10)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        plant = self.plant
        if (section is None) == (exit is None):
            return Outcome(False, "Ange ett spår eller en utfart för tåget.")
        said = f"Tåg {number}" if number else "Tåget utan nummer"
        for train in self.trains:
            if number and train.number == number:
                return Outcome(False, f"Tåg {number} står redan i ställverket.")
            if call and train.call == call:
                return Outcome(False, f"Tågbesöket {call} har redan ett tåg i ställverket.")
        if section is not None:
            if section not in plant.sections:
                return Outcome(False, f"Spårledningen {section} finns inte i stationsmodellen.")
            line = plant.exit_of_section(section)
            if line is not None:
                section, exit = None, line
        if section is not None:
            holder = self._locks().pieces
            for piece in plant.sections[section].pieces:
                if piece in holder:
                    return Outcome(
                        False,
                        f"{_cap(plant.said(section))} är låst i vägen {holder[piece].name}.",
                    )
            if section in self._occupied():
                return Outcome(False, f"Det står redan ett tåg i {plant.said(section)}.")
            where = plant.said(section)
        else:
            if exit not in plant.exits:
                return Outcome(False, f"Utfarten {exit} finns inte i stationsmodellen.")
            if any(t.exit == exit for t in self.trains):
                return Outcome(False, f"Det står redan ett tåg på linjen vid {exit}.")
            where = f"linjen vid {exit}"
        before = self.exit_aspects()
        self.trains.append(_Train(self._next_id(), number, call, section, exit))
        outcome = self._done(f"{said} står på {where}." if exit else f"{said} står i {where}.")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def remove_train(self, train_id: int) -> Outcome:
        """Ta bort ett tågnummer: never from inside a set route."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        train = self._train(train_id)
        if train is None:
            return Outcome(False, "Tåget finns inte längre i ställverket.")
        inside = self._route_of_train(train)
        if inside is not None:
            return Outcome(
                False, f"{train.said} är i vägen {inside.name}. Lös ut eller nödutlös vägen först."
            )
        for route in self.routes:
            if route.train == train.id:
                route.train = None
        self.trains.remove(train)
        return self._done(f"{train.said} är borttaget ur ställverket.")

    def reset(self, confirm: bool, trains: bool = False) -> Outcome:
        """Nollställ: every route released and the switches left where they are; with trains,
        the numbers go too. A state that belongs to another model starts over."""
        if not confirm:
            return Outcome(False, "Bekräfta att ställverket ska nollställas.")
        before = self.exit_aspects()
        released = len(self.routes)
        stale = self.problem is not None
        if stale:
            kept = self._saved.switches if self._saved is not None else {}
            for part, shown in kept.items():
                if part in self.positions and shown.position is not None:
                    self.positions[part] = shown.position
            self.trains = []
            self.problem, self._saved = None, None
        self.routes = []
        removed = len(self.trains) if trains else 0
        if trains:
            self.trains = []
        said = f"Ställverket nollställt: {released} vägar utlösta"
        if removed or stale:
            said += ", tågnumren borttagna"
        outcome = self._done(said + ".")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    # --- the panel functions (STV-04, STV-53) -------------------------------------------------

    def function(
        self,
        name: str,
        action: TklFunctionAction,
        value: str | None = None,
        *,
        confirm: bool = False,
    ) -> Outcome:
        """Manövrera en panelfunktion ur katalogen, by its name in the model (STV-04)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        function = self.plant.functions.get(name)
        if function is None:
            return Outcome(False, f"Panelfunktionen {name} finns inte i stationsmodellen.")
        if function.type in SWITCHED and action in (TklFunctionAction.ON, TklFunctionAction.OFF):
            return self._switch(function, action == TklFunctionAction.ON)
        if function.type == LOCAL and action == TklFunctionAction.LAY:
            return self._lay_local(function, value)
        if function.type in (TRACTION, TURNTABLE) and action == TklFunctionAction.SET:
            if function.type == TRACTION:
                return self._traction(function, value)
            return self._turn(function, value)
        if function.type == EMERGENCY and action == TklFunctionAction.RELEASE:
            return self._release_area(function, confirm)
        return Outcome(False, f"{_cap(function.name)} går inte att manövrera så.")

    def _switch(self, function: Function, on: bool) -> Outcome:
        name = function.name
        if self.on.get(name, False) == on:
            return Outcome(True, f"{_cap(name)} är redan {'på' if on else 'av'}.")
        if function.type == LOCAL:
            return self._local(function, on)
        before = self.exit_aspects()
        self.on[name] = on
        if function.type == PROGRAMMING:
            said = "om till programmeringsspår" if on else "tillbaka till körström"
            return self._done(f"{_cap(name)} kopplades {said}.")
        if not on:
            said = f"{_cap(name)} kopplades ur."
            if any(r.held == name for r in self.routes):
                said += " Vägarna som stoppades visar stopp tills de läggs på nytt."
            outcome = self._done(said)
            return Outcome(True, outcome.message, None, self._exit_reports(before))
        stopped = []
        for route in self.routes:
            if route.held is None and self._held_by(route) == name:
                route.held = name
                stopped.append(route.name)
        if function.type == STOP:
            said = f"{_cap(name)} kopplades in: {_listed(function.signals)} visar stopp"
        else:
            said = f"{_cap(name)} kopplades in: inga vägar läggs över spåret"
        if stopped:
            routes = "Vägen" if len(stopped) == 1 else "Vägarna"
            said += f". {routes} {_listed(stopped)} ligger kvar med signalen i stopp"
        outcome = self._done(said + ".")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def _local(self, function: Function, on: bool) -> Outcome:
        """Lokal frigivning in or out (TKL44, STD-14, FR41)."""
        name = function.name
        local = _listed(function.switches)
        if not on:
            self.on[name] = False
            return self._done(f"{_cap(name)} kopplades ur: {local} läggs åter från ställverket.")
        touching = [r.name for r in self.routes if function.touches(r.way)]
        if touching:
            return Outcome(False, f"Lös ut vägarna i området först: {_listed(touching)}.")
        locks = self._locks()
        occupied = self._occupied()
        moving = {p: v for p, v in function.locked_parts.items() if self.positions.get(p) != v}
        for part in sorted(moving):
            held = locks.parts.get(part)
            if held:
                return Outcome(False, f"Växel {part} är låst i vägen {held[0][0].name}.")
            under = self._under_train(part, occupied)
            if under is not None:
                return Outcome(
                    False,
                    f"Växel {part} kan inte läggas om: {self.plant.said(under)} är belagd.",
                )
        before = self.exit_aspects()
        self.positions.update(moving)
        self.on[name] = True
        said = f"{_cap(name)} kopplades in"
        if function.locked:
            levers = _listed(f"{lever} {sign(side)}" for lever, side in function.locked.items())
            said += f": {levers} låsta"
        if function.switches:
            said += f"{',' if function.locked else ':'} {local} läggs om med knapparna på modulerna"
        outcome = self._done(said + ".")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def _lay_local(self, function: Function, value: str | None) -> Outcome:
        """A local switch laid with the module's button, while the area is released."""
        name = function.name
        if not self.on.get(name):
            return Outcome(False, f"{_cap(name)} är av. Växeln läggs från ställverket.")
        plant = self.plant
        lever_id, why = plant.lever_of(value or "")
        if lever_id is None:
            return Outcome(False, why or "Ange växeln.")
        lever = plant.levers.levers[lever_id]
        own = set(lever.plus) & set(lever.minus)
        if not own or not own <= set(function.switches):
            return Outcome(False, f"Växel {value} är inte lokal i {name}.")
        current = plant.lever_side(lever_id, self.positions)
        side = Position.MINUS if current == Position.PLUS else Position.PLUS
        laid = plant.levers.lay(dict(lever.plus if side == Position.PLUS else lever.minus))
        if laid is None:
            return Outcome(False, f"Växel {value} kan inte läggas i {sign(side)}.")
        moving = {p: v for p, v in laid.positions.items() if self.positions.get(p) != v}
        locks = self._locks()
        for part in sorted(moving):
            if plant.control.get(part) != SwitchControl.TKL:
                return Outcome(False, not_laid(part, plant.control.get(part, SwitchControl.TKL)))
            held = locks.parts.get(part)
            if held:
                return Outcome(False, f"Växel {part} är låst i vägen {held[0][0].name}.")
            if part in function.locked_parts:
                return Outcome(False, f"Växel {part} är låst av {name}.")
        self.positions.update(moving)
        return self._done(f"Växel {lever_id} lagd i {sign(side)} med knappen på modulen.")

    def _traction(self, function: Function, value: str | None) -> Outcome:
        """Körström: the track's mode. It touches no route."""
        name = function.name
        modes = [m for m, _ in function.modes]
        if value not in modes:
            said = f"{_cap(name)} har inget läge {value}. Lägena är {_listed(modes)}."
            return Outcome(False, said)
        if self.modes.get(name) == value:
            return Outcome(True, f"{_cap(name)} är redan {value}.")
        self.modes[name] = value
        return self._done(f"{_cap(name)}: {value}.")

    def _turn(self, function: Function, value: str | None) -> Outcome:
        """Vändskivan: the bridge turned to a track; refused while a route holds it elsewhere."""
        table = function.turntable
        labels = dict(function.modes)
        named = {label: piece for piece, label in labels.items()}
        piece = value if value in labels else named.get(value or "")
        if table is None or piece is None:
            return Outcome(False, f"{_cap(function.name)} har inget spår {value}.")
        held = self._locks().turntables.get(table)
        if held is not None and piece not in self.plant.alignment(table, held[0]):
            return Outcome(False, f"{_cap(function.name)} är låst i vägen {held[1].name}.")
        current = self.turntables.get(table)
        if current is not None and piece in self.plant.alignment(table, current):
            return Outcome(True, f"{_cap(function.name)} står redan mot {labels[piece]}.")
        self.turntables[table] = piece
        return self._done(f"{_cap(function.name)} vriden mot {labels[piece]}.")

    def _release_area(self, function: Function, confirm: bool) -> Outcome:
        """Nödutlösning per spårledning: every lock in the function's sections is released,
        whatever route holds it, after a confirmation. Logged."""
        names = _listed(sorted(function.sections))
        if not confirm:
            return Outcome(
                False,
                f"Bekräfta nödutlösningen av {names}. Låsen där släpps fast ett tåg kan stå där.",
            )
        before = self.exit_aspects()
        released = 0
        for route in list(self.routes):
            for i, (name, _) in enumerate(route.way.sections):
                if name in function.sections and not route.released[i]:
                    route.released[i] = True
                    released += 1
            if all(route.released):
                self._complete(route)
        outcome = self._done(
            f"Nödutlösning av {names} ({function.name}), bekräftad: {released} sektioner utlösta."
        )
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def _complete(self, route: _Route) -> None:
        """The route is done: every lock it still holds is released."""
        if route in self.routes:
            self.routes.remove(route)

    # --- level 3: LocoNet (#85, STV-11, STV-15–STV-17) -------------------------------------------

    def _laid(self) -> list[str]:
        return [p for p, c in self.plant.control.items() if c == SwitchControl.TKL]

    def _circuits(self) -> list[str]:
        return [n for n, section in self.plant.sections.items() if section.circuit]

    def field_connect(self, mode: TklFieldMode | None) -> Outcome:
        """LocoNet connected, against the layout or the pretend LocoNet, or disconnected (None).
        Either way every set route keeps its locks and shows stop until it is set again:
        nothing the layout said before counts (cda-tkl: Återansluten, inväntar nya
        återrapporter). Connected, every switch, circuit and signal is unknown until reported."""
        if mode is None:
            if self.field is None:
                return Outcome(True, "LocoNet är inte anslutet.")
            self.field = None
            for route in self.routes:
                route.held = route.held or DISCONNECTED_HELD
                route.waiting, route.waiting_since = {}, None
            return self._done(
                "LocoNet kopplades från. Vägarna ligger kvar med sina lås och signalerna i stopp; "
                "ställverket går med knapparna som på nivå 1–2."
            )
        if self.level < 3:
            return Outcome(
                False,
                f"Stationen är inte på nivå 3. Slå på nivå 3 i {KOPPLA_IN}.",
            )
        self.field = _Field(
            mode=mode,
            since=self.now(),
            switches=dict.fromkeys(self._laid()),
            sections=dict.fromkeys(self._circuits()),
            ordered_switches=dict(self.positions),
        )
        for route in self.routes:
            route.held = route.held or CONNECTED_HELD
            route.waiting, route.waiting_since = {}, None
        where = "låtsas-LocoNet, LocoNet ej ansluten" if mode == TklFieldMode.PRETEND else "banan"
        return self._done(
            f"LocoNet anslutet ({where}): spårledningarna styr tågnumren och växlarna "
            "återrapporterar (nivå 3). Alla signaler i stopp."
        )

    def take_orders(self) -> list[Order]:
        """What the layout must do now that it has not been told: the switches whose position
        changed, or that a route waits for, and the signals whose aspect changed. Each is
        noted as ordered."""
        field_ = self.field
        if field_ is None or self.problem is not None:
            return []
        orders: list[Order] = []
        for part, position in self.positions.items():
            if field_.ordered_switches.get(part) != position:
                field_.ordered_switches[part] = position
                orders.append(Order(ObjectKind.SWITCH, part, position=position))
        for name, aspect in self._aspects().items():
            if field_.ordered_signals.get(name) != aspect:
                field_.ordered_signals[name] = aspect
                orders.append(Order(ObjectKind.SIGNAL, name, aspect=aspect))
        if orders:
            self.revision += 1
        return orders

    def field_reports(self, reports: Iterable[FieldReport]) -> Outcome:
        """What the layout reported. Accepted with what it led to; the revision only moves when
        something changed."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        if self.field is None:
            return Outcome(False, "LocoNet är inte anslutet.")
        before = self.exit_aspects()
        changed = False
        said: list[str] = []
        up: list[TklReport] = []
        for report in reports:
            if isinstance(report, SwitchReported):
                moved, lines = self._switch_reported(report.part, report.position)
            elif isinstance(report, SectionReported):
                moved, lines, sent = self._section_reported(report.section, report.occupied)
                up += sent
            else:
                moved, lines = self._signal_reported(report)
            changed = changed or moved
            said += lines
        if not changed:
            return Outcome(True, "")
        self.revision += 1
        for line in said:
            self._log(line)
        return Outcome(True, " ".join(said), None, (*up, *self._exit_reports(before)))

    def field_tick(self) -> Outcome:
        """The time: a route whose switches have not all reported within the time is held."""
        if self.field is None or self.problem is not None:
            return Outcome(True, "")
        now = self.now()
        before = self.exit_aspects()
        said = []
        for route in self.routes:
            since = route.waiting_since
            if not route.waiting or since is None or route.held:
                continue
            if (now - since).total_seconds() < FEEDBACK_SECONDS:
                continue
            parts = _listed(sorted(route.waiting))
            route.held = f"ingen återrapport från växel {parts} inom {FEEDBACK_SECONDS} sekunder"
            said.append(
                f"Vägen {route.name} står i stopp: {route.held}. Lägg den på nytt eller lös ut den."
            )
        if not said:
            return Outcome(True, "")
        self.revision += 1
        for line in said:
            self._log(line)
        return Outcome(True, " ".join(said), None, self._exit_reports(before))

    def _switch_reported(self, part: str, position: Position | None) -> tuple[bool, list[str]]:
        assert self.field is not None
        if part not in self.field.switches or self.field.switches[part] == position:
            return False, []
        self.field.switches[part] = position
        said: list[str] = []
        for route in self.routes:
            wanted = route.waiting.get(part)
            if wanted is not None:
                if position != wanted:
                    continue
                del route.waiting[part]
                if not route.waiting:
                    route.waiting_since = None
                    if not route.held:
                        word = "kör" if route.way.kind == RouteKind.TRAIN else "växling"
                        said.append(
                            f"Vägen {route.name}: växlarna ligger rätt, signalen visar {word}."
                        )
                continue
            locked = route.locked_parts().get(part)
            if locked is None or route.held or position == locked:
                continue
            word = "okänt läge" if position is None else sign(position)
            route.held = f"växel {part} rapporterar {word}, men vägen kräver {sign(locked)}"
            said.append(f"Vägen {route.name} står i stopp: {route.held}.")
        return True, said

    def _signal_reported(self, report: SignalReported) -> tuple[bool, list[str]]:
        assert self.field is not None
        if report.name not in self.plant.signals:
            return False, []
        if self.field.signals.get(report.name) == report.aspect:
            return False, []
        self.field.signals[report.name] = report.aspect
        return True, []

    def _section_reported(
        self, section: str, occupied: bool
    ) -> tuple[bool, list[str], list[TklReport]]:
        """A circuit's occupancy: the train number follows it (STV-15)."""
        field_ = self.field
        assert field_ is not None
        if section not in field_.sections or field_.sections[section] == occupied:
            return False, [], []
        field_.sections[section] = occupied
        up: list[TklReport] = []
        line = self.plant.exit_of_section(section)
        if line is not None:
            up.append(
                TklReport(
                    kind=TklReportKind.SECTION_OCCUPANCY,
                    exit=self.plant.exits[line].outside,
                    occupied=occupied,
                )
            )
        said, reports = self._front(section) if occupied else self._tail(section)
        return True, said, [*up, *reports]

    def _ahead(self, route: _Route, section: str) -> int | None:
        """The section of the route the front has come into, past sections that cannot say."""
        for i in range(route.at + 1, len(route.way.sections)):
            name = route.way.sections[i][0]
            if name == section:
                return i
            if self._detects(name):
                return None
        return None

    def _front(self, section: str) -> tuple[list[str], list[TklReport]]:
        """A circuit became occupied: a train's front moves on in its route, or a train takes a
        set route whose signal shows kör. Anything else is only shown as occupied."""
        for route in self.routes:
            if route.at < 0 or route.at >= route.way.last:
                continue
            ahead = self._ahead(route, section)
            if ahead is None:
                continue
            route.at = ahead
            train = self._train(route.train)
            if train is not None:
                train.section, train.exit = section, None
            who = train.said if train is not None else "Tåget"
            return [f"{who} i {self.plant.said(section)}."], []
        for route in self.routes:
            if route.at >= 0 or route.held or route.waiting:
                continue
            if route.way.route.start.kind == PointKind.SIGNAL and route.aspect() == TklAspect.STOP:
                continue
            names = [name for name, _ in route.way.sections]
            if section != names[0] and not (len(names) > 1 and section == names[1]):
                continue
            train, _ = self._train_for(route)
            if train is not None and section != names[0] and train.section != names[0]:
                continue
            if train is None:
                if section != names[0]:
                    continue
                train = _Train(self._next_id(), None, None, None, None)
                self.trains.append(train)
                came_from = None
            else:
                came_from = train.section or self._box(train.exit)
            said = self._enter(route, train)
            route.came_from = came_from if came_from and self._detects(came_from) else None
            return [said], []
        return [], []

    def _box(self, exit_id: str | None) -> str | None:
        """The section on the line just outside an exit's entry signal."""
        place = self.plant.exits.get(exit_id or "")
        if place is None or not place.pieces:
            return None
        return self.plant.section_of.get(place.pieces[-1])

    def _tail(self, section: str) -> tuple[list[str], list[TklReport]]:
        """A circuit became free: behind a train that has moved on, the route is released up to
        it; a train that has passed into its route's last section has arrived (STV-16); a
        train that left its route's last section for the line has departed. Nothing else."""
        said: list[str] = []
        up: list[TklReport] = []
        for route in list(self.routes):
            if route.at < 0:
                continue
            train = self._train(route.train)
            names = [name for name, _ in route.way.sections]
            if route.came_from == section:
                route.came_from = None
            behind = [i for i, name in enumerate(names) if name == section and i < route.at]
            if behind:
                newly = [j for j in range(max(behind) + 1) if not route.released[j]]
                for j in newly:
                    route.released[j] = True
                if newly:
                    who = train.said.lower() if train is not None else "tåget"
                    said.append(f"{_cap(self.plant.said(section))} utlöst efter {who}.")
            at_end = route.at == route.way.last
            if at_end and names[-1] == section and self._out_on_line(route):
                if train is not None:
                    text, report = self._leave(route, train)
                    said.append(text)
                    up.append(report)
                else:
                    self._complete(route)
                continue
            if at_end and route.way.leaves is None and self._passed(route, train):
                text, reports = self._arrived(route, train)
                said.append(text)
                up += reports
        return said, up

    def _out_on_line(self, route: _Route) -> bool:
        """A route out has its train on the line: where the line outside the exit has a
        circuit, it must be occupied; without one, the route's last section being free is all
        there is to go by."""
        if route.way.leaves is None:
            return False
        box = self._box(route.way.leaves)
        if box is None or not self._detects(box):
            return True
        assert self.field is not None
        return bool(self.field.sections.get(box))

    def _passed(self, route: _Route, train: _Train | None) -> bool:
        """The train stands wholly in the route's last section: every section behind it with a
        circuit that can say is released, and the one it came from is free. A train with a set
        route on from there goes on instead."""
        if route.came_from is not None:
            return False
        for i in range(route.way.last):
            if not route.released[i] and self._detects(route.way.sections[i][0]):
                return False
        return train is None or self._onward(route, train) is None

    def _arrived(self, route: _Route, train: _Train | None) -> tuple[str, list[TklReport]]:
        """Ankomst at level 3: the route released after passage (STV-16)."""
        self._complete(route)
        word = _cap(WORD[route.way.kind])
        if train is None:
            return f"{word}en {route.name} är utlöst efter passage.", []
        section = train.section or ""
        track = self.plant.track_of.get(section)
        where = f"spår {track}" if track else self.plant.said(section)
        said = f"{train.said} har kommit fram till {where}. "
        said += f"{word}en {route.name} är utlöst efter passage."
        if route.way.kind != RouteKind.TRAIN or not (train.number or train.call):
            return said, []
        report = TklReport(
            kind=TklReportKind.ARRIVED,
            train_number=train.number,
            call=train.call,
            track=self.plant.track_outside.get(track) if track else None,
        )
        return said, [report]

    # --- goals from a start (for choosing, STV-01, STV-24) ------------------------------------

    def targets(self, start: str) -> TklTargets:
        """The goals from a start, by kind, with whether each can be set now and why not."""
        plant = self.plant
        if start not in plant.points:
            raise UnknownStart(_unknown_point(plant, start))
        kinds = plant.kinds(start)
        found: list[TklTarget] = []
        for kind in kinds:
            for end in plant.ends(kind, start):
                chains = plant.candidates(kind, start, end)
                if not chains:
                    continue
                already = self._already(kind, start, end)
                chosen, reason = self._settable(chains, already)
                found.append(
                    TklTarget(
                        end=end,
                        kind=ShownKind(kind.value),
                        via=[w.end for w in chosen[:-1]],
                        pieces=[p for w in chosen for p in w.pieces],
                        possible=reason is None,
                        reason=reason,
                        route=already.id if already is not None else None,
                    )
                )
        return TklTargets(start=start, kinds=[ShownKind(k.value) for k in kinds], targets=found)

    def _settable(self, chains: list[Chain], already: _Route | None) -> tuple[Chain, str | None]:
        """The chain a click would set now, or the preferred one and why none can be."""
        if self.problem is not None:
            return chains[0], self.problem
        if already is not None:
            return chains[0], None
        first: str | None = None
        for chain in chains:
            _, why = self._plan(chain)
            if why is None:
                return chain, None
            first = first or why
        return chains[0], first

    # --- the view (STV-08), and what it says to Hubben ----------------------------------------

    def exit_aspects(self) -> dict[str, ExitSignalAspect]:
        """What each exit's signal.exit says: proceed while a train route out shows proceed
        from its start, else stop. Level 1 has no signals."""
        found: dict[str, ExitSignalAspect] = {}
        for exit_id in self.plant.exits:
            if self.level < 2:
                found[exit_id] = ExitSignalAspect.UNKNOWN
                continue
            out = any(
                r.way.leaves == exit_id
                and r.way.kind == RouteKind.TRAIN
                and r.aspect() == TklAspect.PROCEED
                for r in self.routes
            )
            found[exit_id] = ExitSignalAspect.PROCEED if out else ExitSignalAspect.STOP
        return found

    def _exit_reports(self, before: dict[str, ExitSignalAspect]) -> tuple[TklReport, ...]:
        if self.level < 2:
            return ()
        reports = []
        for exit_id, aspect in self.exit_aspects().items():
            if before.get(exit_id) == aspect:
                continue
            route = next(
                (
                    r
                    for r in self.routes
                    if r.way.leaves == exit_id and r.way.kind == RouteKind.TRAIN
                ),
                None,
            )
            train = self._train(route.train) if route is not None else None
            reports.append(
                TklReport(
                    kind=TklReportKind.EXIT_SIGNAL,
                    train_number=train.number if train else None,
                    call=train.call if train else None,
                    exit=self.plant.exits[exit_id].outside,
                    aspect=aspect,
                )
            )
        return tuple(reports)

    def green_numbers(self) -> list[TklNumber]:
        """STV-21, a Förslag: the green number stands ahead of the train in the last section
        of a train route set for it, until the front is there; on each part of a chain. The
        seam for where it stands, which is TKL's own choice."""
        found = []
        for route in self.routes:
            train = self._train(route.train)
            if train is None or route.way.kind != RouteKind.TRAIN or route.at >= route.way.last:
                continue
            name, _ = route.way.sections[-1]
            found.append(self._number(train, TklNumberColour.GREEN, name, None, route.id))
        return found

    def _number(
        self,
        train: _Train,
        colour: TklNumberColour,
        section: str | None,
        exit: str | None,
        route: int | None,
    ) -> TklNumber:
        plant = self.plant
        if section is not None:
            pieces = list(plant.sections[section].pieces)
        else:
            pieces = list(plant.exits[exit].pieces) if exit in plant.exits else []
        return TklNumber(
            number=train.number,
            train=train.id,
            colour=colour,
            section=section,
            exit=exit,
            pieces=pieces,
            track=plant.track_of.get(section) if section is not None else None,
            route=route,
            estimated=self.field is None,
        )

    def shown_route(self, route_id: int) -> TklSetRoute | None:
        """One set route as the panel shows it, or None when it is no longer set (Prova)."""
        route = self._route(route_id)
        return self._shown(route) if route is not None else None

    def view(self) -> TklInterlocking:
        """Ställverkets läge: everything the panel draws (STV-08)."""
        plant = self.plant
        if self._saved is not None:
            return self._saved.model_copy(
                update={"problem": self.problem, "revision": self.revision, "events": self.events}
            )
        locks = self._locks()
        local = {p: f.name for f in self._active(LOCAL) for p in f.switches}
        guarded = {p: f.name for f in self._active(LOCAL) for p in f.locked_parts}
        level_3 = self.level == 3
        field_ = self.field
        switches = {}
        for part, control in plant.control.items():
            holders = [r for r, _ in locks.parts.get(part, [])]
            switches[part] = TklSwitchShown(
                position=self.positions.get(part) if control == SwitchControl.TKL else None,
                control=control,
                routes=sorted(r.id for r in holders),
                protection=any(part in r.way.protection for r in holders) or part in guarded,
                local=part in local,
                function=local.get(part) or guarded.get(part),
                state=self._state(ObjectKind.SWITCH, part) if level_3 else None,
                reported=field_.switches.get(part) if field_ is not None else None,
            )
        ends = {r.way.end for r in self.routes}
        blocked = {s for f in self._active(STOP) for s in f.signals}
        blocked |= {s for f in self._active(LOCAL) for s in f.blocked}
        showing = self._aspects(locks)
        signals = {}
        for name in plant.signals:
            signals[name] = TklSignalShown(
                aspect=showing[name],
                end=name in ends,
                blocked=name in blocked,
                state=self._state(ObjectKind.SIGNAL, name) if level_3 else None,
                reported=field_.signals.get(name) if field_ is not None else None,
            )
        pieces: dict[str, TklPieceShown] = {}
        for route in self.routes:
            state = (
                TklPieceState.TRAIN if route.way.kind == RouteKind.TRAIN else TklPieceState.SHUNTING
            )
            for _, piece in route.locked_pieces():
                pieces.setdefault(piece, TklPieceShown(state=state, route=route.id))
        numbers = []
        for train in self.trains:
            inside = self._route_of_train(train)
            numbers.append(
                self._number(
                    train,
                    TklNumberColour.RED,
                    train.section,
                    train.exit,
                    inside.id if inside else None,
                )
            )
            on = plant.sections[train.section].pieces if train.section else ()
            if train.exit in plant.exits:
                on = plant.exits[train.exit].pieces
            for piece in on:
                route_id = pieces[piece].route if piece in pieces else None
                pieces[piece] = TklPieceShown(state=TklPieceState.OCCUPIED, route=route_id)
        if field_ is not None:
            with_number = {t.section for t in self.trains}
            for name, occupied in field_.sections.items():
                if occupied and name not in with_number and name in plant.sections:
                    for piece in plant.sections[name].pieces:
                        route_id = pieces[piece].route if piece in pieces else None
                        pieces[piece] = TklPieceShown(state=TklPieceState.OCCUPIED, route=route_id)
        shown_as = {
            LOCAL: TklPieceState.LOCAL,
            OUT: TklPieceState.OUT_OF_SERVICE,
            PROGRAMMING: TklPieceState.PROGRAMMING,
        }
        for function in self._active(LOCAL, OUT, PROGRAMMING):
            for piece in function.pieces:
                pieces.setdefault(piece, TklPieceShown(state=shown_as[function.type]))
        aspects = self.exit_aspects()
        return TklInterlocking(
            station_id=plant.model.station_id,
            level=plant.model.level,
            model=plant.fingerprint,
            revision=self.revision,
            problem=self.problem,
            switches=switches,
            levers={
                lever: plant.lever_side(lever, self.positions) for lever in plant.levers.levers
            },
            turntables=dict(self.turntables),
            routes=[self._shown(r) for r in self.routes],
            trains=[
                TklTrain(id=t.id, number=t.number, call=t.call, section=t.section, exit=t.exit)
                for t in self.trains
            ],
            signals=signals,
            pieces=pieces,
            numbers=[*numbers, *self.green_numbers()],
            exits=[
                TklExitShown(
                    exit=place.id,
                    outside=place.outside,
                    pieces=list(place.pieces),
                    aspect=aspects[place.id],
                )
                for place in plant.exits.values()
            ],
            tracks=dict(plant.track_of),
            sections={name: list(section.pieces) for name, section in plant.sections.items()},
            functions=[self._function_shown(f) for f in plant.functions.values()],
            events=list(self.events),
            last_id=self.last_id,
            field=field_.shown() if field_ is not None else None,
        )

    def _aspects(self, locks: _Locks | None = None) -> dict[str, TklAspect]:
        """What every signal shows now: a route's aspect, shunting in a locally released area,
        else stop."""
        found = locks if locks is not None else self._locks()
        shunting = {s for f in self._active(LOCAL) for s in f.signals}
        aspects = {}
        for name, signal in self.plant.signals.items():
            holder = found.showing.get(name)
            aspect = holder.showing()[name] if holder is not None else TklAspect.STOP
            if aspect == TklAspect.STOP and name in shunting and signal.type in DWARFS:
                aspect = TklAspect.LOCAL
            aspects[name] = aspect
        return aspects

    def _function_shown(self, function: Function) -> TklFunctionShown:
        if function.type == TURNTABLE:
            mode = self.turntables.get(function.turntable or "")
        else:
            mode = self.modes.get(function.name)
        return TklFunctionShown(
            name=function.name,
            type=function.type,
            on=self.on.get(function.name, False),
            mode=mode,
            modes=[TklFunctionMode(value=v, label=label) for v, label in function.modes],
            pieces=list(function.pieces),
            signals=list(function.signals),
            blocked=list(function.blocked),
            switches=list(function.switches),
            locked=dict(function.locked),
            at=function.turntable or function.at,
            codes=dict(function.codes),
            note=function.note,
        )

    def _shown(self, route: _Route) -> TklSetRoute:
        way = route.way
        return TklSetRoute(
            id=route.id,
            kind=ShownKind(way.kind.value),
            start=way.start,
            end=way.end,
            chain=route.chain,
            sections=[
                TklSectionPart(section=name, pieces=list(pieces), released=route.released[i])
                for i, (name, pieces) in enumerate(way.sections)
            ],
            positions=dict(way.route.positions),
            locked=route.locked_parts(),
            protection=sorted(way.protection),
            crossings=route.crossings(),
            turntable=table[1] if (table := route.turntable()) is not None else None,
            train=route.train,
            at=route.at,
            aspect=route.aspect(),
            held=route.held,
            passed=route.passed_showing(),
            leaves=way.leaves,
            enters=way.enters,
            set_at=route.set_at,
            waiting=sorted(route.waiting),
            waiting_since=route.waiting_since,
            came_from=route.came_from,
        )

    # --- a saved state ------------------------------------------------------------------------

    def _restore(self, saved: TklInterlocking) -> None:
        """The saved state, when it belongs to this model; else it is kept as it was and
        everything but a reset is refused (fails closed)."""
        plant = self.plant
        self.revision = saved.revision
        self.last_id = saved.last_id
        self.events = list(saved.events)
        if saved.model != plant.fingerprint:
            self._stale(saved)
            return
        for part, switch in saved.switches.items():
            if part not in plant.control:
                self._stale(saved)
                return
            if switch.position is not None and plant.control[part] == SwitchControl.TKL:
                self.positions[part] = switch.position
        for table, piece in saved.turntables.items():
            if table in self.turntables:
                self.turntables[table] = piece
        for shown_function in saved.functions:
            found = plant.functions.get(shown_function.name)
            if found is None or found.type != shown_function.type:
                self._stale(saved)
                return
            self.on[found.name] = shown_function.on and found.type in SWITCHED
            if found.type == TRACTION and shown_function.mode in dict(found.modes):
                self.modes[found.name] = shown_function.mode or ""
        trains: list[_Train] = []
        for train in saved.trains:
            if (train.section is not None and train.section not in plant.sections) or (
                train.exit is not None and train.exit not in plant.exits
            ):
                self._stale(saved)
                return
            trains.append(_Train(train.id, train.number, train.call, train.section, train.exit))
        known = {t.id for t in trains}
        routes: list[_Route] = []
        for shown in saved.routes:
            pieces = [p for s in shown.sections for p in s.pieces]
            way = plant.find_way(RouteKind(shown.kind.value), shown.start, shown.end, pieces)
            names = [s.section for s in shown.sections]
            if way is None or names != [name for name, _ in way.sections]:
                self._stale(saved)
                return
            positions = way.route.positions
            routes.append(
                _Route(
                    id=shown.id,
                    way=way,
                    chain=shown.chain,
                    released=[s.released for s in shown.sections],
                    set_at=shown.set_at,
                    train=shown.train if shown.train in known else None,
                    at=min(shown.at, way.last),
                    held=shown.held,
                    waiting={p: positions[p] for p in shown.waiting if p in positions},
                    waiting_since=shown.waiting_since,
                    came_from=shown.came_from if shown.came_from in plant.sections else None,
                )
            )
        self.trains, self.routes = trains, routes
        if saved.field is not None and self.level == 3:
            kept = saved.field
            self.field = _Field(
                mode=kept.mode,
                since=kept.since,
                switches={p: kept.switches.get(p) for p in self._laid()},
                sections={n: kept.sections.get(n) for n in self._circuits()},
                signals={n: a for n, a in kept.signals.items() if n in plant.signals},
                ordered_switches=dict(kept.ordered_switches),
                ordered_signals=dict(kept.ordered_signals),
            )

    def _stale(self, saved: TklInterlocking) -> None:
        self.problem = STALE
        self._saved = saved


def load(
    plant: Plant,
    revision: int,
    body: str | None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Interlocking:
    """The interlocking from its saved state; a fresh one without. A saved state that cannot
    be read fails closed: everything but a reset is refused."""
    if body is None:
        made = Interlocking(plant, now=now)
        made.revision = revision
        return made
    try:
        saved = TklInterlocking.model_validate_json(body)
    except ValueError:
        made = Interlocking(plant, now=now)
        made.revision = revision
        made.problem = BROKEN
        return made
    return Interlocking(plant, saved, now=now)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _listed(names: Iterable[str]) -> str:
    """Names as Swedish lists them: 21, 23 och 31."""
    found = list(names)
    if len(found) < 2:
        return "".join(found)
    return f"{', '.join(found[:-1])} och {found[-1]}"


def _held_said(route: _Route) -> str:
    return (
        f"Vägen {route.name} står i stopp ({route.held}). Lägg den på nytt när {route.held} är av."
    )


def _unknown_point(plant: Plant, name: str) -> str:
    if name in plant.signals:
        return f"Inga vägar börjar eller slutar vid signalen {name}."
    return f"{name} finns inte bland stationens signaler och vägar."
