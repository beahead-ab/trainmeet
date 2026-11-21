"""Import från AnyRail (#91), rule by rule (trainmeet-cad-anyrail-import.md 1–5, ANYRAIL-01–22), on
synthetic files written as AnyRail 2.0 writes its XML export (cad/tests/anyrail_syntetisk.py). The
reference stations' own files are read by test_anyrail_referens.py, locally."""

from __future__ import annotations

import contextlib
import io
import math
import zipfile
from collections import Counter

import pytest

from cad import checks, dxf
from cad.anyrail import interpret, outputs, reader
from cad.anyrail.interpret import Result
from cad.tests.anyrail_syntetisk import EAST, Drawing, station_any, station_xml
from contracts.cad import AnyRailMeasures, Certainty, CheckKind, GraphSource, Scale
from contracts.station_model import NodeType

DEFAULT = AnyRailMeasures()


def read(data: bytes, measures: AnyRailMeasures = DEFAULT, scale: Scale = Scale.H0) -> Result:
    return interpret.interpret(reader.read(data, "fil.xml"), scale, measures)


@pytest.fixture(scope="module")
def station() -> Result:
    return read(station_xml())


def kinds(result: Result) -> Counter[str]:
    return Counter(c.kind.value for c in result.checks)


def module(result: Result, number: str) -> interpret.Proposal:
    return next(p for p in result.proposals if p.number == number)


# --- 1. The file -----------------------------------------------------------------------------


def test_the_xml_export_is_read_in_cm_as_mm() -> None:
    layout = reader.read(station_xml(), "station.xml")
    assert layout.format == "xml" and (layout.length, layout.width) == (6400.0, 1500.0)
    flex = [p for p in layout.parts if p.type == "Flex" and p.elements[0].kind == "line"]
    assert {round(p.elements[0].width, 1) for p in flex} == {16.5, 3.2}
    turnout = next(p for p in layout.parts if p.type == "RightRegularTurnout")
    assert [e.kind for e in turnout.elements] == ["line", "arc"] and len(turnout.endpoints) == 3
    assert all(a in layout.endpoints and b in layout.endpoints for a, b in layout.connections)


def test_a_zip_with_the_file_is_read_too() -> None:
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("station.xml", station_xml())
    layout = reader.read(packed.getvalue(), "station.zip")
    assert layout.parts and layout.format == "xml"


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (
            b'<?xml version="1.0"?><!DOCTYPE layout [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><layout>&b;</layout>',
            "DOCTYPE",
        ),
        (
            b'<?xml version="1.0"?><!DOCTYPE layout SYSTEM "file:///etc/passwd"><layout/>',
            "DOCTYPE",
        ),
        (b"<layout><parts><part", "trasig"),
        (b"<nagot/>", "<layout>"),
        (
            b'<layout workAreaLengthCm="1" workAreaWidthCm="1"><parts></parts></layout>',
            "inga delar",
        ),
        (
            b'<layout><parts><part type="Flex" id="1"><endpointNrs><endpointNr>7</endpointNr>'
            b"</endpointNrs><drawing></drawing></part></parts><endpoints></endpoints></layout>",
            "ändpunkt som saknas",
        ),
        (
            b'<layout><endpoints><endpoint nr="1" coordCm="1e400, 1, 0" direction="0"/>'
            b"</endpoints></layout>",
            "utanför ritytan",
        ),
        (b"serialization::archive", "AnyRail"),
        (b"\x16\x00\x00\x00\x00\x00\x00\x00serialization::archive\x11\x00\x04", "slutar"),
    ],
)
def test_a_hostile_or_broken_file_is_refused_with_why(data: bytes, why: str) -> None:
    with pytest.raises(reader.Unreadable, match=why) as refused:
        reader.read(data, "fil.any" if b"archive" in data else "fil.xml")
    assert str(refused.value).startswith("Filen gick inte att läsa som AnyRail")


