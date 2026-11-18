"""The layout engine (§3, STD-02, STD-03, STD-10–STD-13, STD-20): the four reference stations
and made-up ones, laid out on the grid. Nothing here names a station (RS13); they are found
from the files."""

from __future__ import annotations

import math
from collections.abc import Iterator
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from contracts.station_model import NodeType, SignalType, StationModel, StationTrack, SwitchType
from contracts.tkl import Panel, PanelAngle, PanelSource
from tkl.standard import LayoutError, fits, lay_out
from tkl.standard.grid import describe, hits
from tkl.standard.layout import FITS, SHORTENED, STATION_TRACK
from tkl.tests.provstation import build, ekby, signal, switch

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
SIDEWAYS = {PanelAngle.STEEP: 1, PanelAngle.FLAT: 2}
"""Cells sideways per cell down, in a transition."""


@cache
def model(station: str) -> StationModel:
    return StationModel.model_validate_json((MODELS / f"{station}.tkl.json").read_text("utf-8"))


@cache
def chosen(station: str) -> Panel:
    return lay_out(model(station))


def made_up() -> dict[str, StationModel]:
    return {"ekby": ekby(), "ekby utan ritning": without_drawing(ekby())}


def without_drawing(found: StationModel) -> StationModel:
    return found.model_copy(
        update={"pieces": [p.model_copy(update={"geometry": []}) for p in found.pieces]}
    )


def every() -> Iterator[tuple[str, StationModel]]:
    for station in STATIONS:
        yield station, model(station)
    yield from made_up().items()


CASES = [name for name, _ in every()]


def case(name: str) -> StationModel:
    return dict(every())[name]


def variants(found: StationModel) -> list[Panel]:
    return [lay_out(found, angle, shortened) for angle in PanelAngle for shortened in (False, True)]


# --- The grid -------------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_every_piece_is_on_the_grid_at_the_panel_s_one_angle(name: str) -> None:
    for panel in variants(case(name)):
        assert panel.source == PanelSource.ENGINE
        assert panel.angle in (PanelAngle.STEEP, PanelAngle.FLAT)
        assert panel.cell == (24, 24), "a cell is 24 px (STD-20)"
        assert panel.angle is not None
        ratio = SIDEWAYS[panel.angle]
        rows = {
            n.cell[1] for n in panel.nodes if n.type in (NodeType.SWITCH, NodeType.SIGNAL_POINT)
        }
        assert all((y - rows_base(panel)) % 3 == 0 for y in rows), "rows are three cells apart"
        for line in panel.lines:
            if line.free:
                continue
            for a, b in pairwise(line.cells):
                dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
                assert dy < 1e-6 or abs(dx - ratio * dy) < 1e-3, (line.piece, a, b)
                assert b[0] != a[0] or dy < 1e-6, "no vertical track in the engine's layout"


def rows_base(panel: Panel) -> float:
    return min(n.cell[1] for n in panel.nodes)


@pytest.mark.parametrize("name", CASES)
def test_no_two_tracks_on_one_cell_and_no_crossing_without_a_crossing(name: str) -> None:
    found = case(name)
    ends = {p.id: (p.start, p.end) for p in found.pieces}
    for panel in variants(found):
        lines = {line.piece: line.cells for line in panel.lines}
        nodes = {n.id: n.cell for n in panel.nodes}
        assert [describe(h) for h in hits(lines, ends, nodes)] == []
        assert sampled_overlaps(panel, found) == []


