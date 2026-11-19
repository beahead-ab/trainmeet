"""Delställverk (#87, TKL97–TKL103): a station's parts as the interlocking uses them.

A part is a fixed area of the station with its own operator, against the station's one
interlocking, which locks every route (TKL97, TKL102). It is resolved once against the plant,
from the model's own data:

- its area: the sections whose pieces are all the part's, from its track circuits or pieces. A
  route the part sets itself runs inside it; a route over the border is a request;
- its own switch parts, which it lays freely, and its border switches with their owner and the
  position towards the part (TKL99). The side that does not own a border switch may always lay
  it towards the part's area, never out (RANG-12);
- its switch streets (RANG-02) and the routes out it may request (RANG-03).

The rules are applied by the interlocking (tkl.stallverk.interlocking), the one place where
safety is checked (STV-43). Lokal frigivning and a part rest on the same kind of area (TKL103):
local release is lent out for a while by the station, a part is fixed and has its own operator.

Also here: where a switch street leads, the walk its table in the document was tried with
(RANG-18), and the trains a part may announce ready to send, from the plan (TKL108, TKL110).

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from contracts import station
from contracts.station_model import (
    BorderSwitch,
    NodeType,
    PartOwner,
    PartRules,
    Position,
    RouteOut,
    StationPart,
    SwitchStreet,
)
from contracts.tkl import TklPartTrain, TklPartTrains
from tkl.standard.graph import parts as switch_parts

if TYPE_CHECKING:
    from tkl.stallverk.plant import Plant, Way

ENDS: Final = frozenset({NodeType.STOP_POINT, NodeType.BUFFER_STOP, NodeType.LINE_EXIT})
"""Where a walk along a switch street stops when it has not reached a station track first."""
MOST_STEPS: Final = 200
LATE: Final = "99:99"
"""A train without a planned time sorts after those with one."""


@dataclass(frozen=True)
class Part:
    """A part (delställverk) resolved against the plant. Names the plant does not know are
    left out."""

    spec: StationPart
    sections: frozenset[str]
    """The area: the sections whose pieces are all the part's."""
    pieces: tuple[str, ...]
    own: frozenset[str]
    """The part's own switch parts, laid freely by it."""
    border: Mapping[str, BorderSwitch]
    """Every border switch part, with its owner and the position towards the part."""
    signals: tuple[str, ...]
    streets: Mapping[str, SwitchStreet]
    routes_out: Mapping[str, RouteOut]

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def rules(self) -> PartRules:
        return self.spec.rules

    def inside(self, way: Way) -> bool:
        """The way runs inside the part's area, every section of it."""
        return all(name in self.sections for name, _ in way.sections)

    def may_lay(self, part: str, position: Position) -> bool:
        """Whether the part may lay a switch part in a position: its own, or a border switch
        it owns, or one the station owns towards the part's area when the rules allow it."""
        if part in self.own:
            return True
        border = self.border.get(part)
        if border is None:
            return False
        if border.owner == PartOwner.PART:
            return True
        return self.rules.lays_towards_part and position == border.towards_part


def resolve(plant: Plant) -> dict[str, Part]:
    """The model's parts, by id: the first of two with the same id counts."""
    found: dict[str, Part] = {}
    for spec in plant.model.parts:
        if spec.id in found:
            continue
        listed = set(spec.pieces)
        for circuit in spec.track_circuits:
            section = plant.sections.get(circuit)
            if section is not None:
                listed |= set(section.pieces)
        sections = frozenset(
            name
            for name, section in plant.sections.items()
            if section.pieces and set(section.pieces) <= listed
        )
        order = {p.id: i for i, p in enumerate(plant.model.pieces)}
        pieces = tuple(
            sorted(
                (p for name in sections for p in plant.sections[name].pieces),
                key=lambda p: order.get(p, 0),
            )
        )
        border = {part: b for b in spec.border for part in parts_of(plant, b.switch)}
        own = frozenset(part for n in spec.switches for part in parts_of(plant, n)) - set(border)
        found[spec.id] = Part(
            spec=spec,
            sections=sections,
            pieces=pieces,
            own=own,
            border=border,
            signals=tuple(s for s in spec.signals if s in plant.signals),
            streets={s.id: s for s in spec.streets},
            routes_out={r.id: r for r in spec.routes_out},
        )
    return found


def parts_of(plant: Plant, number: str) -> list[str]:
    """The switch parts a number names: an ordinary switch's own, a slip's parts, or a part."""
    switch = plant.switch_by_number.get(number)
    if switch is not None:
        return [p for p in switch_parts(switch) if p in plant.control]
    return [number] if number in plant.control else []


def owner_of(parts: Iterable[Part], switch: str) -> tuple[Part, BorderSwitch] | None:
    """The part a border switch is at, with its rule there."""
    for part in parts:
        border = part.border.get(switch)
        if border is not None:
            return part, border
    return None


# --- where a switch street leads (RANG-18) ----------------------------------------------------