def test_a_file_over_the_limit_and_a_zip_bomb_are_refused() -> None:
    with pytest.raises(reader.Unreadable, match="20 MB"):
        reader.read(b"<layout>" + b" " * reader.MAX_BYTES, "stor.xml")
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("stor.xml", b"<layout>" + b" " * (reader.MAX_BYTES + 10))
    assert len(packed.getvalue()) < 100_000
    with pytest.raises(reader.Unreadable, match="20 MB"):
        reader.read(packed.getvalue(), "stor.zip")
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w") as archive:
        archive.writestr("a.xml", station_xml())
        archive.writestr("b.xml", station_xml())
    with pytest.raises(reader.Unreadable, match="en enda"):
        reader.read(two.getvalue(), "tva.zip")


def test_too_many_parts_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader, "MAX_PARTS", 10)
    with pytest.raises(reader.Unreadable, match="fler än 10 delar"):
        reader.read(station_xml(), "station.xml")


def test_anyrails_own_file_gives_the_same_station_as_the_export(station: Result) -> None:
    layout = reader.read(station_any(), "station.any")
    assert layout.format == "any" and layout.library == "SYNT01"
    assert all(p.article for p in layout.parts if p.track) and not layout.connections
    own = interpret.interpret(layout, interpret.scale_of(layout), DEFAULT)
    assert [m.number for m in own.modules] == [m.number for m in station.modules]
    assert [(s.number, s.side, s.assumed, s.at) for s in own.switches] == [
        (s.number, s.side, s.assumed, s.at) for s in station.switches
    ]
    assert [r.tracks for r in own.profiles] == [r.tracks for r in station.profiles]
    for key in ("crossings", "backward_removed", "gaps", "overlaps", "loops_removed", "loose"):
        assert getattr(own.stats, key) == getattr(station.stats, key), key
    # AnyRail's own ids are the archive's object ids.
    assert all(s.anyrail and s.anyrail.isdigit() for s in own.switches if not s.assumed)


def test_a_cut_or_damaged_own_file_is_refused_or_read_never_past_its_end() -> None:
    data = station_any()
    for cut in range(0, len(data), 997):
        try:
            reader.read(data[:cut], "station.any")
        except reader.Unreadable as refused:
            assert str(refused).startswith("Filen gick inte att läsa som AnyRail")
    damaged = bytearray(data)
    for k in range(40, len(damaged), 211):
        damaged[k] ^= 0xFF
    with contextlib.suppress(reader.Unreadable):
        reader.read(bytes(damaged), "station.any")


def test_the_direction_decides_how_an_arc_bulges(station: Result) -> None:
    # Two of the file's four arcs bulge the other way when read from their ends and radius
    # alone; with their direction, växel 2's branch bends back toward spår 1's side.
    assert (station.stats.arcs, station.stats.arcs_other_way) == (4, 2)
    branch = [
        p
        for p in station.graph.pieces
        if p.origin and p.origin.ref and any(s.kind == "arc" for s in p.segments)
    ]
    arc = next(s for p in branch for s in p.segments if s.kind == "arc" and s.start[1] < 120)
    assert arc.kind == "arc" and arc.center[1] > arc.start[1]  # the centre below: bulging up


# --- 2. The rules ------------------------------------------------------------------------------


def test_rule_1_track_is_as_wide_as_the_track_width(station: Result) -> None:
    assert station.stats.track_parts == 26
    wide = read(station_xml(), DEFAULT.model_copy(update={"track_width": 40.0}))
    assert wide.stats.track_parts == 0 and not wide.modules


def test_rule_2_modules_from_the_thin_lines_against_the_standard_sizes(station: Result) -> None:
    assert [(m.number, m.standard, m.end) for m in station.modules] == [
        ("1", "1500 × 700", False),
        ("2a", "1500 × 350", False),
        ("2b", "1500 × 350", False),
        ("3", "1500 × 700", False),
        ("Ä1", "700 × 355", True),
        ("Ä2", "700 × 355", True),
    ]
    one = station.modules[0]
    assert one.at == (900.0, 0.0) and one.angle == 0 and one.shape.length == 1500
    odd = Drawing(3000, 1000)
    odd.module(100, 0, 1400, 600)
    odd.line((150, 140), (1450, 140))
    found = read(odd.xml())
    assert [(m.number, m.standard) for m in found.modules] == [("1", None)]