def sampled_overlaps(panel: Panel, found: StationModel) -> list[str]:
    """A second look, by cells: points every quarter cell along each track, and no point used
    by two pieces unless it is a node both end at."""
    ends = {p.id: {p.start, p.end} for p in found.pieces}
    cells = {n.id: (round(n.cell[0], 2), round(n.cell[1], 2)) for n in panel.nodes}
    seen: dict[tuple[float, float], str] = {}
    faults = []
    for line in panel.lines:
        if line.free:
            continue
        for a, b in pairwise(line.cells):
            steps = max(1, round(4 * max(abs(b[0] - a[0]), abs(b[1] - a[1]))))
            for i in range(steps + 1):
                f = i / steps
                point = (round(a[0] + (b[0] - a[0]) * f, 2), round(a[1] + (b[1] - a[1]) * f, 2))
                other = seen.setdefault(point, line.piece)
                if other == line.piece:
                    continue
                shared = ends[other] & ends[line.piece]
                if not any(cells.get(n) == point for n in shared):
                    faults.append(f"{other} och {line.piece} vid {point}")
    return faults


@pytest.mark.parametrize("name", CASES)
def test_a_crossover_is_exactly_three_or_six_cells_per_row(name: str) -> None:
    found = case(name)
    for panel in variants(found):
        assert panel.angle is not None
        ratio = SIDEWAYS[panel.angle]
        crossovers = list(crossovers_of(found))
        lines = {line.piece: line.cells for line in panel.lines}
        for start, end, pieces in crossovers:
            way = [p for piece in pieces for p in lines[piece]]
            first = min(way, key=lambda p: p[0])
            last = max(way, key=lambda p: p[0])
            rows = abs(last[1] - first[1]) / 3
            if rows:
                assert abs((last[0] - first[0]) - 3 * ratio * rows) < 1e-3, (start, end)


def crossovers_of(found: StationModel) -> Iterator[tuple[str, str, list[str]]]:
    """Two switches joined by their diverging legs, over joints only: a crossover."""
    nodes = {n.id: n.type for n in found.nodes}
    touching: dict[str, list[str]] = {}
    for p in found.pieces:
        touching.setdefault(p.start, []).append(p.id)
        touching.setdefault(p.end, []).append(p.id)
    pieces = {p.id: p for p in found.pieces}
    diverging = {
        (s.diverging, s.node)
        for s in found.switches
        if s.type == SwitchType.ORDINARY and s.diverging is not None
    }
    soft = {NodeType.JOINT, NodeType.BLOCK_BOUNDARY, NodeType.MODULE_JOINT}
    for leg, node in sorted(diverging):
        way = [leg]
        here = pieces[leg].end if pieces[leg].start == node else pieces[leg].start
        while nodes.get(here) in soft and len(touching[here]) == 2:
            nxt = next(p for p in touching[here] if p != way[-1])
            way.append(nxt)
            here = pieces[nxt].end if pieces[nxt].start == here else pieces[nxt].start
        if (way[-1], here) in diverging and node < here:
            yield node, here, way


def test_there_are_crossovers_to_check() -> None:
    found = {s: list(crossovers_of(model(s))) for s in STATIONS}
    assert sum(len(c) for c in found.values()) >= 5, found


@pytest.mark.parametrize("name", CASES)
def test_a_station_track_is_at_least_14_cells_or_8_when_shortened(name: str) -> None:
    found = case(name)
    for panel in variants(found):
        least = SHORTENED if panel.shortened else STATION_TRACK
        lines = {line.piece: line.cells for line in panel.lines}
        for track in found.station_tracks:
            flat = [
                (a, b)
                for piece in track.pieces
                for a, b in pairwise(lines[piece])
                if abs(a[1] - b[1]) < 1e-6
            ]
            if not flat:
                continue
            ys = [a[1] for a, _ in flat]
            row = max(set(ys), key=ys.count)
            xs = [x for a, b in flat if a[1] == row for x in (a[0], b[0])]
            assert max(xs) - min(xs) >= least - 1e-6, (track.id, panel.angle, panel.shortened)


