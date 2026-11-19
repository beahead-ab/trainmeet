"""Studio, Dela stationen (#87 del b): the owner divides the station into parts (TKL97–TKL103).

A part (delställverk) is a fixed area of the station with its own operator, against the
station's one interlocking (tkl.stallverk.parts). Here the owner makes it, as data in the station
model, and Studio works out what follows from the track plan:

- The area is chosen on the panel section by section: a track circuit, or the pieces between
  two switches, signals or ends when the station has none (tkl.stallverk.plant). Its edge is
  where an area piece meets one that is not.
- A switch stands at the border when it has a piece in the area and a way out of it: a piece
  outside, or a piece that reaches the outside without passing another switch. Such a switch
  is a border switch, with its owner, the station by default, and its position towards the part
  (TKL99).
- A switch street is computed from an end and a track (RANG-02, RANG-18): from the track the
  walk goes towards the end, through the switches the part may lay, and stops where the area
  ends: past a border switch laid towards the part, at a border signal, before a station's
  switch, at the edge of the area or at another station track. At a switch it meets from its
  points, each leg is tried and the street with the fewest switches counts; when no leg gets
  out, the street ends before that switch. The street's positions are then walked again with
  tkl.stallverk.parts.street_end, which must reach the track: the same walk the interlocking's
  tests use. A street with no switch is no street.
- A route out is one of the station's shunting routes that starts at a signal in the area and
  leaves it (RANG-03): a route, or a chain of routes whose links stay in the area until the last
  one, which goes out, as the interlocking sets a request (plant.candidates).
- The checks, listed with what each is about: every street leads to its track and lays only
  what the part may lay, every route out starts inside the area, every switch at the border is
  a border switch with an owner, and the area hangs together. And the plainer ones: a name, an
  area, known switches and signals, and no piece in two parts.

Lokal frigivning and a part rest on the same kind of area (TKL103): track circuits or pieces,
switches and signals. The area picker in the web app works on that kind of area, so that local
release can use it later; Studio has no area editor for local release yet.

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from contracts.station_model import (
    BorderSwitch,
    NodeType,
    PartSide,
    Position,
    RouteOut,
    StationModel,
    StationPart,
    SwitchControl,
    SwitchStreet,
)
from contracts.tkl import (
    Panel,
    TklDela,
    TklDelaCheck,
    TklDelaFound,
    TklDelaRefKind,
    TklDelaState,
)
from tkl.stallverk.parts import Part, parts_of, resolve, street_end
from tkl.stallverk.plant import Plant
from tkl.standard import PointKind, Route, RouteKind
from tkl.standard.graph import Step
from tkl.standard.outside import outside_id

TARGETS: Final = frozenset({NodeType.STOP_POINT})
"""Places in the area a switch street may lead to, besides the station tracks: the stop
points, such as a loading track's or the depot's."""
MOST_STEPS: Final = 400
MOST_LINKS: Final = 4
"""The most routes in a chain out of the area: the links inside it, and the one out."""
HEADSHUNTS: Final = frozenset({NodeType.BUFFER_STOP})
"""Where a track in the area ends: a street that gets there after a switch starts there."""
PREFIX: Final = {PartSide.LEFT: "V", PartSide.RIGHT: "H"}
"""Vänster and Höger, as the deck and the screen name an end (TKL122)."""

Ref = TklDelaRefKind
MINUS: Final = Position.MINUS


OUT, HEADSHUNT, TRACK, POINTS = 0, 1, 2, 3
"""How a walk from a street's target ended, the best first: out of the area, at the end of a
track in it (a headshunt), at another station track, or before a switch met from its points."""


@dataclass(frozen=True)
class _End:
    """Where a walk from a street's target stopped: the switches it passed, the target's
    first, the node it stopped at, and how."""

    laid: tuple[tuple[str, Position], ...]
    node: str
    how: int


# --- the area ---------------------------------------------------------------------------------


def area_of(plant: Plant, spec: StationPart) -> set[str]:
    """The part's area as pieces: its own pieces and those of its track circuits."""
    found = {p for p in spec.pieces if p in plant.graph.pieces}
    for circuit in spec.track_circuits:
        section = plant.sections.get(circuit)
        if section is not None:
            found |= set(section.pieces)
    return found


