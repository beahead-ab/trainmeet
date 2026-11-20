"""The photo chain's part c2 on synthetic photos (cad/bildkedjan/syntetisk.py): a curve module
read from its chord and sagitta (bildkedjan step 6), its edges checked as arcs; Kant 1 and gable
A chosen, derived from an asymmetric profile and changed after reading at no cost; the switches'
library types and AR3; and a photo under 1 px per mm (step 3).

Each photo is read once per run and shared: the station is read by test_bildkedjan.py's read(),
so both files use the same reading.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from functools import cache
from typing import cast

import numpy as np
import pytest

from cad import checks, curves, geometry, switches, views
from cad.bildkedjan import chain, intake, orient, questions, result, syntetisk
from cad.bildkedjan import corners as corners_
from cad.editor import Drawing
from cad.tests.test_bildkedjan import distances
from cad.tests.test_bildkedjan import read as read_scene
from contracts.cad import (
    CheckKind,
    Curve,
    DrawingState,
    Gable,
    GableEnd,
    PhotoQuestionKind,
    Scale,
    Straight,
    TrackGraph,
)


def _kant1(photo: syntetisk.Photo) -> int:
    """The photo side from A at Kant 1 to B at Kant 1, as the truth has it."""
    found = corners_.clockwise(np.array(photo.corners))
    return int(np.argmin(np.linalg.norm(found - np.array(photo.corners[0]), axis=1)))


def _gables(scene: syntetisk.Scene) -> list[Gable]:
    return [
        Gable(end=GableEnd.A, tracks=scene.gables_a),
        Gable(end=GableEnd.B, tracks=scene.gables_b),
    ]


# --- Kurvmodul (bildkedjan step 6) ---------------------------------------------------------------


@cache
def curve_photo() -> syntetisk.Photo:
    """The curve module photographed by a phone that has taken out its lens's distortion, as
    phones do: the chain finds the lens from the module's straight edges, and a curve module's
    long sides are arcs (syntetisk.CURVE_SHOT)."""
    return syntetisk.take(syntetisk.curve_module_scene(), syntetisk.CURVE_SHOT)


@cache
def curve_prepared() -> chain.Prepared:
    return chain.prepare([intake.take(curve_photo().jpeg)], curve=True)


def curve_setup(corners: np.ndarray | None = None) -> chain.Setup:
    """The owner's setup: the chord and sagitta on track 1 give the radius and angle exactly
    (CAD16), and track 1's distance gives Kant 1's radius."""
    scene = syntetisk.curve_module_scene()
    photo = curve_photo()
    chord, sagitta = syntetisk.curve_measure(scene)
    bend = geometry.from_chord(chord, sagitta)
    edge = bend.radius + scene.gables_a[0]
    given = np.array(photo.corners) if corners is None else corners
    return chain.Setup(
        Scale.H0,
        "curve",
        scene.width_a,
        scene.width_b,
        length=edge * math.radians(bend.angle),
        corners=tuple((float(x), float(y)) for x, y in given),
        kant1=_kant1(photo),
        radius=edge,
        angle=bend.angle,
    )


@cache
def curve_read() -> tuple[chain.Measured, chain.Assembled]:
    scene = syntetisk.curve_module_scene()
    setup = curve_setup()
    measured = chain.measure(curve_prepared(), setup)
    assert setup.radius is not None and setup.angle is not None
    shape = Curve(radius=setup.radius - scene.gables_a[0], angle=setup.angle, width=scene.width_a)
    drawing = Drawing.of(Scale.H0, shape, _gables(scene), TrackGraph(), DrawingState())
    return measured, chain.assemble(measured, measured.code_pairs(), drawing)


def test_a_curve_module_is_read_from_its_chord_and_sagitta() -> None:
    scene = syntetisk.curve_module_scene()
    measured, assembled = curve_read()
    assert chain.pairs_text(measured.code_pairs()) == "A1–B1, A2–B2"
    # Every gable track where the truth has it.
    for t in measured.terminals:
        assert t.kind == "gable" and t.track is not None and t.gable is not None
        truth = (scene.gables_a if t.gable == "A" else scene.gables_b)[t.track - 1]
        assert abs(assembled.gable_positions[t.id] - truth) <= 0.5, t.id
    # The tracks lie on the truth, each drawn as one arc near its own radius.
    found = distances(scene, assembled)
    assert float(np.median(found)) <= 0.2 and float(found.max()) <= 0.6
    arcs = sorted(
        (
            seg.radius
            for p in assembled.built.drawing.pieces.values()
            for seg in p.segs
            if isinstance(seg, curves.Arc)
        ),
        reverse=True,
    )
    assert len(arcs) == 2
    for radius, truth in zip(arcs, (1860.0, 1803.0), strict=True):
        assert abs(radius / truth - 1) <= 0.015, (radius, truth)
    # The long sides straightened are circles where the chord and sagitta put them.
    edges = measured.edges
    assert edges is not None and len(edges.clear) == 2
    assert edges.round and edges.deviation <= 0.5


def test_a_curve_with_wrong_measures_asks_the_owner() -> None:
    """The chord and sagitta measured wrong, giving a radius 10 % too small: straightened with
    them, the long sides are not the arcs they give, so the owner is asked to drag the corners
    again or measure the curve again. (A corner a few millimetres off is not seen this way: the
    four corners give the straightening, and it keeps the edges arcs.)"""
    setup = curve_setup()
    assert setup.radius is not None and setup.angle is not None and setup.length is not None
    wrong = replace(setup, radius=setup.radius * 0.9, angle=setup.angle / 0.9)
    measured = chain.measure(curve_prepared(), wrong)
    assert measured.edges is not None and not measured.edges.round
    scene = syntetisk.curve_module_scene()
    _, good = curve_read()
    crossings = questions.crossing_points(measured.paths, measured.code_pairs())
    decision = result.decide(measured, None, {"forbindelser": "ja"}, crossings)
    found = result.report(measured, good, _gables(scene), None, None, None, decision, {}, False)
    asked = [q for q in found.questions if q.kind == PhotoQuestionKind.CURVE]
    assert len(asked) == 1 and {c.id for c in asked[0].choices} == {"horn", "stammer"}
    answered = result.report(
        measured, good, _gables(scene), None, None, None, decision, {"kurva": "stammer"}, False
    )
    assert not [q for q in answered.questions if q.kind == PhotoQuestionKind.CURVE]


def test_the_corners_of_a_curve_module_are_found_along_its_arcs() -> None:
    """The long sides are arcs: their edge is followed along the arc and the corners are where
    their tangents cross the gables, within a few px of the truth."""
    photo = curve_photo()
    found = curve_prepared().found
    assert found is not None and sorted(found.bent) == [False, False, True, True]
    error = np.linalg.norm(
        corners_.clockwise(found.corners) - corners_.clockwise(np.array(photo.corners)), axis=1
    )
    assert float(error.max()) <= 8.0, error


# --- Kant 1 and gable A (bildkedjan step 4 and 13) -----------------------------------------------


def test_the_sides_are_named_from_kant_1_and_gable_a() -> None:
    corners = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]])
    # As CAD draws a module: gable A is the side before Kant 1.
    plain = chain.ordered(corners, 2)
    assert plain.tolist() == [[10.0, 5.0], [0.0, 5.0], [0.0, 0.0], [10.0, 0.0]]
    # Mirrored: gable A after Kant 1, A at Kant 1 is Kant 1's other end.
    mirrored = chain.ordered(corners, 2, 3)
    assert mirrored.tolist() == [[0.0, 5.0], [10.0, 5.0], [10.0, 0.0], [0.0, 0.0]]
    with pytest.raises(ValueError, match="Gavel A ligger bredvid Kant 1"):
        chain.ordered(corners, 2, 2)
    # Each way round turns into the sides it names; turning back gives the sides again.
    for way in orient.WAYS:
        k, a = orient.sides_for(2, 1, way)
        assert a in ((k + 1) % 4, (k + 3) % 4)
        assert orient.sides_for(k, a, way) == (2, 1)


def test_an_asymmetric_profile_derives_kant_1_and_gable_a_and_a_symmetric_one_asks() -> None:
    station = syntetisk.station_scene()  # 140/197/450 against 140/197/260
    found_a, found_b = list(station.gables_a), list(station.gables_b)
    for way in orient.WAYS:
        # The module read the other way round: what the chain would find.
        a, b = (found_b, found_a) if way.ends else (found_a, found_b)
        if way.sides:
            a, b = [600 - v for v in a], [600 - v for v in b]
        derived = orient.derive(a, b, 600, 600, station.gables_a, station.gables_b)
        assert derived.decided and derived.way == way, (way, derived)
    straight = syntetisk.straight_scene()  # 140/197 at both gables
    for way in orient.WAYS[1:2]:
        derived = orient.derive(
            straight.gables_b, straight.gables_a, 480, 480, straight.gables_a, straight.gables_b
        )
        # A and B alike: never decided between the two ends.
        assert not derived.decided or derived.way.ends is False, (way, derived)
    unknown = orient.derive(found_a, found_b, 600, 600, [], [])
    assert not unknown.decided


def test_mirroring_and_swapping_after_reading_cost_no_new_measuring() -> None:
    """Another Kant 1 or gable A after reading moves the measured module into the new frame:
    the gables' tracks follow, the switches and the connections stay, and nothing is measured
    again (the photo is not read again and no tokens are drawn)."""
    scene, measured, assembled = read_scene("station")
    kant1, gable_a = measured.setup.kant1, measured.setup.gable
    for way in orient.WAYS[1:]:
        k, a = orient.sides_for(kant1, gable_a, way)
        started = time.perf_counter()
        moved = orient.reorient(measured, k, a)
        assert time.perf_counter() - started < 3.0
        new = moved.measured
        assert (new.setup.kant1, new.setup.gable) == (k, a)
        assert new.setup.mirrored == (way.ends != way.sides)
        found_a, found_b = orient.gable_positions(new)
        want_a, want_b = (
            (scene.gables_b, scene.gables_a) if way.ends else (scene.gables_a, scene.gables_b)
        )
        if way.sides:
            want_a, want_b = [600 - v for v in want_a], [600 - v for v in want_b]
        assert np.allclose(sorted(found_a), sorted(want_a), atol=1.0), (way, found_a)
        assert np.allclose(sorted(found_b), sorted(want_b), atol=1.0), (way, found_b)
        # The same connections, named anew.
        renamed = {
            tuple(sorted((moved.labels[p], moved.labels[q]))) for p, q in measured.code_pairs()
        }
        assert renamed == {tuple(sorted(p)) for p in new.code_pairs()}
        # The same measuring image, mirrored or turned: as many pixels, no new photo.
        assert new.image is not None and measured.image is not None
        assert new.image.size == measured.image.size
        if way != orient.Way(True, True):
            continue
        # Drawn again, the switches lie where the old ones were, seen from the new gable A.
        shape = Straight(length=round(new.length, 1), width=600)
        gables = [
            Gable(end=GableEnd.A, tracks=sorted(round(v, 1) for v in found_a)),
            Gable(end=GableEnd.B, tracks=sorted(round(v, 1) for v in found_b)),
        ]
        drawn = chain.assemble(
            new,
            new.code_pairs(),
            Drawing.of(Scale.H0, shape, gables, TrackGraph(), DrawingState()),
        )
        before = sorted(views.switch_infos(assembled.built.drawing), key=lambda s: s.from_a)
        after = sorted(views.switch_infos(drawn.built.drawing), key=lambda s: s.from_a)
        want = sorted((new.length - s.from_a if way.ends else s.from_a) for s in before)
        assert np.allclose([s.from_a for s in after], want, atol=3.0), (way, after, want)


def test_a_mirrored_setup_is_measured_as_drawn_and_turned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chain.measure measures a mirrored module (gable A after Kant 1) as CAD draws it, with the
    ends' widths swapped, and turns the result into the owner's frame: the same photo gives the
    same tracks whichever gable the owner calls A."""
    _, measured, _ = read_scene("station")
    plain = measured.setup
    asked: list[chain.Setup] = []

    def measure_plain(prepared: chain.Prepared, setup: chain.Setup) -> chain.Measured:
        asked.append(setup)
        return measured

    monkeypatch.setattr(chain, "_measure", measure_plain)
    k, a = orient.sides_for(plain.kant1, plain.gable, orient.Way(True, False))
    mirrored = replace(plain, kant1=k, gable_a=a, width_a=plain.width_b, width_b=plain.width_a)
    assert mirrored.mirrored and not plain.mirrored
    turned = chain.measure(cast(chain.Prepared, None), mirrored)
    assert len(asked) == 1 and not asked[0].mirrored
    assert (asked[0].width_a, asked[0].width_b) == (plain.width_a, plain.width_b)
    assert (turned.setup.kant1, turned.setup.gable) == (k, a)
    found_a, found_b = orient.gable_positions(turned)
    plain_a, plain_b = orient.gable_positions(measured)
    assert np.allclose(found_a, plain_b, atol=0.01) and np.allclose(found_b, plain_a, atol=0.01)