@pytest.mark.parametrize("name", CASES)
def test_rows_follow_the_drawing(name: str) -> None:
    """Two station tracks side by side keep the drawing's order from the top (STD-10): side by
    side in the drawing where there is one, and on the panel with the order of the station
    tracks where there is not."""
    found = case(name)
    panel = lay_out(found)
    lines = {line.piece: line.cells for line in panel.lines}
    drawn = any(p.geometry for p in found.pieces)
    placed = []
    for index, track in enumerate(found.station_tracks):
        cells = [c for piece in track.pieces for c in lines[piece]]
        ys = [c[1] for c in cells]
        row = max(set(ys), key=ys.count)
        real = [p for piece in track.pieces for p in pieces_of(found)[piece].geometry]
        if drawn and real:
            span = (min(p[0] for p in real), max(p[0] for p in real))
            height = sum(p[1] for p in real) / len(real)
        else:
            on_row = [c[0] for c in cells if c[1] == row]
            span, height = (min(on_row), max(on_row)), float(index)
        placed.append((track.id, row, span, height))
    checked = 0
    for i, (ida, rowa, spana, ya) in enumerate(placed):
        for idb, rowb, spanb, yb in placed[i + 1 :]:
            if spana[1] <= spanb[0] or spanb[1] <= spana[0] or rowa == rowb:
                continue
            checked += 1
            assert (rowa < rowb) == (ya < yb), (ida, idb)
    assert checked or len(found.station_tracks) < 2


def pieces_of(found: StationModel) -> dict[str, Any]:
    return {p.id: p for p in found.pieces}


def test_without_a_drawing_the_station_tracks_order_is_the_drawing_order() -> None:
    found = without_drawing(ekby())
    reversed_order = found.model_copy(
        update={"station_tracks": list(reversed(found.station_tracks))}
    )
    for given in (found, reversed_order):
        panel = lay_out(given)
        lines = {line.piece: line.cells for line in panel.lines}
        first, second = given.station_tracks
        assert lines[first.pieces[0]][0][1] < lines[second.pieces[0]][0][1]


def test_a_diverging_leg_leaves_on_the_side_the_drawing_shows() -> None:
    found = ekby()
    panel = lay_out(found)
    lines = {line.piece: line.cells for line in panel.lines}
    assert lines["j"][0][1] > lines["d"][0][1], "track 2 below track 1, as drawn"
    assert lines["n"][0][1] > lines["j"][0][1], "the siding below track 2"
    mirrored = found.model_copy(
        update={
            "pieces": [
                p.model_copy(update={"geometry": [(x, -y) for x, y in p.geometry]})
                for p in found.pieces
            ]
        }
    )
    lines = {line.piece: line.cells for line in lay_out(mirrored).lines}
    assert lines["j"][0][1] < lines["d"][0][1], "drawn the other way up, laid out so"


# --- The angle, shortening and fields -------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_flat_is_chosen_only_when_it_fits(name: str) -> None:
    found = case(name)
    panel = lay_out(found)
    flat = lay_out(found, PanelAngle.FLAT)
    assert (panel.angle == PanelAngle.FLAT) == fits(flat)
    if panel.angle == PanelAngle.STEEP and not fits(lay_out(found, PanelAngle.STEEP)):
        assert panel.shortened, "then the station tracks are shortened"


@pytest.mark.parametrize("name", CASES)
def test_fields_only_when_nothing_else_fits(name: str) -> None:
    panel = lay_out(case(name))
    if panel.width <= FITS[0]:
        assert panel.fields == []
        return
    assert panel.angle == PanelAngle.STEEP and panel.shortened
    assert len(panel.fields) >= 2
    assert panel.fields[0].start == 0 and panel.fields[-1].end == panel.width
    for one, other in pairwise(panel.fields):
        assert one.end == other.start
    assert all(f.end - f.start <= FITS[0] for f in panel.fields)