def edge(plant: Plant, area: set[str]) -> list[str]:
    """The nodes where an area piece meets a piece that is not the area's, in the model's
    order."""
    graph = plant.graph
    found = []
    for node in graph.node_type:
        touching = set(graph.touching.get(node, []))
        if touching & area and touching - area:
            found.append(node)
    return found


def components(plant: Plant, area: set[str]) -> list[list[str]]:
    """The area's pieces in groups that hang together over their nodes, the largest first."""
    graph = plant.graph
    left = set(area)
    order = {p.id: i for i, p in enumerate(plant.model.pieces)}
    groups: list[list[str]] = []
    while left:
        first = min(left, key=lambda p: order.get(p, 0))
        group, stack = {first}, [first]
        while stack:
            piece = graph.pieces[stack.pop()]
            for node in (piece.start, piece.end):
                for other in graph.touching.get(node, []):
                    if other in left and other not in group:
                        group.add(other)
                        stack.append(other)
        left -= group
        groups.append(sorted(group, key=lambda p: order.get(p, 0)))
    return sorted(groups, key=len, reverse=True)


def _switch_pieces(plant: Plant, number: str) -> list[str]:
    switch = plant.graph.switch_of_part.get(number) or plant.switch_by_number.get(number)
    if switch is None:
        return []
    return [p for p in plant.graph.touching.get(switch.node, []) if p in plant.graph.pieces]


def _leads_out(plant: Plant, node: str, piece: str, area: set[str]) -> bool:
    """Whether a piece leaving a node reaches the outside of the area before another switch."""
    graph = plant.graph
    step = graph.leaving(piece, node)
    for _ in range(MOST_STEPS):
        if step.piece not in area:
            return True
        if graph.end_node(step) in graph.switch_at:
            return False
        moves = graph.moves(step)
        if len(moves) != 1:
            return False
        step = moves[0].step
    return False


def border_switches(plant: Plant, area: set[str]) -> list[str]:
    """The switches at the border: a piece in the area and a way out of it, by number, in the
    model's order. Only those the interlocking lays: a planned switch, or one laid by hand, has
    no owner to give."""
    found = []
    for switch in plant.model.switches:
        if switch.control != SwitchControl.TKL:
            continue
        pieces = [p for p in plant.graph.touching.get(switch.node, []) if p in plant.graph.pieces]
        if not set(pieces) & area:
            continue
        if any(_leads_out(plant, switch.node, piece, area) for piece in pieces):
            found.append(switch.number)
    return found


def suggested(plant: Plant, number: str, area: set[str]) -> BorderSwitch:
    """A border switch as Studio suggests it: the station its owner (TKL99), and towards the
    part the leg that stays in the area; straight when both or neither do."""
    switch = plant.switch_by_number.get(number)
    towards = Position.PLUS
    if switch is not None:
        stays = [
            position
            for leg, position in ((switch.straight, Position.PLUS), (switch.diverging, MINUS))
            if leg is not None and leg in area and not _leads_out(plant, switch.node, leg, area)
        ]
        if len(stays) == 1:
            towards = stays[0]
    return BorderSwitch(switch=number, towards_part=towards)


# --- switch streets (RANG-02, RANG-18) --------------------------------------------------------


def _x(cells: Mapping[str, tuple[float, float]], node: str) -> float | None:
    found = cells.get(node)
    return found[0] if found is not None else None


def _middle(plant: Plant, area: set[str], cells: Mapping[str, tuple[float, float]]) -> float:
    """The area's middle on the panel, from west to east: what is left of it is the left end."""
    xs = [
        x
        for piece in area
        for node in (plant.graph.pieces[piece].start, plant.graph.pieces[piece].end)
        if (x := _x(cells, node)) is not None
    ]
    return (min(xs) + max(xs)) / 2 if xs else 0.0


