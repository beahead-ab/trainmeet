"""Studio, Inställningar, Fjärrstyrning (#36 del b): the station's remote catalogue, its
automats and its overview, from the station's model (TKL46, FR10, FR16, FR24, FR31, FR40).

The catalogue. A remote route is one of the station's own train routes that goes in from a line
end to a station track, or out from a station track to a line end (FR10). Shunting routes never
are. Where the way in passes a signal before it reaches a track, or the way out passes one after
the track, the route is laid through the signals between, as the interlocking lays a goal
further away (TKL53, plant.candidates): in from the entry signal to the end of the first station
track the walk reaches, out from the signal at the end of the track the train stands on. Each
route gets:

- its id: the start and the end as an outside id (tkl.standard.outside.outside_id), two that
  meet told apart with -2, so that the same model always gives the same ids;
- its exit: the line exit's id in the outside, where the route comes in or leads out;
- its track: the station track's id in the outside;
- its direction: in from the line, or out to it.

The owner chooses among them; nothing is in the catalogue until the owner says so, so that the
outside of a station whose owner has not chosen is as before. A route the model no longer has is
dropped from the outside and named in the problems.

The overview (FR31, FR48, OverviewDrawing): a simple drawing, on a grid read from left to right,
of what the catalogue's routes reach, with no switch numbers and no addresses. It is made from
the station's panel (its own track plan, else the engine's): every piece a catalogue route lays,
and the line outside each of its exits, is cut into its horizontal runs, which are the overview's
tracks, and its slanted runs, which are its links: the switches as lines between the rows. The
panel's rows and columns are counted afresh over what is drawn, so the overview is denser than
the station's own picture. The main signals the routes start and end at, and those they pass,
stand on their tracks, facing the way they show; each exit stands at the end of its line. Each
catalogue route names the tracks and links it lays, in the order the train runs over them.

The automats (FR24–FR29, FR39, FR40): A1, A2 and A3 for the whole station, AN and AU for the
entry signals of one track of a double-track line, and one local release automat per local
release function in the model. Studio suggests A3, A2 and A1, with A3 the default one that the
station switches on after 90 seconds without contact (FR29), and the local release automats with
the code the panel function has in 95 or 85, else L1, L2 and so on (FR39). Two of the same kind
are told apart by the entry signal's number, as AN 21 and AN 121 (FR40).

Pure Python without I/O, using only the contracts, the engine and the plant. No code here names
a station (RS13).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from contracts.common import Side
from contracts.station_model import PanelFunctionType, StationModel
from contracts.station_outside import (
    Automat,
    AutomatKind,
    OverviewDrawing,
    OverviewExit,
    OverviewLink,
    OverviewSignal,
    OverviewTrack,
    RemoteRoute,
    RouteDirection,
)
from contracts.tkl import Panel, TklAutomatSpec, TklFjarrChoice, TklRemoteCandidate
from tkl.stallverk.plant import MAINS, Chain, Plant, Way
from tkl.standard import PointKind, RouteKind
from tkl.standard.outside import OutsideError, Remote, _ids, outside_id, panel_of

MOST_PARTS: Final = 4
"""How many routes a remote route may be laid through: in or out over the signals between."""
EPSILON: Final = 1e-6
DEFAULT_AUTOMATS: Final = (
    (AutomatKind.A3, "A3", True),
    (AutomatKind.A2, "A2", False),
    (AutomatKind.A1, "A1", False),
)
"""Studio's suggestion, in the order the station row shows them (FR43)."""
CODE_SKINS: Final = ("95", "85", "59")
"""Where a local release function's code is read from, the first one it has (FR39, FR41)."""
STATION_WIDE: Final = frozenset({AutomatKind.A1, AutomatKind.A2, AutomatKind.A3})


@dataclass(frozen=True)
class Candidate:
    """A train route that may be in the remote catalogue, as the interlocking would lay it."""

    id: str
    chain: Chain
    exit: str
    """The line exit's name in the model."""
    exit_outside: str
    track: str
    """The station track's id in the model."""
    track_outside: str
    track_label: str
    direction: RouteDirection

    @property
    def start(self) -> str:
        return self.chain[0].start

    @property
    def end(self) -> str:
        return self.chain[-1].end

    @property
    def via(self) -> list[str]:
        return [way.end for way in self.chain[:-1]]

    @property
    def remote(self) -> RemoteRoute:
        return RemoteRoute(
            id=self.id,
            start=self.start,
            end=self.end,
            exit=self.exit_outside,
            track=self.track_outside,
            direction=self.direction,
        )


# --- the catalogue ------------------------------------------------------------------------------