def test_a_module_at_an_angle_keeps_its_frame() -> None:
    d = Drawing(3000, 2000)
    d.module(200, 800, 700, 355, angle=22.5)
    a = math.radians(-22.5)
    start = (200 + 30 * math.cos(a) - 140 * math.sin(a), 800 + 30 * math.sin(a) + 140 * math.cos(a))
    d.line(start, (start[0] + 600 * math.cos(a), start[1] + 600 * math.sin(a)))
    found = read(d.xml())
    assert len(found.modules) == 1
    turned = found.modules[0]
    assert turned.angle == pytest.approx(22.5, abs=0.01) and turned.end and turned.number == "Ä1"
    piece = turned.graph.pieces[0]
    assert piece.segments[0].start[1] == pytest.approx(140, abs=0.5)  # along Kant 1 in its frame


def test_rule_3_gaps_and_overlaps_are_joined_in_the_middle(station: Result) -> None:
    assert (station.stats.gaps, station.stats.overlaps) == (6, 1)
    fixes = [c for c in station.checks if c.kind == CheckKind.DRAWING_FIX]
    assert any("Överlapp på 30,0 mm" in c.title for c in fixes)
    short = read(station_xml(), DEFAULT.model_copy(update={"join_distance": 7.0}))
    assert (short.stats.gaps, short.stats.overlaps) == (1, 0)
    strict = read(station_xml(), DEFAULT.model_copy(update={"lateral": 0.0}))
    assert strict.stats.gaps == 0


def test_rule_4_track_over_the_outer_edge_is_the_line_and_a_loop_goes(station: Result) -> None:
    rows = {r.joint: r for r in station.profiles}
    assert rows["Linjen|Ä1"].tracks == (140, 197)
    assert station.stats.loops_removed == 1
    end = module(station, "Ä2").drawing
    stops = [n for n in end.nodes.values() if n.type == NodeType.BUFFER_STOP]
    assert len(stops) == 2  # the loop's two tracks end as ordinary track ends (AR4)


def test_rule_5_a_flex_that_parts_without_a_switch_is_an_assumed_switch(station: Result) -> None:
    assumed = [s for s in station.switches if s.assumed]
    assert [(s.number, s.at, s.side, s.anyrail) for s in assumed] == [
        (4, (4800.0, 197.0), "right", None)
    ]
    three = module(station, "3").drawing
    switch = next(s for s in three.switches.values() if s.number == "4")
    assert switch.origin is not None and switch.origin.certainty == Certainty.UNCERTAIN
    assert switch.straight is not None
    assert three.pieces[switch.straight].segs[-1].end[1] == pytest.approx(197)
    found = checks.find(three)
    yellow = [c for c in found if c.kind == CheckKind.SWITCH_ASSUMED]
    assert len(yellow) == 1 and yellow[0].assumed and yellow[0].key == assumed[0].confirm


def test_rule_6_a_crossing_once_far_from_a_node_and_the_doubts() -> None:
    station = read(station_xml())
    assert station.stats.crossings == 1
    crossing = next(n for n in station.graph.nodes if n.type == NodeType.CROSSING)
    assert crossing.at[0] == pytest.approx(4525, abs=2) and crossing.at[1] == pytest.approx(197)
    far = read(station_xml(), DEFAULT.model_copy(update={"crossing_node": 300.0}))
    assert far.stats.crossings == 0
    flagged = read(station_xml(), DEFAULT.model_copy(update={"crossing_angle": 10.0}))
    assert flagged.stats.crossings == 1 and kinds(flagged)["crossing_doubt"] == 1
    # Two tracks at 3°: a crossing, flagged; two that meet twice: a warning, no crossing.
    d = Drawing(3000, 1000)
    d.module(100, 0, 1500, 700)
    d.line((150, 300), (1450, 300))
    d.line((150, 266), (1450, 334))  # 3° across
    d.line((150, 500), (1450, 500))
    d.bezier([(150, 505), (600, 480), (1000, 480), (1450, 505)])  # meets the line twice
    both = read(d.xml())
    assert both.stats.crossings == 1
    doubts = [c.title for c in both.checks if c.kind == CheckKind.CROSSING_DOUBT]
    assert sorted(doubts) == ["Korsning på 3,0°, troligen ett ritfel", "Två spår möts två gånger"]