def _side(x: float | None, middle: float) -> PartSide:
    return PartSide.LEFT if x is not None and x < middle else PartSide.RIGHT


def _targets(plant: Plant, area: set[str]) -> list[tuple[str, set[str]]]:
    """What a street may lead to: the station tracks in the area, by their id, and the stop
    points in it that are on no station track, by their node."""
    graph = plant.graph
    on_tracks = {p for t in plant.model.station_tracks for p in t.pieces}
    found: list[tuple[str, set[str]]] = []
    for track in plant.model.station_tracks:
        pieces = {p for p in track.pieces if p in graph.pieces}
        if pieces and pieces <= area:
            found.append((track.id, pieces))
    for node in plant.model.nodes:
        touching = set(graph.touching.get(node.id, []))
        if node.type in TARGETS and touching and touching <= area and not touching & on_tracks:
            found.append((node.id, set()))
    return found


def _starts(plant: Plant, target: str, pieces: set[str]) -> list[Step]:
    """The steps a walk out of a target starts with: along each piece away from a stop, or
    off each end of a station track."""
    graph = plant.graph
    if not pieces:
        return [graph.leaving(piece, target) for piece in graph.touching.get(target, [])]
    found = []
    for piece in sorted(pieces):
        for node in (graph.pieces[piece].start, graph.pieces[piece].end):
            if not set(graph.touching.get(node, [])) - {piece} <= pieces:
                found.append(graph.arriving(piece, node))
    return found


def _walk(
    plant: Plant,
    part: Part,
    area: set[str],
    step: Step,
    target: set[str],
    tracks: Mapping[str, str],
    stops: set[str],
    laid: tuple[tuple[str, Position], ...] = (),
    depth: int = 0,
) -> list[_End]:
    """The ways a street can go out from its target along a step. A way gets out of the area
    past a switch laid towards the part, at a border signal, before a station's switch or at
    the area's edge. Else it ends at the end of a track in the area, where a shunt starts, at
    another station track, or before a switch it meets from its points when no leg gets
    further."""
    graph = plant.graph
    border_signals = set(part.spec.border_signals)
    for _ in range(MOST_STEPS):
        node = graph.end_node(step)
        switch = graph.switch_at.get(node)
        if switch is None:
            if {s.name for s in graph.signals_at.get(node, [])} & border_signals:
                return [_End(laid, node, OUT)]
            if node in stops and node not in target:
                return [_End(laid, node, TRACK)]
            moves = graph.moves(step)
            if not moves and graph.node_type.get(node) in HEADSHUNTS:
                return [_End(laid, node, HEADSHUNT)]
            if len(moves) != 1:
                return []
            onward = moves[0].step
            if onward.piece not in area:
                return [_End(laid, node, OUT)]
            if onward.piece not in target and onward.piece in tracks:
                return [_End(laid, node, TRACK)]
            step = onward
            continue
        moves = graph.moves(step)
        found: list[_End] = []
        if not graph.laid_by_tkl(switch):
            return [_End(laid, node, OUT)]
        for move in moves:
            numbers = list(move.positions.items())
            if not all(n in part.own or n in part.border for n, _ in numbers):
                found.append(_End(laid, node, OUT))
                continue
            if not all(part.may_lay(n, position) for n, position in numbers):
                continue
            passed = laid + tuple(numbers)
            if move.step.piece not in area:
                found.append(_End(passed, node, OUT))
            elif depth < MOST_STEPS:
                found += _walk(
                    plant, part, area, move.step, target, tracks, stops, passed, depth + 1
                )
        if len(moves) > 1 and laid and not any(f.how < TRACK for f in found):
            found.append(_End(laid, node, POINTS))
        return found
    return []