def _track_of_piece(model: StationModel) -> dict[str, str]:
    return {piece: track.id for track in model.station_tracks for piece in track.pieces}


def _tracks_on(way: Way, tracks: dict[str, str]) -> list[str]:
    """The station tracks a way runs over, in the order it runs over them."""
    return list(dict.fromkeys(tracks[p] for p in way.pieces if p in tracks))


def _start_track(plant: Plant, way: Way, tracks: dict[str, str]) -> str | None:
    """The station track a train stands on to take the way: the signal's approach, or where the
    way starts on a track at level 1."""
    start = way.route.start
    if start.kind == PointKind.SIGNAL:
        signal = plant.signals.get(start.name)
        return tracks.get(signal.approach) if signal is not None else None
    on = _tracks_on(way, tracks)
    return on[0] if on else None


def _ways_in(plant: Plant, tracks: dict[str, str]) -> Iterator[tuple[Chain, str]]:
    """From each way in from a line end, on through the signals between, to the first station
    track it reaches."""
    trains = [w for w in plant.preferred() if w.kind == RouteKind.TRAIN]
    by_start: dict[str, list[Way]] = {}
    for way in trains:
        by_start.setdefault(way.start, []).append(way)

    def walk(path: tuple[Way, ...]) -> Iterator[tuple[Chain, str]]:
        last = path[-1]
        if last.leaves is not None:
            return  # through the station: no track to stop at
        on = _tracks_on(last, tracks)
        if on:
            yield path, on[-1]
            return
        if len(path) >= MOST_PARTS:
            return
        for after in by_start.get(last.end, []):
            if after not in path and after.enters is None:
                yield from walk((*path, after))

    for way in trains:
        if way.enters is not None:
            yield from walk((way,))


def _ways_out(plant: Plant, tracks: dict[str, str]) -> Iterator[tuple[Chain, str]]:
    """Back from each way out to a line end, through the signals between, to the signal at the
    end of the station track the train stands on."""
    trains = [w for w in plant.preferred() if w.kind == RouteKind.TRAIN]
    by_end: dict[str, list[Way]] = {}
    for way in trains:
        by_end.setdefault(way.end, []).append(way)

    def walk(path: tuple[Way, ...]) -> Iterator[tuple[Chain, str]]:
        first = path[0]
        track = _start_track(plant, first, tracks)
        if track is not None:
            yield path, track
            return
        if first.enters is not None or len(path) >= MOST_PARTS:
            return
        for before in by_end.get(first.start, []):
            if before not in path and before.leaves is None:
                yield from walk((before, *path))

    for way in trains:
        if way.leaves is not None:
            yield from walk((way,))


def candidates(plant: Plant) -> list[Candidate]:
    """The station's train routes that may be in the remote catalogue, by line end: in from it,
    then out to it, each by station track in the model's order. Empty at level 0, which has no
    model, and for a station without line exits or station tracks."""
    model = plant.model
    tracks = _track_of_piece(model)
    track_order = {t.id: i for i, t in enumerate(model.station_tracks)}
    labels = {t.id: t.label for t in model.station_tracks}
    exit_order = {e.id: i for i, e in enumerate(model.line_exits)}
    found: dict[tuple[str, str], tuple[Chain, str, str, RouteDirection]] = {}
    for direction, walked in (
        (RouteDirection.IN, _ways_in(plant, tracks)),
        (RouteDirection.OUT, _ways_out(plant, tracks)),
    ):
        for path, track in walked:
            start, end = path[0].start, path[-1].end
            if (start, end) in found:
                continue
            chain = _laid(plant, start, end)
            if chain is None:
                continue
            line = chain[0].enters if direction == RouteDirection.IN else chain[-1].leaves
            if line is None or line not in plant.exits:
                continue
            if direction == RouteDirection.IN:
                on = [t for way in chain for t in _tracks_on(way, tracks)]
                laid_track = on[-1] if on else None
            else:
                laid_track = _start_track(plant, chain[0], tracks)
            if laid_track != track:
                continue
            found[(start, end)] = (chain, line, track, direction)
    ordered = sorted(
        found.items(),
        key=lambda item: (
            exit_order.get(item[1][1], len(exit_order)),
            0 if item[1][3] == RouteDirection.IN else 1,
            track_order.get(item[1][2], len(track_order)),
            item[0],
        ),
    )
    ids = _ids([(f"{start}-{end}", None) for (start, end), _ in ordered])
    made = []
    for made_id, ((_, _), (chain, line, track, direction)) in zip(ids, ordered, strict=True):
        if not made_id:
            continue
        made.append(
            Candidate(
                id=made_id,
                chain=chain,
                exit=line,
                exit_outside=plant.exits[line].outside,
                track=track,
                track_outside=plant.track_outside.get(track, track),
                track_label=labels.get(track, track),
                direction=direction,
            )
        )
    return made