def test_a_track_drawn_twice_is_one_track_and_yellow_until_confirmed() -> None:
    d = Drawing(3000, 1000)
    d.module(100, 0, 1500, 700)
    d.line((0, 300), (1700, 300))
    d.line((400, 303), (1200, 304))  # the same track, drawn again 3–4 mm beside it
    found = read(d.xml())
    assert found.stats.doubled_removed == 1
    assert (found.stats.switches, found.stats.crossings) == (0, 0)
    assert not [c for c in found.checks if c.kind == CheckKind.CROSSING_DOUBT]
    fixed = [c for c in found.checks if c.key.startswith("drawing_fix:doubled:")]
    assert len(fixed) == 1 and fixed[0].assumed and fixed[0].kind == CheckKind.DRAWING_FIX
    assert fixed[0].title == "Två spår ritade ovanpå varandra lästes som ett"
    assert (400.0, 303.0) in [line[0] for line in found.left_out]  # drawn as taken away
    one = found.modules[0].graph
    assert len(one.pieces) == 1 and len(one.nodes) == 2  # one track, gable to gable
    piece = one.pieces[0]
    assert piece.origin is not None and piece.origin.certainty == Certainty.UNCERTAIN
    assert piece.origin.ref is not None and "+" in piece.origin.ref  # both AnyRail ids kept
    # In the module it is yellow until the owner confirms it; then it is answered.
    drawing = found.proposals[0].drawing
    yellow = [c for c in checks.find(drawing) if c.key.startswith(checks.ANYRAIL_DOUBLED)]
    assert len(yellow) == 1 and yellow[0].assumed and yellow[0].kind == CheckKind.DRAWING_FIX
    rows = {r.joint: r.tracks for r in found.profiles}
    assert rows == {"Linjen|1": (300,), "1|Linjen": (300,)}
    # With a lateral error of 1 mm they are two tracks side by side: none is taken away, and the
    # one drawn again hangs together with nothing, a loose part (rule 8).
    tight = read(d.xml(), DEFAULT.model_copy(update={"lateral": 1.0}))
    assert (tight.stats.doubled_removed, tight.stats.loose) == (0, 1)


def test_two_tracks_that_cross_twice_at_an_angle_stay_two_with_a_warning() -> None:
    d = Drawing(3000, 1000)
    d.module(100, 0, 1500, 700)
    _, trunk_end = d.line((0, 500), (300, 500))
    points, straight, branch, straight_at, branch_at, _ = d.turnout((300, 500), EAST, "right")
    d.connect(trunk_end, points)
    on, _ = d.line(straight_at, (1700, 500))
    d.connect(straight, on)
    # The branch goes over the track and back, crossing it twice at about 20°.
    back, _ = d.bezier([branch_at, (900, 570), (1000, 380), (1400, 560)])
    d.connect(branch, back)
    found = read(d.xml())
    assert (found.stats.crossings, found.stats.doubled_removed) == (0, 0)
    assert (found.stats.switches, found.stats.loose) == (1, 0)
    doubts = [c.title for c in found.checks if c.kind == CheckKind.CROSSING_DOUBT]
    assert doubts == ["Två spår möts två gånger"]
    assert len(found.modules[0].graph.pieces) == 5  # trunk, legs, the line on, the branch