def streets(
    plant: Plant, part: Part, area: set[str], cells: Mapping[str, tuple[float, float]]
) -> list[SwitchStreet]:
    """Every switch street Studio can compute for the part: per target and end, the best way
    from the target to that end of the area (out of it, else from a headshunt, another track
    or a switch's points), with the fewest switches. Each is checked with street_end: it must
    lead to its target."""
    tracks = {p: t.id for t in plant.model.station_tracks for p in t.pieces}
    middle = _middle(plant, area, cells)
    targets = _targets(plant, area)
    stops = {target for target, pieces in targets if not pieces}
    found: list[SwitchStreet] = []
    for target, pieces in targets:
        ends = [
            end
            for first in _starts(plant, target, pieces)
            if first.piece in area
            for end in _walk(plant, part, area, first, pieces or {target}, tracks, stops)
            if end.laid
        ]
        for side in (PartSide.LEFT, PartSide.RIGHT):
            here = [e for e in ends if _side(_x(cells, e.node), middle) == side]
            chosen = min(here, key=lambda e: (e.how, len(e.laid)), default=None)
            if chosen is None:
                continue
            positions = dict(reversed(chosen.laid))
            if street_end(plant, positions) != target:
                continue
            found.append(
                SwitchStreet(
                    id=outside_id(f"{PREFIX[side]}{target}") or PREFIX[side],
                    name=f"{PREFIX[side]} {target}",
                    side=side,
                    track=target,
                    positions=positions,
                )
            )
    return found


def street_problems(plant: Plant, part: Part, street: SwitchStreet) -> list[str]:
    """Why a street does not do what it says: where it leads, and what it lays."""
    said: list[str] = []
    unknown = [n for n in street.positions if not parts_of(plant, n)]
    if unknown:
        said.append(f"Växelgatan {street.name} lägger växlar som inte finns: {', '.join(unknown)}.")
        return said
    if not street.positions:
        return [f"Växelgatan {street.name} lägger inga växlar."]
    leads = street_end(plant, street.positions)
    if leads != street.track:
        where = f"till {leads}" if leads else "ingenstans"
        said.append(f"Växelgatan {street.name} leder {where}, inte till {street.track}.")
    for number, position in street.positions.items():
        for switch_part in parts_of(plant, number):
            if part.may_lay(switch_part, position):
                continue
            if switch_part in part.border:
                said.append(
                    f"Växelgatan {street.name} lägger gränsväxeln {number} ut från delen. Den "
                    "får bara ligga mot delens område (RANG-12)."
                )
            else:
                said.append(
                    f"Växelgatan {street.name} lägger {number}, som är stationens. En gata "
                    "lägger bara delens egna växlar."
                )
            break
    return said


# --- routes out (RANG-03) -----------------------------------------------------------------------


def routes_out(
    plant: Plant, part: Part, area: set[str], cells: Mapping[str, tuple[float, float]]
) -> list[RouteOut]:
    """The station's shunting routes that start at a signal in the area and leave it: they run
    outside it or lay a border switch out, and end outside it or at a border signal. A route,
    or a chain through the part's signals, as the interlocking sets a request
    (plant.candidates). Its end is the end of the area it crosses out at; its track the station
    track it ends on."""
    shunting = [
        found[0] for (kind, _, _), found in plant.paths.items() if kind == RouteKind.SHUNTING
    ]
    by_start: dict[str, list[Route]] = {}
    for route in shunting:
        by_start.setdefault(route.start.name, []).append(route)
    starts = [
        s
        for s in dict.fromkeys([*part.spec.signals, *part.spec.border_signals])
        if s in plant.signals and _signal_inside(plant, s, area)
    ]
    middle = _middle(plant, area, cells)
    found: dict[tuple[str, str], RouteOut] = {}

    inside = set(part.spec.signals)
    border = set(part.spec.border_signals)

    def extend(start: str, here: str, links: int, seen: set[str], left: bool) -> None:
        for route in by_start.get(here, []):
            end = route.end.name
            if end in seen:
                continue
            out = left or _leaves(part, area, route.pieces, route.positions)
            ours = end in inside or end in border
            if (
                out
                and (not ours or end in border)
                and (start, end) not in found
                and plant.candidates(RouteKind.SHUNTING, start, end)
            ):
                found[(start, end)] = _route_out(plant, start, route, area, cells, middle)
            if ours and route.end.kind == PointKind.SIGNAL and links + 1 < MOST_LINKS:
                extend(start, end, links + 1, seen | {end}, out)

    for start in starts:
        extend(start, start, 0, {start}, False)
    return list(found.values())