# --- The switch library and AR3 (bildkedjan step 15) ---------------------------------------------


def test_each_switch_gets_its_nearest_library_type_and_how_far_off() -> None:
    scene, measured, assembled = read_scene("station")
    crossings = questions.crossing_points(measured.paths, measured.code_pairs())
    decision = result.decide(measured, None, {}, crossings)
    found = result.report(
        measured, assembled, _gables(scene), 1500.0, None, None, decision, {}, False
    )
    facts = [f for f in found.facts if f.key.startswith("vaxel.")]
    assert len(facts) == 3
    for fact in facts:
        assert fact.text is not None
        assert "R 830" in fact.text or "R 970" in fact.text
        assert " %)" in fact.text and "avviker" in fact.text  # the type and the fit's error
        assert "antagen" not in fact.text
        assert fact.certainty.value == "probable"


def test_a_switch_no_type_fits_is_antagen_and_blocks_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AR3: with no library type within 10 %, the photo's switch is antagen (yellow): Att kolla
    has it open, and an open item blocks approval."""
    scene, measured, assembled = read_scene("station")
    monkeypatch.setattr(switches, "DESIGNS", ())
    crossings = questions.crossing_points(measured.paths, measured.code_pairs())
    decision = result.decide(measured, None, {}, crossings)
    found = result.report(
        measured, assembled, _gables(scene), 1500.0, None, None, decision, {}, False
    )
    facts = [f for f in found.facts if f.key.startswith("vaxel.")]
    assert facts and all(
        f.text is not None
        and "ingen känd växeltyp inom 10 %" in f.text
        and f.text.endswith("antagen")
        and f.certainty.value == "uncertain"
        for f in facts
    )
    found_checks = checks.open_items(checks.find(assembled.built.drawing))
    items = [c for c in found_checks if c.kind == CheckKind.SWITCH_ASSUMED]
    assert len(items) == 3 and all(c.assumed for c in items)


# --- Under 1 px per mm (bildkedjan step 3) ------------------------------------------------------


@cache
def low_read() -> tuple[syntetisk.Scene, chain.Measured, chain.Assembled]:
    """The station photographed at 1500 × 1125 px: 0,8 px per mm on the module, a gauge of 13
    px and a rail head of about 1 px."""
    scene = syntetisk.station_scene()
    photo = syntetisk.take(scene, syntetisk.Shot(size=(1500, 1125)))
    prepared = chain.prepare([intake.take(photo.jpeg)])
    setup = chain.Setup(
        Scale.H0,
        "straight",
        600,
        600,
        length=1500.0,
        corners=tuple((float(x), float(y)) for x, y in photo.corners),
        kant1=_kant1(photo),
    )
    measured = chain.measure(prepared, setup)
    drawing = Drawing.of(
        Scale.H0, Straight(length=1500, width=600), _gables(scene), TrackGraph(), DrawingState()
    )
    return scene, measured, chain.assemble(measured, measured.code_pairs(), drawing)


def test_under_1_px_per_mm_the_topology_and_rough_measures_but_no_length() -> None:
    scene, measured, assembled = low_read()
    # The length is the owner's: the photo cannot give it (bildkedjan step 3).
    assert not measured.quality.length_from_photo
    assert measured.quality.widen > 1.0
    # The gables' tracks and the crossover's two switches are found.
    for t in measured.terminals:
        if t.kind != "gable" or t.gable is None or t.track is None:
            continue
        truth = (scene.gables_a if t.gable == "A" else scene.gables_b)[t.track - 1]
        assert abs(assembled.gable_positions[t.id] - truth) <= 1.5, t.id
    assert {("A1", "B1"), ("A1", "B2"), ("A2", "B2"), ("A3", "B3")} <= measured.code_pairs()
    infos = sorted(views.switch_infos(assembled.built.drawing), key=lambda s: s.from_a)
    crossover = [s.at[0] for s in scene.switches[:2]]
    assert len(infos) >= 2
    assert all(any(abs(i.from_a - x) <= 5.0 for i in infos) for x in crossover), infos