def _laid(plant: Plant, start: str, end: str) -> Chain | None:
    """The chain the interlocking lays first for a train route from start to end."""
    found = plant.candidates(RouteKind.TRAIN, start, end)
    return found[0] if found else None


def shown(found: Sequence[Candidate], chosen: Iterable[str]) -> list[TklRemoteCandidate]:
    """The candidates as Studio lists them, the chosen ones marked."""
    picked = set(chosen)
    return [
        TklRemoteCandidate(
            id=c.id,
            start=c.start,
            end=c.end,
            via=c.via,
            exit=c.exit_outside,
            exit_name=c.exit,
            track=c.track_outside,
            track_label=c.track_label,
            direction=c.direction,
            chosen=c.id in picked,
        )
        for c in found
    ]


# --- the automats -------------------------------------------------------------------------------


def entry_signals(plant: Plant) -> list[str]:
    """The main signals where a train comes in from a line end: AN and AU are set for them."""
    found = {
        way.start
        for way in plant.preferred()
        if way.kind == RouteKind.TRAIN and way.enters is not None and way.start in plant.signals
    }
    return [s.name for s in plant.model.signals if s.name in found]


def local_releases(model: StationModel) -> list[str]:
    """The station's local release functions, by name, in the model's order."""
    return [f.name for f in model.functions if f.type == PanelFunctionType.LOCAL_RELEASE]


def _local_codes(model: StationModel) -> list[TklAutomatSpec]:
    """One local release automat per local release function: its code in 95, 85 or 59, else
    L1, L2 and so on (FR39)."""
    made: list[TklAutomatSpec] = []
    for number, function in enumerate(
        (f for f in model.functions if f.type == PanelFunctionType.LOCAL_RELEASE), start=1
    ):
        code = next((function.codes[s] for s in CODE_SKINS if function.codes.get(s)), None)
        made.append(
            TklAutomatSpec(
                code=(code or f"L{number}")[:12],
                kind=AutomatKind.LOCAL_RELEASE,
                function=function.name,
            )
        )
    return made


def suggested(model: StationModel) -> list[TklAutomatSpec]:
    """Studio's suggestion: A3 (the default), A2 and A1, and the local release automats."""
    made = [TklAutomatSpec(code=code, kind=kind, default=d) for kind, code, d in DEFAULT_AUTOMATS]
    return made + _local_codes(model)


def automats_of(model: StationModel, settings: TklFjarrChoice) -> list[TklAutomatSpec]:
    """The owner's automats, with a local release automat for each local release function the
    owner left out: every local area has its code (FR39)."""
    given = list(settings.automats)
    named = {a.function for a in given if a.kind == AutomatKind.LOCAL_RELEASE}
    taken = {a.code.casefold() for a in given}
    for local in _local_codes(model):
        if local.function in named or local.code.casefold() in taken:
            continue
        given.append(local)
        taken.add(local.code.casefold())
    return given


def code_for(kind: AutomatKind, signals: Sequence[str], same_kind: int) -> str:
    """The code a new automat gets: its kind, with the entry signal's number when there are
    several of the kind (FR40), as AN21."""
    base = kind.value.upper() if kind != AutomatKind.LOCAL_RELEASE else "L"
    if same_kind and signals:
        return f"{base}{signals[0]}"[:12]
    return base


# --- the checks ---------------------------------------------------------------------------------