def test_a_long_station_is_split_into_fields() -> None:
    """Eight passing loops in a row: too wide even at 45° with the station tracks shortened."""
    spec, switches, signals, tracks = [], [], [], []
    for i in range(8):
        a, b = f"S{i}", f"S{i + 1}"
        spec += [f"m{i}:{a}-X{i}", f"x{i}:X{i}-Y{i}", f"y{i}:Y{i}-{b}"]
        spec += [f"u{i}:X{i}-U{i}", f"v{i}:U{i}-V{i}", f"w{i}:V{i}-Y{i}"]
        switches += [
            switch(f"X{i}", f"m{i}", f"x{i}", f"u{i}"),
            switch(f"Y{i}", f"y{i}", f"x{i}", f"w{i}"),
        ]
        signals += [
            signal(f"U{i}", SignalType.HSI, f"U{i}", f"u{i}"),
            signal(f"V{i}", SignalType.HSI, f"V{i}", f"w{i}"),
        ]
        tracks.append(StationTrack(id=f"{i + 1}", label=f"Spår {i + 1}", pieces=[f"v{i}"]))
    long = build(" ".join(spec), switches=switches, signals=signals, station_tracks=tracks)
    assert not fits(lay_out(long, PanelAngle.STEEP, shortened=True))
    panel = lay_out(long)
    assert panel.angle == PanelAngle.STEEP and panel.shortened
    assert len(panel.fields) >= 2
    assert panel.fields[0].start == 0 and panel.fields[-1].end == panel.width
    assert all(f.end - f.start <= FITS[0] for f in panel.fields)


# --- Labels ---------------------------------------------------------------------------


def test_signals_stand_over_the_track_east_and_under_it_west() -> None:
    panel = lay_out(ekby())
    side = {s.name: s.side for s in panel.signals}
    assert side["11"] == "over" and side["12"] == "under"
    assert side["21"] == "over" and side["22"] == "under"
    for s in panel.signals:
        assert (s.label[1] < s.cell[1]) == (s.side == "over")
        assert s.symbol == s.cell or math.dist(s.symbol, s.cell) <= 0.6, "in the track line"


def test_on_a_double_track_line_the_signals_stand_outside_the_pair() -> None:
    """TKL43: two exits at the same end on rows next to each other, tracks that do not join."""
    for station in STATIONS:
        panel = chosen(station)
        exits = {e.node: e for e in model(station).line_exits}
        cells = {n.id: n.cell for n in panel.nodes}
        side = {s.name: s.side for s in panel.signals}
        for one in exits.values():
            for other in exits.values():
                a, b = cells.get(one.node), cells.get(other.node)
                if a is None or b is None or a[0] != b[0] or b[1] - a[1] != 3:
                    continue
                upper = [side[n] for n in one.signals if n in side]
                lower = [side[n] for n in other.signals if n in side]
                if upper and lower and set(upper) == {"over"}:
                    assert set(lower) == {"under"}, (station, one.id, other.id)


def test_a_stop_lamp_stands_beside_the_track_to_the_left() -> None:
    for station in STATIONS:
        for s in chosen(station).signals:
            if s.type == SignalType.STOP_LAMP:
                left = (s.toward[1], -s.toward[0])
                offset = (s.symbol[0] - s.cell[0], s.symbol[1] - s.cell[1])
                assert offset[0] * left[0] + offset[1] * left[1] > 0, (station, s.name)


def test_track_names_exits_and_switch_numbers_have_their_places() -> None:
    panel = lay_out(ekby())
    assert {t.name for t in panel.track_names} == {"1", "2"}
    for t in panel.track_names:
        assert t.train_number[0] > t.cell[0], "the train number's box right after the name"
    exits = {label.text: label for label in panel.labels if label.kind == "exit"}
    assert exits["W"].anchor == "end" and exits["O"].anchor == "start", "at the row's end"
    assert {s.number for s in panel.switches} == {"1", "2", "4"}


def test_the_soft_view_carries_the_drawing() -> None:
    found = ekby()
    panel = lay_out(found)
    assert panel.real_box == (0.0, 100.0, 3000.0, 120.0)
    shapes = {line.piece: line.real for line in panel.lines}
    assert shapes == {p.id: list(p.geometry) for p in found.pieces}


def test_a_station_the_engine_cannot_lay_out_says_why() -> None:
    lonely = build("a:A-B", switches=[], signals=[])
    lonely = lonely.model_copy(update={"pieces": []})
    with pytest.raises(LayoutError):
        lay_out(lonely)