def _leaves(
    part: Part, area: set[str], pieces: Iterable[str], positions: Mapping[str, Position]
) -> bool:
    """Whether a route leaves the part: it runs outside the area, or lays a border switch out
    of the part's position, which only the station's interlocking may (RANG-12)."""
    if set(pieces) - area:
        return True
    return any(
        border.towards_part != positions[switch]
        for switch, border in part.border.items()
        if switch in positions
    )


def _signal_inside(plant: Plant, name: str, area: set[str]) -> bool:
    signal = plant.signals.get(name)
    return signal is not None and bool(set(plant.graph.touching.get(signal.node, [])) & area)


def _route_out(
    plant: Plant,
    start: str,
    last: Route,
    area: set[str],
    cells: Mapping[str, tuple[float, float]],
    middle: float,
) -> RouteOut:
    graph = plant.graph
    track = next(
        (
            plant.track_of[section]
            for piece in reversed(last.pieces)
            if (section := plant.section_of.get(piece)) is not None and section in plant.track_of
        ),
        last.end.name,
    )
    crossing = next(
        (
            graph.end_node(Step(step.piece, not step.forward))
            for step in last.steps
            if step.piece not in area
        ),
        last.end.node,
    )
    side = _side(_x(cells, crossing), middle)
    return RouteOut(
        id=outside_id(f"{PREFIX[side]}{track}") or PREFIX[side],
        name=f"{PREFIX[side]} {track}",
        side=side,
        track=track,
        start=start,
        end=last.end.name,
    )


# --- the checks ---------------------------------------------------------------------------------


def _check(
    text: str,
    part: StationPart | None = None,
    kind: Ref | None = None,
    ref: str | None = None,
    problem: bool = True,
) -> TklDelaCheck:
    return TklDelaCheck(
        text=text, problem=problem, part=part.id if part else None, kind=kind, id=ref
    )


def checks(plant: Plant, specs: list[StationPart]) -> list[TklDelaCheck]:
    """Studio's checks of the parts, the problems first, each with what it is about."""
    found: list[TklDelaCheck] = []
    resolved = resolve(plant, specs)
    for number in sorted(n for n, c in Counter(s.id for s in specs).items() if c > 1):
        found.append(_check(f"Två delar har id {number}. Varje del behöver ett eget id."))
    owner: dict[str, str] = {}
    for spec in specs:
        part = resolved.get(spec.id)
        if part is None or part.spec is not spec:
            continue
        found += _part_checks(plant, spec, part)
        for piece in sorted(area_of(plant, spec)):
            other = owner.setdefault(piece, spec.name)
            if other != spec.name:
                found.append(
                    _check(
                        f"Spårbit {piece} hör till både {other} och {spec.name}. Ett område "
                        "hör till en del.",
                        spec,
                        Ref.PIECE,
                        piece,
                    )
                )
    return sorted(found, key=lambda c: not c.problem)


