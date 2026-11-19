"""Platser and the station's geography for the deck, computed from the station model (SD66).

A place is a line exit or a station track where a train route starts or ends: the exit a route
comes in from or leaves to, else the track of the route's first or last section. A start that
is neither, such as a signal in the middle of a chain, is no place; the routes through it are
still reached as chains between places (TKL53).

The parts (SD79) run from west to east: the west exits, the station's track parts and the east
exits. Track parts are the station tracks that stand over each other on the panel: their names
on the panel lie close together from west to east. A part is named after what its tracks have
in common, such as "Spår c" for 1c, 2c, 11, 12 and 13, else after its first and last track.

Positions are the panel's, in its cells: west is left and the top row the top tracks (SD2). The
cut-out of Spårplan is made of squares of `tile` cells: the spacing of the track rows, so that a
key holds one track (SD71), and smaller when a square would hold two switches.

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, Literal

from contracts.common import Side
from contracts.tkl import Panel, TklDeckPart, TklDeckPlace, TklDeckPoint
from tkl.stallverk import Plant, Way
from tkl.standard import OutsideError, RouteKind, outside_of
from tkl.standard.outside import exit_ids

GAP: Final = 0.5
"""Tracks whose names lie further apart than this share of a track's length are two parts."""
MOST_TILE: Final = 4
NUMBERED: Final = re.compile(r"^(?P<head>.*?)(?P<number>\d+)(?P<tail>\D*)$")
SUFFIX: Final = re.compile(r"^\d+(?P<letter>[A-Za-zåäöÅÄÖ]+)$")


@dataclass(frozen=True)
class Geography:
    """What the profile needs of the station, for every grid."""

    places: list[TklDeckPlace]
    parts: list[TklDeckPart]
    points: list[TklDeckPoint]
    start_place: dict[str, str]
    """A route's start -> its place."""
    end_place: dict[str, str]
    """A route's end -> its place."""
    tile: float
    tile_origin: tuple[float, float]
    """Where the cut-out's squares begin, in the panel's cells."""
    plan: tuple[float, float]
    exit_place: dict[str, str]
    """An exit's id in the model -> its place."""
    track_place: dict[str, str]
    """A station track's id in the model -> its place."""


