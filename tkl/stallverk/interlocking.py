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

Without detection the train number follows the buttons (STV-15): occupancy is where a train
number is, and it never frees anything by itself (STV-16). Only step, arrive, depart and the
releases do.

Two Förslag wait for Benny's answer (trainmeet #62) and have a seam each: the signals a route
passes (STV-19, `passed_showing`) and where the green number stands (STV-21, `green_numbers`).
Flank protection (STV-20) has its seam in plant.protection_holds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from contracts.station import ExitSignalAspect
from contracts.station_model import Position, SwitchControl
from contracts.tkl import RouteKind as ShownKind
from contracts.tkl import (
    TklAspect,
    TklExitShown,
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
from tkl.stallverk.plant import MINUS_SIGN, Chain, Plant, Spot, Way, not_laid, sign
from tkl.standard import PointKind, RouteKind

KEPT_EVENTS: Final = 100
WORD: Final = {RouteKind.TRAIN: "tågväg", RouteKind.SHUNTING: "växlingsväg"}
STALE: Final = (
    "Ställverkets sparade läge gäller en annan version av stationsmodellen. Nollställ ställverket."
)
BROKEN: Final = "Ställverkets sparade läge går inte att läsa. Nollställ ställverket."


@dataclass(frozen=True)
class Outcome:
    """Ja, or no with the reason; and what goes up to Hubben."""

    accepted: bool
    message: str
    route: int | None = None
    reports: tuple[TklReport, ...] = ()


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
        """The start signal: the route's aspect until the train has passed it."""
        if self.at >= 0 or self.way.route.start.kind != PointKind.SIGNAL:
            return TklAspect.STOP
        return TklAspect.PROCEED if self.way.kind == RouteKind.TRAIN else TklAspect.SHUNT

    def passed_showing(self) -> list[str]:
        """STV-19, a Förslag: the signals the route passes show its aspect until the train
        has passed them. The seam for Benny's answer (trainmeet #62)."""
        return [s for s, k in sorted(self.way.passed_at.items()) if self.at < k]

    def showing(self) -> dict[str, TklAspect]:
        """The signals this route holds at proceed or shunt."""
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
        self._saved: TklInterlocking | None = None
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
        node = self.plant.part_node.get(part)
        if node is None:
            return None
        for section in sorted(self.plant.touching(node)):
            if section in occupied:
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
        """Why the way cannot be set on top of what `locks` holds, or None."""
        plant = self.plant
        for i, (name, pieces) in enumerate(way.sections):
            for piece in pieces:
                holder = locks.pieces.get(piece)
                if holder is not None:
                    return f"{_cap(plant.said(name))} är låst i vägen {holder.name}."
            taken = locks.detectors.get(plant.sections[name].detector)
            if taken is not None:
                return f"{_cap(plant.said(name))} är låst i vägen {taken[1].name}."
            train = occupied.get(name)
            if train is None or name in starting:
                continue
            if way.kind == RouteKind.SHUNTING and last and i == way.last:
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
            return Outcome(
                True, f"{_cap(WORD[chosen])}en {start} → {end} ligger redan.", already.id
            )
        reasons: list[str] = []
        for chain in found:
            planned, why = self._plan(chain)
            if why is None:
                return self._lay(chain, planned)
            reasons.append(why)
        return Outcome(False, reasons[0])

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
        outcome = self._done(said + ".", route=first.id)
        return Outcome(True, outcome.message, first.id, self._exit_reports(before))

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
            held = locks.parts.get(part)
            if held:
                follow = "" if part in own else " och kan inte följa med"
                return Outcome(False, f"Växel {part} är låst i vägen {held[0][0].name}{follow}.")
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
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre.")
        before = self.exit_aspects()
        reports: list[TklReport] = []
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
        route = self._route(route_id)
        if route is None:
            return Outcome(False, "Vägen finns inte längre.")
        if route.way.leaves is None:
            return Outcome(False, f"Vägen {route.name} går inte ut på linjen.")
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

    def _complete(self, route: _Route) -> None:
        """The route is done: every lock it still holds is released."""
        if route in self.routes:
            self.routes.remove(route)

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
            estimated=self.level < 3,
        )

    def view(self) -> TklInterlocking:
        """Ställverkets läge: everything the panel draws (STV-08)."""
        plant = self.plant
        if self._saved is not None:
            return self._saved.model_copy(
                update={"problem": self.problem, "revision": self.revision, "events": self.events}
            )
        locks = self._locks()
        switches = {}
        for part, control in plant.control.items():
            holders = [r for r, _ in locks.parts.get(part, [])]
            switches[part] = TklSwitchShown(
                position=self.positions.get(part) if control == SwitchControl.TKL else None,
                control=control,
                routes=sorted(r.id for r in holders),
                protection=any(part in r.way.protection for r in holders),
            )
        ends = {r.way.end for r in self.routes}
        signals = {}
        for name in plant.signals:
            holder = locks.showing.get(name)
            aspect = holder.showing()[name] if holder is not None else TklAspect.STOP
            signals[name] = TklSignalShown(aspect=aspect, end=name in ends)
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
            events=list(self.events),
            last_id=self.last_id,
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
            passed=route.passed_showing(),
            leaves=way.leaves,
            enters=way.enters,
            set_at=route.set_at,
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
            routes.append(
                _Route(
                    id=shown.id,
                    way=way,
                    chain=shown.chain,
                    released=[s.released for s in shown.sections],
                    set_at=shown.set_at,
                    train=shown.train if shown.train in known else None,
                    at=min(shown.at, way.last),
                )
            )
        self.trains, self.routes = trains, routes

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


def _unknown_point(plant: Plant, name: str) -> str:
    if name in plant.signals:
        return f"Inga vägar börjar eller slutar vid signalen {name}."
    return f"{name} finns inte bland stationens signaler och vägar."