def _part_checks(plant: Plant, spec: StationPart, part: Part) -> list[TklDelaCheck]:
    found: list[TklDelaCheck] = []
    name = spec.name.strip() or spec.id
    if not spec.name.strip():
        found.append(_check(f"Delen {spec.id} behöver ett namn.", spec, Ref.PART, spec.id))
    unknown = [p for p in spec.pieces if p not in plant.graph.pieces]
    unknown += [c for c in spec.track_circuits if c not in plant.sections]
    for piece in unknown:
        found.append(
            _check(f"{name}: spårbiten {piece} finns inte i spårplanen.", spec, Ref.PIECE, piece)
        )
    area = area_of(plant, spec)
    if not area:
        found.append(
            _check(
                f"{name} har inget område. Klicka på spåren som hör till delen.",
                spec,
                Ref.PART,
                spec.id,
            )
        )
        return found
    groups = components(plant, area)
    if len(groups) > 1:
        found.append(
            _check(
                f"{name}s område hänger inte ihop: det är {len(groups)} delar. Ta med spåren "
                "mellan dem, eller gör en del av varje.",
                spec,
                Ref.PIECE,
                groups[1][0],
            )
        )
    for number in spec.switches:
        if not parts_of(plant, number):
            found.append(_check(f"{name}: växel {number} finns inte.", spec, Ref.SWITCH, number))
        elif not set(_switch_pieces(plant, number)) & area:
            found.append(
                _check(f"{name}: växel {number} står utanför området.", spec, Ref.SWITCH, number)
            )
    marked = {b.switch for b in spec.border}
    for border in spec.border:
        if not parts_of(plant, border.switch):
            found.append(
                _check(
                    f"{name}: gränsväxeln {border.switch} finns inte.",
                    spec,
                    Ref.SWITCH,
                    border.switch,
                )
            )
            continue
        if not set(_switch_pieces(plant, border.switch)) & area:
            found.append(
                _check(
                    f"{name}: gränsväxeln {border.switch} står inte vid området.",
                    spec,
                    Ref.SWITCH,
                    border.switch,
                )
            )
            continue
        towards = _leg(plant, border.switch, border.towards_part)
        switch = plant.switch_by_number.get(border.switch)
        if (
            towards is not None
            and switch is not None
            and (towards not in area or _leads_out(plant, switch.node, towards, area))
        ):
            found.append(
                _check(
                    f"{name}: gränsväxeln {border.switch} i läge {border.towards_part.value} leder "
                    "inte in i området. Ändra läget mot delen.",
                    spec,
                    Ref.SWITCH,
                    border.switch,
                )
            )
    for number in border_switches(plant, area):
        if number in marked:
            continue
        found.append(
            _check(
                f"{name}: växel {number} står vid gränsen. Gör den till gränsväxel och ange vem "
                "som äger den (TKL99).",
                spec,
                Ref.SWITCH,
                number,
            )
        )
    for signal in spec.signals:
        if signal not in plant.signals:
            found.append(_check(f"{name}: signal {signal} finns inte.", spec, Ref.SIGNAL, signal))
        elif not _signal_inside(plant, signal, area):
            found.append(
                _check(f"{name}: signal {signal} står utanför området.", spec, Ref.SIGNAL, signal)
            )
    for signal in spec.border_signals:
        if signal not in plant.signals:
            found.append(
                _check(f"{name}: gränssignalen {signal} finns inte.", spec, Ref.SIGNAL, signal)
            )
    for street_id in sorted(n for n, c in Counter(s.id for s in spec.streets).items() if c > 1):
        found.append(
            _check(f"{name}: två växelgator har id {street_id}.", spec, Ref.STREET, street_id)
        )
    for street in spec.streets:
        found += [
            _check(text, spec, Ref.STREET, street.id)
            for text in street_problems(plant, part, street)
        ]
    for out_id in sorted(n for n, c in Counter(r.id for r in spec.routes_out).items() if c > 1):
        found.append(_check(f"{name}: två vägar ut har id {out_id}.", spec, Ref.ROUTE_OUT, out_id))
    for out in spec.routes_out:
        found += [
            _check(text, spec, Ref.ROUTE_OUT, out.id)
            for text in route_out_problems(plant, part, area, out)
        ]
    if spec.own_place and not (spec.code or "").strip():
        found.append(
            _check(
                f"{name} är egen driftplats men har ingen signatur. Hubben använder namnet.",
                spec,
                Ref.PART,
                spec.id,
                problem=False,
            )
        )
    return found