def problems(plant: Plant | None, settings: TklFjarrChoice, level: int) -> list[str]:
    """What is wrong with the owner's choice, in Swedish; empty when it may be kept."""
    found: list[str] = []
    if level < 1 or plant is None:
        if settings.routes or settings.automats:
            found.append(
                "En station på nivå 0 har inget ställverk som låser vägar och därför ingen "
                "fjärrkatalog eller några automater (FR16)."
            )
        return found
    known = {c.id: c for c in candidates(plant)}
    shunting = {
        outside_id(f"{w.start}-{w.end}") for w in plant.preferred() if w.kind == RouteKind.SHUNTING
    }
    for route in settings.routes:
        if route in known:
            continue
        if route in shunting:
            found.append(f"{route} är en växlingsväg. Växlingsvägar ingår aldrig (FR10).")
        else:
            found.append(f"Tågvägen {route} finns inte bland stationens tågvägar in och ut.")
    if len(set(settings.routes)) != len(settings.routes):
        found.append("En tågväg står två gånger i fjärrkatalogen.")
    codes = [a.code.casefold() for a in settings.automats]
    if len(set(codes)) != len(codes):
        found.append("Två automater har samma kod.")
    if sum(a.kind == AutomatKind.A3 for a in settings.automats) > 1:
        found.append("En station har bara en A3 (FR26).")
    if sum(a.default for a in settings.automats) > 1:
        found.append("Bara en automat kan vara förvald (FR29).")
    signals = set(entry_signals(plant))
    functions = set(local_releases(plant.model))
    for automat in settings.automats:
        if automat.kind == AutomatKind.LOCAL_RELEASE:
            if automat.function not in functions:
                found.append(
                    f"{automat.code}: stationen har ingen panelfunktion för lokal frigivning "
                    f"som heter {automat.function or '–'}."
                )
            if automat.default:
                found.append(f"{automat.code}: en lokalfrigivningsautomat kan inte vara förvald.")
            continue
        unknown = [s for s in automat.signals if s not in signals]
        if unknown:
            found.append(f"{automat.code}: {', '.join(unknown)} är ingen infartssignal.")
        if automat.kind in (AutomatKind.AN, AutomatKind.AU) and not automat.signals:
            found.append(f"{automat.code}: välj infartssignalen för spåret automaten sköter.")
        if automat.kind in STATION_WIDE and automat.signals:
            found.append(f"{automat.code}: {automat.kind.value.upper()} gäller hela stationen.")
    return found


# --- the outside ------------------------------------------------------------------------------


def remote_of(
    plant: Plant | None, settings: TklFjarrChoice | None, panel: Panel | None = None
) -> Remote:
    """What the outside gets from the owner's choice: the chosen routes the model still has,
    the automats, who may receive the station, and the overview of the chosen routes. Nothing
    at level 0 or before the owner has chosen (FR16)."""
    if plant is None or settings is None:
        return Remote()
    known = {c.id: c for c in candidates(plant)}
    picked = [known[r] for r in dict.fromkeys(settings.routes) if r in known]
    automats: list[Automat] = []
    seen: set[str] = set()
    a3 = False
    for spec in automats_of(plant.model, settings):
        key = spec.code.casefold()
        if key in seen or (spec.kind == AutomatKind.A3 and a3):
            continue
        seen.add(key)
        a3 = a3 or spec.kind == AutomatKind.A3
        automats.append(Automat(code=spec.code, kind=spec.kind, default=spec.default))
    overview = None
    if picked:
        drawn = panel if panel is not None else _panel(plant.model)
        overview = overview_of(plant, drawn, picked) if drawn is not None else None
    return Remote(
        routes=[c.remote for c in picked],
        automats=automats,
        receivers=list(dict.fromkeys(settings.receivers)),
        overview=overview,
    )


def _panel(model: StationModel) -> Panel | None:
    try:
        return panel_of(model)
    except OutsideError:
        return None


# --- the overview -----------------------------------------------------------------------------


@dataclass
class _Run:
    """A straight run of a piece on the panel, from one corner to the next."""

    piece: str
    a: tuple[float, float]
    b: tuple[float, float]

    @property
    def flat(self) -> bool:
        return abs(self.a[1] - self.b[1]) < EPSILON

    @property
    def upright(self) -> bool:
        return abs(self.a[0] - self.b[0]) < EPSILON


def _runs(panel: Panel, pieces: Iterable[str]) -> dict[str, list[_Run]]:
    """Each piece's runs, from its start to its end."""
    lines = {line.piece: line for line in panel.lines}
    made: dict[str, list[_Run]] = {}
    for piece in pieces:
        line = lines.get(piece)
        if line is None:
            continue
        cells = [(float(c[0]), float(c[1])) for c in line.cells]
        made[piece] = [
            _Run(piece, a, b)
            for a, b in pairwise(cells)
            if abs(a[0] - b[0]) > EPSILON or abs(a[1] - b[1]) > EPSILON
        ]
    return made


def _rank(values: Iterable[float]) -> dict[float, int]:
    """Each distinct value's place among them, from 0: the overview's rows and columns."""
    ordered: list[float] = []
    for value in sorted(values):
        if not ordered or value - ordered[-1] > EPSILON:
            ordered.append(value)
    return {value: i for i, value in enumerate(ordered)}


def _at(ranks: dict[float, int], value: float) -> int:
    """The rank of a value, matching the nearest one within the tolerance."""
    found = ranks.get(value)
    if found is not None:
        return found
    nearest = min(ranks, key=lambda v: abs(v - value))
    return ranks[nearest]


