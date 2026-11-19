"""Ställverket at level 1–2 (#84): the interlocking's state machine over one station model.

Fjärrstyrning (#36 del b): while the station is remote-controlled, its own panel, its Stream Deck
and its answers to the parts lay nothing (FR6, FR17): set_route, release, emergency_release,
lay_lever, reset, part_reply and the functions say who controls it, except the local area, which
is given back on the spot and whose switches are laid with the modules' buttons (FR21, FR44).
The routes asked for from afar and those the station automats lay go through the same checks,
with lay_route and free_route (tkl.stallverk.automats, FR12). Every set route remembers the
catalogue route it is, who laid it and the request it answered (FR13, FR33). While a local area
is released, a train route may still start at one of its signals and go out of it, from the
border, without touching it (FR22); none goes into it (FR42).

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
    no route touches the area, except a train route out of it from one of its signals that
    touches nothing else of it (FR22, #36 del b). It is refused while a route touches the area.
    Taking it back is always allowed, as in the prototype: the local switches stay where they
    lie.
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

Delställverk (#87, TKL97–TKL103): a station may have parts, each a fixed area with its own
operator. The interlocking is still one, and locks every route; a part is a role with an area
against it (tkl.stallverk.parts). What a part may do:

- set and release shunting routes inside its area, and lay its own switches, with the same
  locking as the station's (part_route, part_release, part_lever);
- lay a border switch towards its area, never out (RANG-12, TKL99): a route out over the border
  is a request. The side that owns a border switch lays it both ways;
- lay a switch street, every switch of it or none (RANG-02, part_street);
- Klart and Grindar lay the border switches back towards the area; Klart also returns every
  request (RANG-04, RANG-12).

The five messages between a part and the station (TKL98): begär väg (part_request), svar
(part_reply), lämna tillbaka (part_return), klart att skicka (part_ready) and ring (part_ring).
A request that cannot go now is refused at once with the reason, and nothing reaches the
station (RANG-10). On approval the station's interlocking sets the route, which is then the
part's: the part can only return it, never set it itself, and the station cannot release it
while it is the part's (envägsregeln, RANG-09); nödutlösning still can, confirmed and logged.
A waiting request that a route set since has made impossible is answered no, with the reason
(ported from cda-tkl's YardControl.tick). Every message is written in the events with who did it
(RANG-05) and handed on with the outcome: locally that is all; when the station is
remote-controlled the station's TKL sends them through Hubben (TKL100, #36). The trains announced
ready to send are a list for the station, by the planned departure, which the station may move
and mark Skickat (TKL108).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from contracts.station import ExitSignalAspect, RouteBy
from contracts.station_model import PanelFunctionType, PartOwner, Position, SwitchControl
from contracts.tkl import (
    PART_REFUSALS,
    AddressState,
    ObjectKind,
    TklAspect,
    TklExitShown,
    TklField,
    TklFieldMode,
    TklFjarrState,
    TklFunctionAction,
    TklFunctionMode,
    TklFunctionShown,
    TklHappening,
    TklInterlocking,
    TklNumber,
    TklNumberColour,
    TklPartMessage,
    TklPartMessageKind,
    TklPartRefusal,
    TklPartRequest,
    TklPartRequestState,
    TklPartRouteOut,
    TklPartShown,
    TklPartStreet,
    TklPieceShown,
    TklPieceState,
    TklReady,
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
from tkl.stallverk.parts import Part, owner_of
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
STATION_BY: Final = "Tågklareraren"
"""Who the station is in the events (RANG-05): whoever runs its interlocking."""
WAITING, APPROVED = TklPartRequestState.WAITING, TklPartRequestState.APPROVED
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
    messages: tuple[TklPartMessage, ...] = ()
    """The messages between a part and the station (TKL98), to hand on (TKL100)."""


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
    part: str | None = None
    """The part the route is: set by it, or its approved request (TKL97)."""
    request: int | None = None
    """The request it was set for: the one-way rule holds it for the part (RANG-09)."""
    catalogue: str | None = None
    """The remote catalogue's route it is, when it is one (#36 del b)."""
    by: RouteBy | None = None
    """Laid from afar or by a station automat; None on the spot (FR33)."""
    request_id: str | None = None
    """The remote request it answered."""
    automat: str | None = None
    """The station automat that laid it."""

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
class _Request:
    """Begäran (TKL98): a route out a part has asked for, waiting or approved."""

    id: int
    part: str
    route_out: str
    said: str
    state: TklPartRequestState
    asked: datetime
    route: int | None = None
    answered: datetime | None = None