def _leg(plant: Plant, number: str, position: Position) -> str | None:
    switch = plant.switch_by_number.get(number)
    if switch is None or switch.number != number:
        return None
    return switch.straight if position == Position.PLUS else switch.diverging


def route_out_problems(plant: Plant, part: Part, area: set[str], out: RouteOut) -> list[str]:
    """Why a route out cannot be the part's: it must start inside the area and leave it."""
    if out.start not in plant.signals or not _signal_inside(plant, out.start, area):
        return [f"Vägen ut {out.name} börjar vid {out.start}, utanför området."]
    chains = plant.candidates(RouteKind.SHUNTING, out.start, out.end)
    if not chains:
        return [f"Ingen växlingsväg går från {out.start} till {out.end} (vägen ut {out.name})."]
    if not any(
        _leaves(
            part,
            area,
            [p for way in chain for p in way.pieces],
            {k: v for way in chain for k, v in way.route.positions.items()},
        )
        for chain in chains
    ):
        return [f"Vägen ut {out.name} lämnar inte området. En väg i området lägger delen själv."]
    return []


# --- keeping the streets' order -------------------------------------------------------------


def ordered(
    plant: Plant, given: list[StationPart], cells: Mapping[str, tuple[float, float]]
) -> list[StationPart]:
    """The parts with each street's switches in their order: from the end of the area to the
    track, the order street_end walks them in. A browser reorders a map whose keys look like
    numbers, such as switch numbers, so the order comes back from the model's street with the
    same id, else from the street Studio computes for the same end and track."""
    kept = {(p.id, s.id): s for p in plant.model.parts for s in p.streets}
    resolved = resolve(plant, given)
    found: list[StationPart] = []
    for spec in given:
        part = resolved.get(spec.id)
        offered: dict[tuple[PartSide | None, str], SwitchStreet] = {}
        if part is not None and part.spec is spec and spec.streets:
            area = area_of(plant, spec)
            offered = {(s.side, s.track): s for s in streets(plant, part, area, cells)}
        mended = []
        for street in spec.streets:
            base = kept.get((spec.id, street.id)) or offered.get((street.side, street.track))
            if base is not None and set(base.positions) == set(street.positions):
                order = list(base.positions)
                street = street.model_copy(
                    update={"positions": {k: street.positions[k] for k in order}}
                )
            mended.append(street)
        found.append(spec.model_copy(update={"streets": mended}))
    return found


# --- the view -----------------------------------------------------------------------------------


def view(
    model: StationModel,
    plant: Plant,
    specs: list[StationPart],
    state: TklDelaState,
    panel: Panel | None,
) -> TklDela:
    """What Dela stationen shows: the parts, the sections, what each part can be given, and the
    checks. plant: the stored model's; the parts are resolved against it."""
    del model
    cells = {n.id: n.cell for n in panel.nodes} if panel is not None else {}
    resolved = resolve(plant, specs)
    found: list[TklDelaFound] = []
    for spec in specs:
        part = resolved.get(spec.id)
        if part is None or part.spec is not spec:
            continue
        area = area_of(plant, spec)
        found.append(
            TklDelaFound(
                part=spec.id,
                edge=edge(plant, area),
                border_switches=[suggested(plant, n, area) for n in border_switches(plant, area)],
                streets=streets(plant, part, area, cells) if area else [],
                routes_out=routes_out(plant, part, area, cells) if area else [],
            )
        )
    return TklDela(
        state=state,
        parts=specs,
        sections={name: list(s.pieces) for name, s in plant.sections.items() if s.pieces},
        found=found,
        checks=checks(plant, specs),
    )


__all__ = [
    "area_of",
    "border_switches",
    "checks",
    "components",
    "edge",
    "ordered",
    "route_out_problems",
    "routes_out",
    "street_problems",
    "streets",
    "view",
]