def geography(plant: Plant, panel: Panel | None) -> Geography:
    """The places, the parts and the points of a station, west to east."""
    model = plant.model
    nodes = {n.id: n.cell for n in panel.nodes} if panel is not None else {}
    signal_cells = {s.name: s.cell for s in panel.signals} if panel is not None else {}
    lines = {line.piece: line for line in panel.lines} if panel is not None else {}
    width = panel.width if panel is not None else 0.0

    start_place: dict[str, str] = {}
    end_place: dict[str, str] = {}
    for way in plant.ways():
        if way.kind != RouteKind.TRAIN:
            continue
        begin_at = _start_of(plant, way)
        if begin_at is not None:
            start_place.setdefault(way.start, _key(*begin_at))
        end_at = _end_of(plant, way)
        if end_at is not None:
            end_place.setdefault(way.end, _key(*end_at))
    used = set(start_place.values()) | set(end_place.values())

    exit_place: dict[str, str] = {}
    track_place: dict[str, str] = {}
    sides = _sides(plant, panel)
    found: list[tuple[str, Literal["exit", "track"], str, float, float, float, float]] = []
    for line in model.line_exits:
        if _key("exit", line.id) not in used:
            continue
        x, y = nodes.get(line.node, (0.0, 0.0))
        found.append((line.id, "exit", line.id, x, y, x, x))
    for track in model.station_tracks:
        if _key("track", track.id) not in used:
            continue
        xs = [c[0] for p in track.pieces if p in lines for c in lines[p].cells]
        ys = [c[1] for p in track.pieces if p in lines for c in lines[p].cells]
        named = next(
            (
                n.cell
                for n in (panel.track_names if panel else [])
                if n.name in (track.id, track.label)
            ),
            None,
        )
        low, high = (min(xs), max(xs)) if xs else (0.0, 0.0)
        x = named[0] if named else (low + high) / 2
        y = sum(ys) / len(ys) if ys else (named[1] if named else 0.0)
        found.append((track.id, "track", track.id, x, y, low, high))

    ids: dict[str, str] = {}
    taken: set[str] = set()
    for item in found:
        own, kind = item[0], item[1]
        given = own
        while given in taken:
            given += "*"
        taken.add(given)
        ids[_key(kind, own)] = given
    for item in found:
        model_id, kind = item[0], item[1]
        (exit_place if kind == "exit" else track_place)[model_id] = ids[_key(kind, model_id)]

    west = sorted(
        (f for f in found if f[1] == "exit" and sides.get(f[0], _side(f[3], width)) == Side.LEFT),
        key=lambda f: (f[4], f[3]),
    )
    east = sorted(
        (f for f in found if f[1] == "exit" and sides.get(f[0], _side(f[3], width)) != Side.LEFT),
        key=lambda f: (f[4], f[3]),
    )
    tracks = sorted((f for f in found if f[1] == "track"), key=lambda f: (f[3], f[4]))
    groups: list[list[tuple[str, Literal["exit", "track"], str, float, float, float, float]]] = []
    lengths = sorted(f[6] - f[5] for f in tracks)
    gap = GAP * (lengths[len(lengths) // 2] if lengths else 0.0)
    for track_found in tracks:
        if groups and track_found[3] - max(g[3] for g in groups[-1]) <= gap:
            groups[-1].append(track_found)
        else:
            groups.append([track_found])

    parts: list[TklDeckPart] = []
    places: list[TklDeckPlace] = []
    ordered = [("Väster", west)] if west else []
    ordered += [(_part_name([g[0] for g in group]), group) for group in groups]
    ordered += [("Öster", east)] if east else []
    for number, (name, group) in enumerate(ordered):
        members = sorted(group, key=lambda f: (f[4], f[3]))
        parts.append(
            TklDeckPart(
                name=name,
                places=[ids[_key(f[1], f[0])] for f in members],
                said=compressed(sorted((f[2] for f in members), key=_natural)),
            )
        )
        for model_id, kind, own_name, x, y, _, _ in members:
            key = _key(kind, model_id)
            starts = sorted(s for s, p in start_place.items() if p == key)
            ends = sorted(e for e, p in end_place.items() if p == key)
            signals = [s for s in dict.fromkeys(starts + ends) if s in plant.signals][:2]
            places.append(
                TklDeckPlace(
                    id=ids[key],
                    kind=kind,
                    name=own_name,
                    part=number,
                    starts=starts,
                    ends=ends,
                    signals=signals,
                    x=x,
                    y=y,
                )
            )

    tile, tile_origin = _tile(panel)
    point_nodes: dict[str, str] = {}
    starting: set[str] = set()
    for way in plant.ways():
        point_nodes.setdefault(way.start, way.route.start.node)
        point_nodes.setdefault(way.end, way.route.end.node)
        starting.add(way.start)
    points: list[TklDeckPoint] = []
    for name, node in sorted(point_nodes.items()):
        cell = signal_cells.get(name) or nodes.get(node)
        if cell is None:
            continue
        points.append(TklDeckPoint(name=name, x=cell[0], y=cell[1], start=name in starting))
    return Geography(
        places=places,
        parts=parts,
        points=points,
        start_place={s: ids[p] for s, p in start_place.items() if p in ids},
        end_place={e: ids[p] for e, p in end_place.items() if p in ids},
        tile=tile,
        tile_origin=tile_origin,
        plan=(panel.width, panel.height) if panel is not None else (0.0, 0.0),
        exit_place=exit_place,
        track_place=track_place,
    )


def _key(kind: str, name: str) -> str:
    return f"{kind}\N{UNIT SEPARATOR}{name}"


def _start_of(plant: Plant, way: Way) -> tuple[str, str] | None:
    """Where a train route starts: the track its start signal stands at, else its exit."""
    signal = plant.signals.get(way.start)
    if signal is not None and signal.approach in plant.section_of:
        track = plant.track_of.get(plant.section_of[signal.approach])
        if track is not None:
            return "track", track
    if way.enters is not None:
        return "exit", way.enters
    exit_id = plant.exit_at.get(way.route.start.node)
    if exit_id is not None:
        return "exit", exit_id
    tracks = {plant.track_of.get(s) for s in plant.touching(way.route.start.node)} - {None}
    if len(tracks) == 1:
        return "track", str(tracks.pop())
    return None


def _end_of(plant: Plant, way: Way) -> tuple[str, str] | None:
    """Where a train route ends: the exit it leaves to, else the track of its last section."""
    if way.leaves is not None:
        return "exit", way.leaves
    track = plant.track_of.get(way.sections[-1][0])
    return ("track", track) if track is not None else None


def _sides(plant: Plant, panel: Panel | None) -> dict[str, Side]:
    """The exits' sides as the outside has them, by the model's ids."""
    model = plant.model
    try:
        outside = outside_of(model, model.station_id, model.name, panel=panel)
    except OutsideError:
        return {}
    by_outside = {e.id: e.side for e in outside.exits}
    return {m: by_outside[o] for m, o in exit_ids(model).items() if o in by_outside}


def _side(x: float, width: float) -> Side:
    return Side.LEFT if x <= width / 2 else Side.RIGHT


def _part_name(names: list[str]) -> str:
    """What a part's tracks have in common: a letter after the number, else first and last."""
    letters = Counter(m.group("letter") for n in names if (m := SUFFIX.match(n)))
    if letters:
        letter, _ = letters.most_common(1)[0]
        return f"Spår {letter}"
    ordered = sorted(names, key=_natural)
    if len(ordered) == 1:
        return f"Spår {ordered[0]}"
    return f"Spår {ordered[0]}\N{EN DASH}{ordered[-1]}"


def _natural(name: str) -> tuple[str, int, str]:
    found = NUMBERED.match(name)
    if found is None:
        return name, -1, ""
    return found.group("head"), int(found.group("number")), found.group("tail")


def compressed(names: Iterable[str]) -> str:
    """Names in short: three or more in a row with the same letters become first–last, as
    A1–A4 or 11–13."""
    found = list(names)
    said: list[str] = []
    i = 0
    while i < len(found):
        j = i
        here = NUMBERED.match(found[i])
        while here is not None and j + 1 < len(found):
            following = NUMBERED.match(found[j + 1])
            if following is None or (following.group("head"), following.group("tail")) != (
                here.group("head"),
                here.group("tail"),
            ):
                break
            if int(following.group("number")) != int(here.group("number")) + (j + 1 - i):
                break
            j += 1
        if j - i >= 2:
            said.append(f"{found[i]}\N{EN DASH}{found[j]}")
        else:
            said.extend(found[i : j + 1])
        i = j + 1
    return " ".join(said)


def _tile(panel: Panel | None) -> tuple[float, tuple[float, float]]:
    """The side of a cut-out square in the panel's cells, and where the squares begin: the
    spacing of the track rows, with a row of track through the middle of each square, and moved
    sideways so that as few squares as can be hold two switches (SD71)."""
    if panel is None:
        return 1.0, (0.0, 0.0)
    rows = sorted(
        {
            round(line.cells[0][1], 2)
            for line in panel.lines
            if all(abs(c[1] - line.cells[0][1]) < 1e-6 for c in line.cells)
        }
    )
    gaps = [b - a for a, b in pairwise(rows) if b - a >= 0.5]
    size = float(max(1, min(MOST_TILE, round(min(gaps))))) if gaps else 1.0
    oy = (rows[0] - size / 2) % size if rows else 0.0
    knots = [s.cell for s in panel.switches]
    best: tuple[int, float] | None = None
    for step in range(int(size * 4)):
        ox = step / 4
        squares = Counter(
            (math.floor((x - ox) / size), math.floor((y - oy) / size)) for x, y in knots
        )
        most = max(squares.values(), default=0)
        if best is None or most < best[0]:
            best = (most, ox)
    return size, (best[1] if best else 0.0, oy)