def overview_of(plant: Plant, panel: Panel, routes: Sequence[Candidate]) -> OverviewDrawing:
    """The overview of the catalogue's routes (FR31, FR48), on its own grid."""
    model = plant.model
    pieces: list[str] = []
    for candidate in routes:
        for way in candidate.chain:
            pieces += [p for p in way.pieces if p not in pieces]
    used_exits = list(dict.fromkeys(c.exit for c in routes))
    for exit_name in used_exits:
        pieces += [p for p in plant.exits[exit_name].pieces if p not in pieces]
    runs = _runs(panel, pieces)
    xs = [x for found in runs.values() for run in found for x in (run.a[0], run.b[0])]
    ys = [y for found in runs.values() for run in found for y in (run.a[1], run.b[1])]
    if not xs:
        return OverviewDrawing(columns=1, rows=1)
    columns, rows = _rank(xs), _rank(ys)
    track_of_piece = _track_of_piece(model)
    platforms = [(x, y, x + w, y + h) for (x, y, w, h) in panel.platforms]
    tracks: list[OverviewTrack] = []
    links: list[OverviewLink] = []
    ids: dict[tuple[str, int], str] = {}
    for piece in pieces:
        for i, run in enumerate(runs.get(piece, [])):
            col_a, col_b = _at(columns, run.a[0]), _at(columns, run.b[0])
            row_a, row_b = _at(rows, run.a[1]), _at(rows, run.b[1])
            if run.flat and col_a != col_b:
                made_id = f"t{len(tracks) + 1}"
                station_track = track_of_piece.get(piece)
                tracks.append(
                    OverviewTrack(
                        id=made_id,
                        row=row_a,
                        start=min(col_a, col_b),
                        end=max(col_a, col_b),
                        track=plant.track_outside.get(station_track) if station_track else None,
                        platform=_has_platform(run, platforms),
                    )
                )
            elif not run.flat:
                made_id = f"l{len(links) + 1}"
                links.append(
                    OverviewLink(
                        id=made_id,
                        from_row=row_a,
                        from_column=col_a,
                        to_row=row_b,
                        to_column=col_b,
                    )
                )
            else:
                continue
            ids[(piece, i)] = made_id
    signals = _signals(plant, panel, routes, columns, rows)
    exits = []
    for exit_name in used_exits:
        place = plant.exits[exit_name]
        node = next((n for n in panel.nodes if n.id == place.node), None)
        if node is None:
            continue
        exits.append(
            OverviewExit(
                exit=place.outside,
                row=_at(rows, float(node.cell[1])),
                column=_at(columns, float(node.cell[0])),
            )
        )
    laid: dict[str, list[str]] = {}
    for candidate in routes:
        order: list[str] = []
        for way in candidate.chain:
            for step in way.route.steps:
                found = runs.get(step.piece, [])
                indices = range(len(found)) if step.forward else range(len(found) - 1, -1, -1)
                for i in indices:
                    piece_id = ids.get((step.piece, i))
                    if piece_id is not None and piece_id not in order:
                        order.append(piece_id)
        laid[candidate.id] = order
    return OverviewDrawing(
        columns=max(1, len(columns) - 1),
        rows=max(1, len(rows)),
        tracks=tracks,
        links=links,
        signals=signals,
        exits=exits,
        routes=laid,
    )


def _has_platform(run: _Run, platforms: Sequence[tuple[float, float, float, float]]) -> bool:
    """A platform beside the run: its box touches the run's row and overlaps its columns."""
    left, right = sorted((run.a[0], run.b[0]))
    y = run.a[1]
    for x0, y0, x1, y1 in platforms:
        if x1 <= left or x0 >= right:
            continue
        if y0 - 0.75 <= y <= y1 + 0.75:
            return True
    return False


def _signals(
    plant: Plant,
    panel: Panel,
    routes: Sequence[Candidate],
    columns: dict[float, int],
    rows: dict[float, int],
) -> list[OverviewSignal]:
    """The main signals the routes start and end at and pass, where they stand on the panel."""
    wanted: list[str] = []
    for candidate in routes:
        for way in candidate.chain:
            for name in (way.start, *way.route.passed, way.end):
                signal = plant.signals.get(name)
                if signal is not None and signal.type in MAINS and name not in wanted:
                    wanted.append(name)
    drawn = {s.name: s for s in panel.signals}
    made = []
    for name in wanted:
        found = drawn.get(name)
        if found is None:
            continue
        x, y = float(found.cell[0]), float(found.cell[1])
        towards = Side.RIGHT if found.toward[0] > 0 else Side.LEFT
        made.append(
            OverviewSignal(
                name=name[:12], row=_at(rows, y), column=_at(columns, x), towards=towards
            )
        )
    return made