def street_end(plant: Plant, positions: Mapping[str, Position]) -> str | None:
    """Where a switch street leads: from its first switch along the track with the street's
    positions, the station track it reaches first, by its id, else the stop point or buffer
    stop. Of the ways out of the first switch, the one that passes most of the street's
    switches counts. None when no way out of the first switch fits the positions."""
    graph = plant.graph
    if not positions:
        return None
    first = graph.switch_of_part.get(next(iter(positions)))
    if first is None:
        return None
    track_of_piece = {p: t.id for t in plant.model.station_tracks for p in t.pieces}
    best: tuple[int, str] | None = None
    for leg in (first.trunk, first.straight, first.diverging):
        if leg is None or leg not in graph.pieces:
            continue
        found = _walk(plant, first.node, leg, positions, track_of_piece)
        if found is not None and (best is None or found[0] > best[0]):
            best = found
    return best[1] if best is not None else None


def _walk(
    plant: Plant,
    node: str,
    piece: str,
    positions: Mapping[str, Position],
    tracks: Mapping[str, str],
) -> tuple[int, str] | None:
    graph = plant.graph
    here_switch = graph.switch_at.get(node)
    if here_switch is not None and here_switch.number in positions:
        wanted = positions[here_switch.number]
        leg = here_switch.straight if wanted == Position.PLUS else here_switch.diverging
        if piece not in (here_switch.trunk, leg):
            return None
    passed = {here_switch.number} if here_switch is not None else set()
    step = graph.leaving(piece, node)
    for _ in range(MOST_STEPS):
        if step.piece in tracks:
            return len(passed & set(positions)), tracks[step.piece]
        node = graph.end_node(step)
        if graph.node_type.get(node) in ENDS:
            return len(passed & set(positions)), node
        switch = graph.switch_at.get(node)
        if switch is not None:
            if switch.number not in positions:
                return None
            wanted = positions[switch.number]
            leg = switch.straight if wanted == Position.PLUS else switch.diverging
            if step.piece == switch.trunk:
                onward = leg
            elif step.piece == leg:
                onward = switch.trunk
            else:
                return None
            if onward is None or onward not in graph.pieces:
                return None
            passed.add(switch.number)
            step = graph.leaving(onward, node)
            continue
        others = [p for p in graph.touching.get(node, []) if p != step.piece]
        if len(others) != 1:
            return None
        step = graph.leaving(others[0], node)
    return None


# --- the trains a part may announce ready to send (TKL108, TKL110) ----------------------------


def plan_trains(
    part: Part,
    plant: Plant,
    here: station.Snapshot | None,
    own: station.Snapshot | None = None,
) -> TklPartTrains:
    """The trains a part chooses among for Klart att skicka, the earliest first.

    A part that is its own driftplats (TKL101) has the trains that depart from it in the
    timetable (TKL108): from its own place's snapshot when TKL is approved for that place
    (#87 del c, TRAFIK-35), else from the station's own snapshot, which TKL already gets: the
    calls coming from the part's driftplats, with their time at the station. Another part, and
    one whose driftplats Hubben does not know yet, has the station's trains that by the plan
    stand on a track in its area (TKL110). Another number may always be typed."""
    found: list[TklPartTrain] = []
    spec = part.spec
    if spec.own_place and own is not None:
        for call in own.calls:
            if call.to_place and call.departure_state == station.DepartureState.PLANNED:
                found.append(_train(call, call.departure, call.track or call.planned_track))
    elif spec.own_place and spec.place and here is not None:
        for call in here.calls:
            if call.from_place == spec.place and _waiting(call):
                found.append(_train(call, call.arrival or call.departure, None))
    else:
        tracks = _tracks_in(part, plant)
        for call in here.calls if here is not None else []:
            on = call.track or call.planned_track
            if on in tracks and call.departure_state == station.DepartureState.PLANNED:
                found.append(_train(call, call.departure, tracks[on]))
    found.sort(key=lambda t: (t.departure or LATE, t.number))
    message = None
    if not found:
        if here is None and own is None:
            message = "TKL har ingen plan från Hubben. Skriv tågnumret."
        elif spec.own_place:
            message = f"Inga tåg avgår från {spec.name} enligt planen. Skriv tågnumret."
        else:
            message = f"Inga tåg står på spåren i {spec.name} enligt planen. Skriv tågnumret."
    return TklPartTrains(part=spec.id, trains=found, message=message)


def _waiting(call: station.CallHere) -> bool:
    return (
        call.arrival_state != station.ArrivalState.ARRIVED
        and call.departure_state == station.DepartureState.PLANNED
    )


def _train(call: station.CallHere, time: str | None, track: str | None) -> TklPartTrain:
    return TklPartTrain(
        number=call.train_number,
        call=call.call,
        track=track,
        departure=time,
        label=call.train_label or call.train_type,
    )


def _tracks_in(part: Part, plant: Plant) -> dict[str, str]:
    """The station tracks in the part's area, by every name the plan may use for them: the
    track's id, its label and its id in the outside. To the track's id."""
    area = set(part.pieces)
    found: dict[str, str] = {}
    for track in plant.model.station_tracks:
        if track.pieces and set(track.pieces) <= area:
            for name in (track.id, track.label, plant.track_outside.get(track.id, track.id)):
                found[name] = track.id
    return found