def test_a_switch_whose_legs_cross_a_joint_before_they_part_moves_to_the_joint() -> None:
    d = Drawing(3400, 1000)
    d.module(100, 0, 1500, 700)
    d.module(1600, 0, 1500, 700)
    _, trunk_end = d.line((0, 300), (1590, 300))
    points, straight, _, straight_at, _, _ = d.turnout((1590, 300), EAST, "right")
    d.connect(trunk_end, points)
    on, _ = d.line(straight_at, (3200, 300))
    d.connect(straight, on)
    found = read(d.xml())
    # The legs cross the joint 10 mm from the points, still on top of each other: one gable
    # track, and the switch lies on the joint, in module 2 where its legs are.
    rows = {r.joint: r.tracks for r in found.profiles}
    assert rows["1|2"] == (300,)
    switch = found.switches[0]
    assert switch.over_joint and switch.at[0] == pytest.approx(1600, abs=0.5)
    assert {m.key: m.number for m in found.modules}[switch.module or ""] == "2"
    joint = next(c for c in found.checks if c.kind == CheckKind.SWITCH_JOINT)
    assert "flyttades" in joint.text and "10,0 mm" in joint.text
    assert all(len(m.graph.switches) == (1 if m.number == "2" else 0) for m in found.modules)


def test_rule_7_the_turntable_bridge_goes_and_its_tracks_end_in_the_pit() -> None:
    d = Drawing(3000, 1000)
    d.module(100, 0, 1500, 700)
    d.circle((800, 400), 120)
    d.circle((800, 400), 150)
    d.line((680, 400), (920, 400))  # the bridge through the centre
    a, _ = d.line((800 - 125, 400), (150, 400))  # radial, to the west, to the line
    d.line((800 + 125, 400), (1350, 400))  # radial, east, ending in the module
    del a
    found = read(d.xml())
    assert found.stats.bridges_removed == 1 and found.stats.loose == 0
    assert kinds(found)["removed"] == 1
    lengths = sorted(
        round(p.segments[-1].end[0] - p.segments[0].start[0]) for p in found.graph.pieces
    )
    assert len(lengths) == 2  # both radial tracks stay, held together by the turntable


def test_rule_8_a_loose_track_is_left_out(station: Result) -> None:
    assert station.stats.loose == 1
    loose = [c for c in station.checks if c.kind == CheckKind.LOOSE_PART]
    assert len(loose) == 1 and "0,60 m" in loose[0].title
    assert all(n.at[1] < 1000 for n in station.graph.nodes)


def test_rule_9_numbered_from_the_west_with_anyrails_ids_kept(station: Result) -> None:
    assert [(s.number, s.at[0], s.side) for s in station.switches] == [
        (1, 1100.0, "right"),
        (2, 2250.0, "left"),
        (3, 4000.0, "right"),
        (4, 4800.0, "right"),
    ]
    assert all(s.anyrail for s in station.switches if not s.assumed)
    for m in station.modules:
        for piece in m.graph.pieces:
            assert piece.origin is not None and piece.origin.source == GraphSource.ANYRAIL
            assert piece.origin.ref and piece.origin.ref.replace("+", "").isdigit()


def test_ar2_the_station_tracks_are_numbered_from_the_top(station: Result) -> None:
    numbered = {p.track for p in station.graph.pieces if p.track}
    assert numbered == {"1", "2", "3", "4"} and station.stats.station_tracks == 4
    middle = station.stats.station_middle
    assert middle is not None and 2400 < middle < 3900

    def y_at(track: str) -> float:
        piece = next(
            p
            for p in station.graph.pieces
            if p.track == track
            and p.segments[0].start[0] <= middle
            and p.segments[-1].end[0] >= middle
        )
        return piece.segments[0].start[1]

    assert y_at("1") < y_at("2") < y_at("3") < y_at("4")


# --- 3–4. The filters and the checks ----------------------------------------------------------