@dataclass
class _PartState:
    """A part's state of the moment: its requests, its ring, Fika and what it was refused."""

    requests: list[_Request] = field(default_factory=list)
    rings: datetime | None = None
    fika: bool = False
    refused: list[TklPartRefusal] = field(default_factory=list)


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
        self.parts: dict[str, _PartState] = {p: _PartState() for p in plant.parts}
        self.ready: list[TklReady] = []
        self.fjarr = TklFjarrState()
        """Who remote-controls the station, the automats that are on and the magazine (#36)."""
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

    def _log(self, text: str, by: str | None = None) -> None:
        self.events.insert(0, TklHappening(at=self.now(), text=text, by=by))
        del self.events[KEPT_EVENTS:]

    def note(self, text: str) -> None:
        """A line in the events that changes nothing else, such as how a report went."""
        self.revision += 1
        self._log(text)

    def _done(
        self, message: str, *, route: int | None = None, log: bool = True, by: str | None = None
    ) -> Outcome:
        self.revision += 1
        if log:
            self._log(message, by)
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
            if function.touches(way) and not _from_border(function, way):
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

    def _plan(
        self, chain: Chain, routes: Iterable[_Route] | None = None
    ) -> tuple[list[_Route], str | None]:
        """The chain as routes on top of the set ones (or only `routes`), or why it cannot be
        set."""
        locks = self._locks(routes)
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

    # --- fjärrstyrning (#36 del b): what the remote module asks of the interlocking -----------

    def conflicts(self, start: str, end: str, kind: RouteKind = RouteKind.TRAIN) -> list[int]:
        """The set routes that alone stop a route from start to end: what it would wait for
        in the magazine (FR45). Empty when nothing stops it, or when something besides set
        routes does, such as a train in the way or a local area."""
        for chain in self.plant.candidates(kind, start, end):
            if self._border_for_station(chain) is not None:
                continue
            if self._plan(chain, [])[1] is not None:
                continue
            found = [r.id for r in self.routes if self._plan(chain, [r])[1] is not None]
            if found:
                return found
        return []

    def set_by(self, start: str, end: str, kind: RouteKind = RouteKind.TRAIN) -> int | None:
        """The set route, or the first part of the set chain, from start to end."""
        found = self._already(kind, start, end)
        return found.id if found is not None else None

    def mark(
        self,
        route_id: int,
        catalogue: str,
        by: RouteBy | None,
        request_id: str | None = None,
        automat: str | None = None,
    ) -> None:
        """The set route, with the rest of its chain, is the catalogue's route, laid by the
        controller, an automat or on the spot (#36 del b, FR13, FR33)."""
        first = self._route(route_id)
        if first is None:
            return
        parts = [r for r in self.routes if r.chain == first.id] or [first]
        for route in parts:
            route.catalogue, route.by = catalogue, by
            route.request_id, route.automat = request_id, automat
        self.revision += 1

    def switch_local(self, name: str, on: bool, *, empty: bool = False) -> Outcome:
        """A local area switched in or out for whoever controls the station (FR20, FR42); with
        `empty`, out only when no train is in it (FR23)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        function = self.plant.functions.get(name)
        if function is None or function.type != LOCAL:
            return Outcome(False, f"Panelfunktionen {name} är ingen lokal frigivning.")
        if not on and empty and self.on.get(name):
            inside = [t.said for t in self.trains if t.section in function.sections]
            if self.field is not None:
                inside += [
                    self.plant.said(n)
                    for n in sorted(function.sections)
                    if self.field.sections.get(n)
                ]
            if inside:
                return Outcome(False, f"{_cap(name)} är inte tomt: {_listed(inside)}.")
        return self._switch(function, on)

    def area_tracks(self, name: str) -> list[str]:
        """The station tracks in a local area, by their id in the outside (FR39)."""
        function = self.plant.functions.get(name)
        if function is None:
            return []
        pieces = set(function.pieces)
        return [
            self.plant.track_outside.get(t.id, t.id)
            for t in self.plant.model.station_tracks
            if t.pieces and set(t.pieces) <= pieces
        ]

    def occupied_tracks(self) -> list[str]:
        """Level 3 with LocoNet: the station tracks a track circuit reports occupied, by their
        id in the outside."""
        if self.field is None:
            return []
        found = []
        section_of = self.plant.section_of
        for track in self.plant.model.station_tracks:
            sections = {section_of[p] for p in track.pieces if p in section_of}
            if any(self.field.sections.get(n) for n in sections):
                found.append(self.plant.track_outside.get(track.id, track.id))
        return found

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

    def remote_refusal(self) -> Outcome | None:
        """While the station is remote-controlled its own panel lays nothing (FR6, FR17)."""
        controller = self.fjarr.controller
        if controller is None:
            return None
        return Outcome(
            False,
            f"Stationen fjärrstyrs från {controller}. Den som fjärrstyr lägger vägarna; ta "
            "tillbaka stationen för att lägga dem här.",
        )

    def set_remote(self, controller: str | None) -> bool:
        """Who remote-controls the station now, as Hubben says it; True when it changed."""
        if self.fjarr.controller == controller:
            return False
        self.fjarr = self.fjarr.model_copy(update={"controller": controller})
        if controller is None:
            self._done("Stationen är bemannad.")
        else:
            self._done(f"Stationen fjärrstyrs från {controller}.")
        return True

    def set_route(self, start: str, end: str, kind: RouteKind | None = None) -> Outcome:
        """Lägg en väg (STV-01, STV-03, STV-14, STV-24), on the spot."""
        if (remote := self.remote_refusal()) is not None:
            return remote
        return self.lay_route(start, end, kind)

    def lay_route(self, start: str, end: str, kind: RouteKind | None = None) -> Outcome:
        """The interlocking's own check for a route, whoever asks for it: the panel, a remote
        request or a station automat (FR12)."""
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
            why = self._border_for_station(chain)
            planned: list[_Route] = []
            if why is None:
                planned, why = self._plan(chain)
            if why is None:
                return self._answer_waiting(self._lay(chain, planned))
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

    def _lay(
        self,
        chain: Chain,
        planned: list[_Route],
        *,
        part: str | None = None,
        request: int | None = None,
        by: str | None = None,
        intro: str = "",
    ) -> Outcome:
        before = self.exit_aspects()
        starting = self._at_start(chain[0])
        for route in planned:
            route.id = self._next_id()
            route.chain = planned[0].id if len(planned) > 1 else None
            route.part, route.request = part, request
            if len(starting) == 1:
                route.train = starting[0].id
            for switch, position in route.way.route.positions.items():
                if self.plant.control.get(switch) == SwitchControl.TKL:
                    self.positions[switch] = position
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
        outcome = self._done(f"{intro}{said}.", route=first.id, by=by)
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
        if (remote := self.remote_refusal()) is not None:
            return remote
        return self.free_route(route_id)

    def free_route(self, route_id: int) -> Outcome:
        """Lös ut, whoever asks: also a route taken away from afar (route.cancel), released when
        the interlocking allows."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre. Ingenting löstes ut.")
        held = self._held_for_part(route)
        if held is not None:
            return Outcome(False, held)
        busy = self._train_in(route)
        if busy is not None:
            return Outcome(False, busy)
        before = self.exit_aspects()
        self._complete(route)
        outcome = self._done(f"Vägen {route.name} är utlöst.")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def _train_in(self, route: _Route) -> str | None:
        """Why a route cannot be released now: a train is in it, short of its end."""
        if 0 <= route.at < route.way.last:
            train = self._train(route.train)
            who = train.said if train else "Tåget"
            return f"{who} är i vägen {route.name}. Kör fram tåget, eller nödutlös vägen."
        return None

    def _held_for_part(self, route: _Route) -> str | None:
        """Envägsregeln (RANG-09): a part's approved request is the part's until it returns
        it; the station does not release it. Nödutlösning still can."""
        if route.request is None or route.part not in self.plant.parts:
            return None
        part = self.plant.parts[route.part]
        if not part.rules.one_way:
            return None
        return (
            f"Vägen {route.name} är {_genitive(part.name)} godkända begäran. {part.name} lämnar "
            "tillbaka den (envägsregeln, RANG-09). Nödutlös den om det behövs."
        )

    def emergency_release(self, route_id: int, confirm: bool) -> Outcome:
        """Nödutlös: the route goes even with a train in it. The train stays where it is."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        if (remote := self.remote_refusal()) is not None:
            return remote
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
        if (remote := self.remote_refusal()) is not None:
            return remote
        return self._lever(switch, position, None)

    def _lever(self, switch: str, position: Position | None, part: Part | None) -> Outcome:
        """A lever laid by the station, or by a part within its rights (TKL99)."""
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
        wanted = lever.plus if side == Position.PLUS else lever.minus
        own = set(lever.plus) & set(lever.minus)
        refused = self._lever_rights(own, wanted, part)
        if refused is not None:
            return Outcome(False, refused)
        laid = plant.levers.lay(dict(wanted))
        if laid is None:
            return Outcome(
                False,
                f"Spaken {lever_id} kan inte läggas i {sign(side)}: den behöver en växel åt "
                "båda hållen.",
            )
        moving = {p: v for p, v in laid.positions.items() if self.positions.get(p) != v}
        why = self._may_move(moving, own)
        if why is not None:
            return Outcome(False, why)
        if not moving:
            return Outcome(True, f"Spaken {lever_id} ligger redan i {sign(side)}.")
        self.positions.update(moving)
        dragged = [f"{p} {sign(v)}" for p, v in sorted(moving.items()) if p not in own]
        said = f"Spaken {lever_id} lagd i {sign(side)}"
        if dragged:
            said += f", drar med {', '.join(dragged)}"
        return self._done(said + ".", by=part.name if part is not None else None)

    def _lever_rights(
        self, own: set[str], wanted: dict[str, Position], part: Part | None
    ) -> str | None:
        """Who may lay a lever where (TKL99, RANG-12). The station: everything but a border
        switch a part owns, which it lays only towards the part. A part: its own switches, and
        a border switch towards its area, with the station's half of the same lever."""
        if part is None:
            for name in sorted(own):
                found = owner_of(self.plant.parts.values(), name)
                if found is None or found[1].owner != PartOwner.PART:
                    continue
                at, border = found
                if wanted.get(name) != border.towards_part:
                    return (
                        f"Växel {name} är en gränsväxel och styrs av {at.name}. Stationen lägger "
                        f"den bara mot {_genitive(at.name)} område ({sign(border.towards_part)})."
                    )
            return None
        with_border = any(name in part.border for name in own)
        for name in sorted(own):
            if name in part.border:
                why = self._border_why(part, name, wanted[name])
                if why is not None:
                    return why
            elif name not in part.own and not with_border:
                return _not_parts(part, name)
        return None

    def _border_why(self, part: Part, name: str, position: Position) -> str | None:
        """Why a part may not lay a border switch in a position, or None (RANG-12)."""
        if part.may_lay(name, position):
            return None
        border = part.border[name]
        if position == border.towards_part:
            return f"Växel {name} är en gränsväxel och läggs av stationen."
        return (
            f"Växel {name} är en gränsväxel: {part.name} lägger den bara mot sitt område "
            f"({sign(border.towards_part)}). Ut går den bara med en begäran som stationen "
            "godkänner (RANG-12)."
        )

    def _may_move(self, moving: dict[str, Position], own: set[str]) -> str | None:
        """Why these switches cannot be laid over now, or None: a switch the interlocking does
        not lay, at level 3 one that may not run, one locked in a route or by a local release,
        one that is locally released, or one under a train."""
        plant = self.plant
        locks = self._locks()
        occupied = self._occupied()
        for part in sorted(moving, key=lambda p: (p not in own, p)):
            control = plant.control.get(part)
            if control is None:
                return f"Växel {part} finns inte i stationsmodellen."
            if control != SwitchControl.TKL:
                return not_laid(part, control)
            if self.field is not None:
                why = self._refused_state(ObjectKind.SWITCH, part)
                if why is not None:
                    return why
            held = locks.parts.get(part)
            if held:
                follow = "" if part in own else " och kan inte följa med"
                return f"Växel {part} är låst i vägen {held[0][0].name}{follow}."
            for function in self._active(LOCAL):
                if part in function.locked_parts:
                    return f"Växel {part} är låst av {function.name}."
                if part in function.switches:
                    return (
                        f"Växel {part} är lokalt frigiven ({function.name}) och läggs om med "
                        "knappen på modulen."
                    )
            under = self._under_train(part, occupied)
            if under is not None:
                return f"Växel {part} kan inte läggas om: {plant.said(under)} är belagd."
        return None

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
        if self.problem is None and (remote := self.remote_refusal()) is not None:
            return remote
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
        self._drop_spent()
        self.fjarr = self.fjarr.model_copy(update={"magazine": []})
        removed = len(self.trains) if trains else 0
        if trains:
            self.trains = []
        said = f"Ställverket nollställt: {released} vägar utlösta"
        if removed or stale:
            said += ", tågnumren borttagna"
        outcome = self._done(said + ".")
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    # --- delställverk (#87, TKL97–TKL103): what a part does, and the station's answers --------

    def _part_of(self, part_id: str) -> tuple[Part | None, Outcome | None]:
        """The part, or why nothing is done for it: a stale state, an unknown part, or Fika."""
        if (stale := self._refuse_stale()) is not None:
            return None, stale
        part = self.plant.parts.get(part_id)
        if part is None:
            return None, Outcome(False, f"Delställverket {part_id} finns inte i stationsmodellen.")
        if self.parts[part.id].fika:
            return None, Outcome(False, f"{part.name} har fika. Tryck Tillbaka först.")
        return part, None

    def _part_no(self, part: Part, text: str) -> Outcome:
        """A no to the part, kept with it so that every screen of the part shows what was refused
        and why. Nothing goes to the station."""
        state = self.parts[part.id]
        state.refused.insert(0, TklPartRefusal(at=self.now(), text=text))
        del state.refused[PART_REFUSALS:]
        self.revision += 1
        return Outcome(False, text)

    def _message(
        self, kind: TklPartMessageKind, part: Part, text: str, **more: object
    ) -> TklPartMessage:
        return TklPartMessage.model_validate(
            {"kind": kind, "part": part.id, "at": self.now(), "text": text, **more}
        )

    def part_route(self, part_id: str, start: str, end: str) -> Outcome:
        """Lägg en växlingsväg inside the part's area, with the same locking as the station's.
        A border switch it lays goes towards the area (RANG-12); a route over the border is a
        request."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        plant = self.plant
        for name in (start, end):
            if name not in plant.points:
                return self._part_no(part, _unknown_point(plant, name))
        if start == end:
            return Outcome(False, "Start och mål är samma.")
        found = plant.candidates(RouteKind.SHUNTING, start, end)
        if not found:
            return self._part_no(part, f"Ingen växlingsväg går från {start} till {end}.")
        already = self._already(RouteKind.SHUNTING, start, end)
        if already is not None:
            return self._again(RouteKind.SHUNTING, already)
        reasons: list[str] = []
        for chain in found:
            why = self._part_hindrance(part, chain)
            planned: list[_Route] = []
            if why is None:
                planned, why = self._plan(chain)
            if why is None:
                laid = self._lay(chain, planned, part=part.id, by=part.name)
                return self._answer_waiting(laid)
            reasons.append(why)
        return self._part_no(part, reasons[0])

    def _part_hindrance(self, part: Part, chain: Chain) -> str | None:
        """Why a part may not set a chain itself, or None: it leaves the area, or lays a switch
        the part may not lay there (TKL99, RANG-12)."""
        for way in chain:
            for name, _ in way.sections:
                if name not in part.sections:
                    return (
                        f"{_cap(self.plant.said(name))} är utanför {part.name}. En väg ut över "
                        "gränsen begärs av stationen."
                    )
            for switch, position in way.route.positions.items():
                if switch in part.border:
                    why = self._border_why(part, switch, position)
                    if why is not None:
                        return why
                elif switch not in part.own and switch in way.route.switches:
                    return _not_parts(part, switch)
        return None

    def _border_for_station(self, chain: Chain) -> str | None:
        """A border switch a part owns: the station's own routes lay it only towards the
        part (TKL99)."""
        for way in chain:
            for switch, position in way.route.positions.items():
                found = owner_of(self.plant.parts.values(), switch)
                if found is None or found[1].owner != PartOwner.PART:
                    continue
                at, border = found
                if position != border.towards_part:
                    return (
                        f"Växel {switch} är en gränsväxel och styrs av {at.name}. Vägen dit "
                        f"begärs av {at.name}."
                    )
        return None

    def part_release(self, part_id: str, route_id: int) -> Outcome:
        """Lös ut one of the part's own routes. Its approved request is returned instead."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre. Ingenting löstes ut.")
        if route.part != part.id:
            return self._part_no(
                part,
                f"Vägen {route.name} är stationens. {part.name} löser bara ut sina egna vägar.",
            )
        if route.request is not None:
            return self.part_return(part.id, route.request)
        busy = self._train_in(route)
        if busy is not None:
            return self._part_no(part, busy)
        before = self.exit_aspects()
        self._complete(route)
        outcome = self._done(f"Vägen {route.name} är utlöst.", by=part.name)
        return Outcome(True, outcome.message, None, self._exit_reports(before))

    def part_lever(self, part_id: str, switch: str, position: Position | None = None) -> Outcome:
        """A switch laid by the part: its own, or a border switch towards its area, never out
        (RANG-12). The station's own switches are not the part's (RANG-19)."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        outcome = self._lever(switch, position, part)
        return outcome if outcome.accepted else self._part_no(part, outcome.message)

    def _street_plan(self, part: Part, street_id: str) -> tuple[dict[str, Position], str | None]:
        """What a switch street lays over, every switch of it and those its levers take along,
        or why it cannot be laid now (RANG-02). A switch in a locked route refuses the whole
        street."""
        street = part.streets.get(street_id)
        if street is None:
            return {}, f"{part.name} har ingen växelgata {street_id}."
        plant = self.plant
        moving: dict[str, Position] = {}
        own: set[str] = set()
        for switch, position in street.positions.items():
            if switch in part.border:
                why = self._border_why(part, switch, position)
                if why is not None:
                    return {}, why
            elif switch not in part.own:
                return {}, _not_parts(part, switch)
            lever_id, why = plant.lever_of(switch)
            if lever_id is None:
                return {}, why or f"Växel {switch} finns inte i stationsmodellen."
            lever = plant.levers.levers[lever_id]
            side = Position.PLUS if lever.plus.get(switch) == position else Position.MINUS
            wanted = lever.plus if side == Position.PLUS else lever.minus
            laid = plant.levers.lay(dict(wanted)) if wanted.get(switch) == position else None
            if laid is None:
                return {}, f"Växel {switch} kan inte läggas i {sign(position)}."
            own |= set(lever.plus) & set(lever.minus)
            for name, value in laid.positions.items():
                if moving.get(name, value) != value or street.positions.get(name, value) != value:
                    return {}, f"Växelgatan {street.name} lägger växel {name} åt två håll."
                moving[name] = value
        moving = {p: v for p, v in moving.items() if self.positions.get(p) != v}
        return moving, self._may_move(moving, own)

    def part_street(self, part_id: str, street_id: str) -> Outcome:
        """Lägg en växelgata (RANG-02): the part's switches straight out to a track, without a
        route, a lock or a signal. All of it or nothing."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        moving, why = self._street_plan(part, street_id)
        street = part.streets.get(street_id)
        if why is not None or street is None:
            said = f"Växelgatan {street.name}: {why}" if street is not None else why
            return self._part_no(part, said or "")
        if not moving:
            return Outcome(True, f"Växelgatan {street.name} ligger redan.")
        self.positions.update(moving)
        laid = ", ".join(f"{p} {sign(v)}" for p, v in street.positions.items())
        return self._done(
            f"Växelgatan {street.name} lagd mot {street.track}: {laid}.", by=part.name
        )

    def _street_laid(self, street_positions: dict[str, Position]) -> bool:
        return all(self.positions.get(p) == v for p, v in street_positions.items())

    def _out_hindrance(self, part: Part, route_out: str) -> str | None:
        """Why a route out cannot be set now, or None: what the station would meet."""
        out = part.routes_out.get(route_out)
        if out is None:
            return f"{part.name} har ingen väg ut {route_out}."
        chains = self.plant.candidates(RouteKind.SHUNTING, out.start, out.end)
        if not chains:
            return f"Ingen växlingsväg går från {out.start} till {out.end}."
        if self._already(RouteKind.SHUNTING, out.start, out.end) is not None:
            return f"Vägen {out.start} → {out.end} ligger redan."
        _, why = self._settable(chains, None)
        return why

    def part_request(self, part_id: str, route_out: str) -> Outcome:
        """Begär väg (TKL98): a route out over the border. When it cannot go now the
        interlocking says so at once, and nothing reaches the station (RANG-10)."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        out = part.routes_out.get(route_out)
        if out is None:
            return self._part_no(part, f"{part.name} har ingen väg ut {route_out}.")
        state = self.parts[part.id]
        for asked in state.requests:
            if asked.route_out == out.id:
                if asked.state == WAITING:
                    return Outcome(False, f"{asked.said} är redan begärd. Väntar på svar.")
                return Outcome(False, f"{asked.said} ligger redan. Lämna tillbaka den först.")
        why = self._out_hindrance(part, out.id)
        if why is not None:
            return self._part_no(part, f"Går inte att begära {out.name}: {why}")
        said = out.name
        if out.side is not None:
            coming = next(
                (
                    s.track
                    for s in part.streets.values()
                    if s.side == out.side and self._street_laid(s.positions)
                ),
                None,
            )
            if coming is not None:
                said = f"{coming} \N{RIGHTWARDS ARROW} {out.track}"
        asked = _Request(self._next_id(), part.id, out.id, said, WAITING, self.now())
        state.requests.append(asked)
        text = f"{part.name} begär {said} ({out.start} \N{RIGHTWARDS ARROW} {out.end})."
        self._done(text, by=part.name)
        message = self._message(
            TklPartMessageKind.REQUEST, part, text, request=asked.id, route_out=out.id
        )
        return Outcome(True, text, None, (), (message,))

    def _request(self, request_id: int) -> tuple[Part, _Request] | None:
        for part_id, state in self.parts.items():
            for asked in state.requests:
                if asked.id == request_id:
                    return self.plant.parts[part_id], asked
        return None

    def part_reply(self, request_id: int, approved: bool) -> Outcome:
        """Svar (TKL98): the station approves a request, and its interlocking sets the route,
        which is then the part's (RANG-09); or refuses it. A route that cannot be set now is a
        no to the station, and the request waits. While the station is remote-controlled the one
        who controls it answers instead (FR50)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        if (remote := self.remote_refusal()) is not None:
            return remote
        found = self._request(request_id)
        if found is None:
            return Outcome(False, "Begäran finns inte längre.")
        part, asked = found
        if asked.state != WAITING:
            return Outcome(False, f"{_genitive(part.name)} begäran {asked.said} är redan godkänd.")
        out = part.routes_out[asked.route_out]
        state = self.parts[part.id]
        if not approved:
            state.requests.remove(asked)
            text = f"{STATION_BY} nekade {_genitive(part.name)} begäran {asked.said}."
            self._part_no(part, text)
            self._log(text, STATION_BY)
            message = self._message(
                TklPartMessageKind.REPLY,
                part,
                text,
                request=asked.id,
                route_out=out.id,
                approved=False,
            )
            return Outcome(True, text, None, (), (message,))
        reasons: list[str] = []
        for chain in self.plant.candidates(RouteKind.SHUNTING, out.start, out.end):
            planned, why = self._plan(chain)
            if why is None:
                intro = f"{STATION_BY} godkände {_genitive(part.name)} begäran {asked.said}. "
                laid = self._lay(
                    chain, planned, part=part.id, request=asked.id, by=STATION_BY, intro=intro
                )
                asked.state, asked.route, asked.answered = APPROVED, laid.route, self.now()
                message = self._message(
                    TklPartMessageKind.REPLY,
                    part,
                    laid.message,
                    request=asked.id,
                    route_out=out.id,
                    approved=True,
                )
                return self._answer_waiting(
                    Outcome(True, laid.message, laid.route, laid.reports, (message,))
                )
            reasons.append(why)
        why = reasons[0] if reasons else "vägen finns inte i stationsmodellen."
        return Outcome(
            False,
            f"Vägen {out.start} \N{RIGHTWARDS ARROW} {out.end} kan inte läggas nu: {why} Neka "
            "begäran, eller godkänn den när vägen är fri.",
        )

    def _answer_waiting(self, outcome: Outcome) -> Outcome:
        """After a route is set: a waiting request it has made impossible is answered no, with
        the reason, so that the part learns at once (ported from cda-tkl's YardControl.tick)."""
        if not outcome.accepted:
            return outcome
        messages = list(outcome.messages)
        for part_id, state in self.parts.items():
            part = self.plant.parts[part_id]
            for asked in [r for r in state.requests if r.state == WAITING]:
                why = self._out_hindrance(part, asked.route_out)
                if why is None:
                    continue
                state.requests.remove(asked)
                text = f"{_genitive(part.name)} begäran {asked.said} kan inte läggas: {why}"
                self._part_no(part, text)
                self._log(text)
                messages.append(
                    self._message(
                        TklPartMessageKind.REPLY,
                        part,
                        text,
                        request=asked.id,
                        route_out=asked.route_out,
                        approved=False,
                    )
                )
        return Outcome(
            outcome.accepted, outcome.message, outcome.route, outcome.reports, tuple(messages)
        )

    def _give_back(self, part: Part, asked: _Request) -> str | None:
        """Lämna tillbaka one request: a waiting one is taken back; an approved one's routes are
        released and the border switches it laid out go back towards the part. Why not, or
        None."""
        routes = [r for r in self.routes if r.request == asked.id]
        for route in routes:
            busy = self._train_in(route)
            if busy is not None:
                return busy
        laid_out = {p for r in routes for p in r.way.route.positions if p in part.border}
        for route in routes:
            self._complete(route)
        state = self.parts[part.id]
        if asked in state.requests:
            state.requests.remove(asked)
        self._gates_back(part, laid_out)
        return None

    def part_return(self, part_id: str, request_id: int) -> Outcome:
        """Lämna tillbaka (TKL98): the part returns an approved route, and the station has its
        tracks free without doing anything; or takes back a request that waits."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        asked = next((r for r in self.parts[part.id].requests if r.id == request_id), None)
        if asked is None:
            return Outcome(False, "Begäran finns inte längre.")
        before = self.exit_aspects()
        waiting = asked.state == WAITING
        why = self._give_back(part, asked)
        if why is not None:
            return self._part_no(part, why)
        out = part.routes_out[asked.route_out]
        if waiting:
            text = f"{part.name} tog tillbaka sin begäran {asked.said}."
        else:
            text = (
                f"{part.name} lämnade tillbaka {asked.said} ({out.start} \N{RIGHTWARDS ARROW} "
                f"{out.end}). Gränsväxlarna ligger mot {part.name}."
            )
        self._done(text, by=part.name)
        message = self._message(
            TklPartMessageKind.RETURN, part, text, request=asked.id, route_out=out.id
        )
        return Outcome(True, text, None, self._exit_reports(before), (message,))

    def _gates_back(self, part: Part, only: set[str] | None = None) -> tuple[list[str], list[str]]:
        """The border switches back towards the part (TKL55): those that lie out, unless one
        lies in a locked route, which stays until the route is released. Laid and kept."""
        plant = self.plant
        laid: list[str] = []
        kept: list[str] = []
        for name, border in part.border.items():
            if only is not None and name not in only:
                continue
            if not part.may_lay(name, border.towards_part):
                continue
            if self.positions.get(name) == border.towards_part:
                continue
            lever_id, _ = plant.lever_of(name)
            if lever_id is None:
                continue
            lever = plant.levers.levers[lever_id]
            wanted = lever.plus if lever.plus.get(name) == border.towards_part else lever.minus
            done = plant.levers.lay(dict(wanted))
            if done is None or wanted.get(name) != border.towards_part:
                kept.append(name)
                continue
            moving = {p: v for p, v in done.positions.items() if self.positions.get(p) != v}
            if self._may_move(moving, set(lever.plus) & set(lever.minus)) is not None:
                kept.append(name)
                continue
            self.positions.update(moving)
            laid.append(f"{name} {sign(border.towards_part)}")
        return laid, kept

    def part_gates(self, part_id: str) -> Outcome:
        """Grindar: the border switches back towards the part, without returning anything
        (TKL55)."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        laid, kept = self._gates_back(part)
        if not laid and not kept:
            return Outcome(True, f"Gränsväxlarna ligger redan mot {part.name}.")
        return self._done(_gates_said(part, laid, kept), by=part.name)

    def part_done(self, part_id: str) -> Outcome:
        """Klart (RANG-04): every request returned, waiting or approved, and the border switches
        back towards the part. A route with a train in it stays."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        before = self.exit_aspects()
        state = self.parts[part.id]
        returned: list[str] = []
        stays: list[str] = []
        messages: list[TklPartMessage] = []
        for asked in list(state.requests):
            why = self._give_back(part, asked)
            if why is not None:
                stays.append(asked.said)
                continue
            returned.append(asked.said)
            messages.append(
                self._message(
                    TklPartMessageKind.RETURN,
                    part,
                    f"{part.name} lämnade tillbaka {asked.said}.",
                    request=asked.id,
                    route_out=asked.route_out,
                )
            )
        laid, kept = self._gates_back(part)
        text = f"{part.name}: klart. "
        text += f"{_listed(returned)} tillbaka." if returned else "Inga begärda vägar ute."
        if laid or kept:
            text += f" {_gates_said(part, laid, kept)}"
        if stays:
            text += f" {_listed(stays)} står kvar: ett tåg är i vägen."
        self._done(text, by=part.name)
        return Outcome(True, text, None, self._exit_reports(before), tuple(messages))

    def part_ring(self, part_id: str) -> Outcome:
        """Ring (TKL98): the part rings the station, until the station answers."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        state = self.parts[part.id]
        state.rings = state.rings or self.now()
        text = f"{part.name} ringer."
        self._done(text, by=part.name)
        return Outcome(True, text, None, (), (self._message(TklPartMessageKind.RING, part, text),))

    def part_ring_answer(self, part_id: str) -> Outcome:
        """The station answers the part's ring."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        part = self.plant.parts.get(part_id)
        if part is None:
            return Outcome(False, f"Delställverket {part_id} finns inte i stationsmodellen.")
        state = self.parts[part.id]
        if state.rings is None:
            return Outcome(True, f"{part.name} ringer inte.")
        state.rings = None
        return self._done(f"{STATION_BY} svarar {part.name}.", by=STATION_BY)

    def part_fika(self, part_id: str, on: bool) -> Outcome:
        """Fika: the part's screen is locked until it is back, and the station sees it. Only
        this part; TKL's lock for the whole station is Lås (SD30)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        part = self.plant.parts.get(part_id)
        if part is None:
            return Outcome(False, f"Delställverket {part_id} finns inte i stationsmodellen.")
        state = self.parts[part.id]
        if state.fika == on:
            return Outcome(True, f"{part.name} har {'redan fika' if on else 'inte fika'}.")
        state.fika = on
        said = f"{part.name} tar fika." if on else f"{part.name} är tillbaka från fikat."
        return self._done(said, by=part.name)

    def part_ready(
        self,
        part_id: str,
        number: str,
        *,
        call: str | None = None,
        track: str | None = None,
        departure: str | None = None,
    ) -> Outcome:
        """Klart att skicka (TKL108): a train by its number, in the station's list before the
        first with a later planned departure, else last. What has no planned time, a typed
        number, and what the station has moved stay where they are."""
        part, no = self._part_of(part_id)
        if part is None:
            return no or Outcome(False, "")
        if any(r.number == number for r in self.ready):
            return self._part_no(part, f"Tåg {number} är redan anmält klart att skicka.")
        entry = TklReady(
            number=number,
            part=part.id,
            part_name=part.name,
            track=track,
            departure=departure,
            call=call,
            at=self.now(),
        )
        at = next(
            (
                i
                for i, r in enumerate(self.ready)
                if departure and r.departure and r.departure > departure
            ),
            None,
        )
        self.ready.insert(len(self.ready) if at is None else at, entry)
        text = f"{part.name}: tåg {number} är klart att skicka"
        if track:
            text += f" från spår {track}"
        if departure:
            text += f", avgår {departure}"
        text += "."
        self._done(text, by=part.name)
        message = self._message(TklPartMessageKind.READY, part, text, number=number)
        return Outcome(True, text, None, (), (message,))

    def ready_move(self, number: str, to: int) -> Outcome:
        """Flytta i listan Klara att skicka: the station decides the order (TKL108)."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        at = next((i for i, r in enumerate(self.ready) if r.number == number), None)
        if at is None:
            return Outcome(False, f"Tåg {number} är inte anmält klart att skicka.")
        to = min(to, len(self.ready) - 1)
        if to == at:
            return Outcome(True, f"Tåg {number} står redan där.")
        entry = self.ready.pop(at)
        self.ready.insert(to, entry.model_copy(update={"moved": True}))
        return self._done(
            f"Tåg {number} flyttat till plats {to + 1} av {len(self.ready)}.", log=False
        )

    def ready_sent(self, number: str) -> Outcome:
        """Skickat: the train leaves the list Klara att skicka."""
        if (stale := self._refuse_stale()) is not None:
            return stale
        entry = next((r for r in self.ready if r.number == number), None)
        if entry is None:
            return Outcome(False, f"Tåg {number} är inte anmält klart att skicka.")
        self.ready.remove(entry)
        return self._done(f"Tåg {number} från {entry.part_name} är skickat.", by=STATION_BY)

    def part_targets(self, part_id: str, start: str) -> TklTargets:
        """The goals a part may set from a start inside its area, with whether each can be set
        now and why not. Goals only outside the area are left out: they are requests."""
        plant = self.plant
        part = plant.parts.get(part_id)
        if start not in plant.points or part is None:
            raise UnknownStart(_unknown_point(plant, start))
        found: list[TklTarget] = []
        for end in plant.ends(RouteKind.SHUNTING, start):
            chains = [
                c
                for c in plant.candidates(RouteKind.SHUNTING, start, end)
                if all(part.inside(w) for w in c)
            ]
            if not chains:
                continue
            already = self._already(RouteKind.SHUNTING, start, end)
            chosen, reason = chains[0], None
            if self.parts[part.id].fika:
                reason = f"{part.name} har fika."
            elif already is None:
                first: str | None = None
                for chain in chains:
                    why = self._part_hindrance(part, chain)
                    if why is None:
                        _, why = self._plan(chain)
                    if why is None:
                        chosen, first = chain, None
                        break
                    first = first or why
                reason = first
            found.append(
                TklTarget(
                    end=end,
                    kind=ShownKind.SHUNTING,
                    via=[w.end for w in chosen[:-1]],
                    pieces=[p for w in chosen for p in w.pieces],
                    possible=reason is None,
                    reason=reason,
                    route=already.id if already is not None else None,
                )
            )
        kinds = [ShownKind.SHUNTING] if found else []
        return TklTargets(start=start, kinds=kinds, targets=found)

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
        on_the_spot = function.type == LOCAL and action in (
            TklFunctionAction.OFF,
            TklFunctionAction.LAY,
        )
        if not on_the_spot and (remote := self.remote_refusal()) is not None:
            if function.type == LOCAL and action == TklFunctionAction.ON:
                return Outcome(
                    False,
                    f"Stationen fjärrstyrs från {self.fjarr.controller}. Be den som fjärrstyr om "
                    f"det lokala området {_cap(name)}.",
                )
            return remote
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
        """The route is done: every lock it still holds is released. An approved request whose
        routes are all gone, by nödutlösning or after its train, goes with them."""
        if route in self.routes:
            self.routes.remove(route)
        self._drop_spent()

    def _drop_spent(self) -> None:
        held = {r.request for r in self.routes if r.request is not None}
        for state in self.parts.values():
            state.requests = [r for r in state.requests if r.state == WAITING or r.id in held]

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
            parts=[self._part_shown(part) for part in plant.parts.values()],
            ready=list(self.ready),
            fjarr=self.fjarr,
        )

    def _part_shown(self, part: Part) -> TklPartShown:
        """A part as both screens show it (TKL97–TKL103): its area and border, its streets and
        routes out with whether each can go now, and its state."""
        state = self.parts[part.id]
        stale = self.problem
        streets = []
        for street in part.streets.values():
            _, why = self._street_plan(part, street.id) if stale is None else ({}, stale)
            streets.append(
                TklPartStreet(
                    id=street.id,
                    name=street.name,
                    side=street.side,
                    track=street.track,
                    positions=dict(street.positions),
                    laid=self._street_laid(street.positions),
                    possible=why is None,
                    reason=why,
                )
            )
        routes_out = []
        for out in part.routes_out.values():
            asked = next((r for r in state.requests if r.route_out == out.id), None)
            why = None if asked is not None else stale or self._out_hindrance(part, out.id)
            routes_out.append(
                TklPartRouteOut(
                    id=out.id,
                    name=out.name,
                    side=out.side,
                    track=out.track,
                    start=out.start,
                    end=out.end,
                    possible=asked is None and why is None,
                    reason=why,
                    request=asked.id if asked is not None else None,
                    state=asked.state if asked is not None else None,
                )
            )
        return TklPartShown(
            id=part.id,
            name=part.name,
            own_place=part.spec.own_place,
            place=part.spec.place,
            pieces=list(part.pieces),
            switches=sorted(part.own),
            signals=list(part.signals),
            border=list(part.spec.border),
            rules=part.rules,
            streets=streets,
            routes_out=routes_out,
            requests=[
                TklPartRequest(
                    id=r.id,
                    part=r.part,
                    route_out=r.route_out,
                    said=r.said,
                    start=part.routes_out[r.route_out].start,
                    end=part.routes_out[r.route_out].end,
                    state=r.state,
                    route=r.route,
                    asked=r.asked,
                    answered=r.answered,
                )
                for r in state.requests
            ],
            rings=state.rings,
            fika=state.fika,
            refused=list(state.refused),
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
            part=route.part,
            request=route.request,
            catalogue=route.catalogue,
            by=route.by,
            request_id=route.request_id,
            automat=route.automat,
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
                    part=shown.part if shown.part in plant.parts else None,
                    request=shown.request if shown.part in plant.parts else None,
                    catalogue=shown.catalogue,
                    by=shown.by,
                    request_id=shown.request_id,
                    automat=shown.automat,
                )
            )
        parts: dict[str, _PartState] = {p: _PartState() for p in plant.parts}
        held = {r.request for r in routes if r.request is not None}
        for kept_part in saved.parts:
            if kept_part.id not in plant.parts:
                self._stale(saved)
                return
            outs = plant.parts[kept_part.id].routes_out
            requests = [
                _Request(r.id, r.part, r.route_out, r.said, r.state, r.asked, r.route, r.answered)
                for r in kept_part.requests
                if r.route_out in outs and (r.state == WAITING or r.id in held)
            ]
            parts[kept_part.id] = _PartState(
                requests, kept_part.rings, kept_part.fika, list(kept_part.refused)
            )
        self.trains, self.routes, self.parts = trains, routes, parts
        self.ready = list(saved.ready)
        known_routes = {r.id for r in routes}
        self.fjarr = saved.fjarr.model_copy(
            update={
                "magazine": [
                    m.model_copy(
                        update={"blocked_by": [b for b in m.blocked_by if b in known_routes]}
                    )
                    for m in saved.fjarr.magazine
                ]
            }
        )
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


def _from_border(function: Function, way: Way) -> bool:
    """A train route out of a released local area from its border (FR22): it starts at one of
    the area's signals and touches nothing else of it, neither its sections, nor its signals at
    the end, nor its local switches."""
    return (
        way.kind == RouteKind.TRAIN
        and way.start in function.signals
        and way.end not in function.signals
        and not any(name in function.sections for name, _ in way.sections)
        and not any(part in function.switches for part in way.route.positions)
    )


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


def _genitive(name: str) -> str:
    """A name in the genitive, as Swedish writes it: Bangårdens, but Lunds and Gårds."""
    return name if name[-1:].lower() in ("s", "x", "z") else f"{name}s"


def _not_parts(part: Part, switch: str) -> str:
    return (
        f"Växel {switch} tillhör stationen. {part.name} lägger bara sina egna växlar och "
        "gränsväxlarna mot sitt område."
    )


def _gates_said(part: Part, laid: list[str], kept: list[str]) -> str:
    said = []
    if laid:
        word = "Gränsväxeln" if len(laid) == 1 else "Gränsväxlarna"
        said.append(f"{word} {_listed(laid)} lagd{'' if len(laid) == 1 else 'a'} mot {part.name}.")
    if kept:
        word = "Gränsväxel" if len(kept) == 1 else "Gränsväxlarna"
        said.append(f"{word} {_listed(kept)} ligger i en låst väg och står kvar.")
    return " ".join(said)