def test_3_1_a_backward_piece_goes_and_its_neighbours_meet(station: Result) -> None:
    assert station.stats.backward_removed == 1
    kept = read(station_xml(), DEFAULT.model_copy(update={"backward_length": 10.0}))
    assert kept.stats.backward_removed == 0


def test_3_2_a_tight_flex_curve_is_drawn_again() -> None:
    from cad.anyrail import shapes

    curve = [(500.0, 200.0), (650.0, 200.0), (700.0, 330.0), (850.0, 330.0)]
    assert 200 < shapes.bezier_min_radius(curve) < 400
    d = Drawing(3000, 1000)
    d.module(100, 0, 1500, 700)
    _, a = d.line((150, 200), (500, 200))
    b, c = d.bezier(curve)
    e, _ = d.line((850, 330), (1400, 330))
    d.connect(a, b)
    d.connect(c, e)
    found = read(d.xml())
    assert found.stats.smoothed == 1
    smoothed = [c for c in found.checks if c.title.startswith("Flexbågen ritades om")]
    assert smoothed and "flytt" in smoothed[0].title
    kept = read(d.xml(), DEFAULT.model_copy(update={"tight_radius": 200.0}))
    assert kept.stats.smoothed == 0


def test_3_3_the_kinks_and_the_smallest_radius_are_measured(station: Result) -> None:
    assert station.stats.max_kink is not None and station.stats.min_radius is not None


def test_4_a_switch_over_a_joint_and_a_track_across_it_at_an_angle(station: Result) -> None:
    assert station.stats.switches_over_joint == 1
    over = [s for s in station.switches if s.over_joint]
    assert [s.number for s in over] == [2]
    oblique = [c for c in station.checks if c.kind == CheckKind.OBLIQUE_JOINT]
    assert oblique and "snett" in oblique[0].title


# --- 5. What the import gives ------------------------------------------------------------------


def test_each_module_is_ready_to_be_a_module(station: Result) -> None:
    for m in station.modules:
        assert m.graph.complete or not m.graph.pieces
        for gable in m.gables:
            assert all(0 < t < m.shape.width for t in gable.tracks)
    one = station.modules[0]
    assert [g.tracks for g in one.gables] == [[140.0, 197.0], [134.9, 140.0, 197.0, 450.0]]


def test_the_exports(station: Result) -> None:
    whole = dxf.read(outputs.station_dxf(station))
    assert whole.of("LINE", "ANYRAIL-RITNING") and whole.of("ARC", "SPARMITT")
    one = dxf.read(outputs.module_dxf(station, "m1") or b"")
    assert one.of("TEXT", "GAVEL")
    assert outputs.module_dxf(station, "m99") is None
    rows = outputs.gable_csv(station).decode("utf-8-sig").splitlines()
    assert rows[1] == "Linjen|Ä1;355;140 197;0.0 0.0"
    switches = outputs.switch_csv(station).decode("utf-8-sig").splitlines()
    assert switches[1].split(";")[:7] == [
        "1",
        switches[1].split(";")[1],
        "höger",
        "2200",
        "1",
        "nej",
        "1100",
    ]


def test_the_same_file_and_measures_give_the_same_result() -> None:
    first = read(station_xml())
    second = read(station_xml(), AnyRailMeasures.model_validate(DEFAULT.model_dump()))
    assert [m.model_dump() for m in first.modules] == [m.model_dump() for m in second.modules]
    assert [c.model_dump() for c in first.checks] == [c.model_dump() for c in second.checks]
    assert first.graph == second.graph and first.switches == second.switches
    assert outputs.station_dxf(first) == outputs.station_dxf(second)
    assert outputs.gable_csv(first) == outputs.gable_csv(second)


def test_the_scale_comes_from_the_track_library() -> None:
    layout = reader.read(station_xml(), "station.xml")
    assert interpret.scale_of(layout) == Scale.H0
    assert (
        interpret.scale_of(layout.__class__(**{**layout.__dict__, "library": "ATL02R"}))
        == Scale.ZERO
    )
