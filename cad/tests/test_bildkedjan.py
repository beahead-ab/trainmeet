"""The photo chain on synthetic photos (cad/bildkedjan/syntetisk.py): modules with a known
geometry, photographed by a known camera with perspective, lens distortion, noise, uneven light
and a shadow from outside the module. The measures are checked against the truth, within the
tolerances of the document's photo test (median 0,5 mm after Lås mått).

Each scene is read once and shared by the tests: a photo takes 6–13 s.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import replace
from functools import cache

import numpy as np
import pytest
from PIL import Image

from cad import curves, views
from cad.bildkedjan import chain, intake, measures, questions, result, syntetisk
from cad.bildkedjan import corners as corners_
from cad.editor import Drawing
from contracts.cad import (
    DrawingState,
    Gable,
    GableEnd,
    PhotoQuestionKind,
    Scale,
    Straight,
    TrackGraph,
    Trapezoid,
)


def _corners(prepared: chain.Prepared) -> np.ndarray:
    assert prepared.corners is not None, "Hörnen hittades inte."
    return corners_.clockwise(prepared.corners)


def _truth_kant1(prepared: chain.Prepared, photo: syntetisk.Photo) -> int:
    found = _corners(prepared)
    return int(np.argmin(np.linalg.norm(found - np.array(photo.corners[0]), axis=1)))


@cache
def photo_of(name: str) -> syntetisk.Photo:
    """The scene photographed by the default camera, once."""
    return syntetisk.take(syntetisk.SCENES[name]())


@cache
def read(name: str) -> tuple[syntetisk.Scene, chain.Measured, chain.Assembled]:
    """The scene photographed, taken in as the service does (its original stored as a JPEG and
    read back), measured with the length from the photo, and drawn with the code's connections."""
    scene = syntetisk.SCENES[name]()
    photo = photo_of(name)
    stored = intake.jpeg(intake.take(photo.jpeg).pixels)
    prepared = chain.prepare([intake.take(stored)])
    setup = chain.Setup(
        Scale.H0,
        scene.kind,
        scene.width_a,
        scene.width_b,
        kant1=_truth_kant1(prepared, photo),
    )
    measured = chain.measure(prepared, setup)
    shape: Straight | Trapezoid = (
        Straight(length=round(measured.length, 1), width=scene.width_a)
        if scene.kind == "straight"
        else Trapezoid(
            length=round(measured.length, 1),
            width_a=scene.width_a,
            width_b=scene.width_b,
            offset=round(measured.offset, 1),
        )
    )
    gables = [
        Gable(end=GableEnd.A, tracks=scene.gables_a),
        Gable(end=GableEnd.B, tracks=scene.gables_b),
    ]
    drawing = Drawing.of(Scale.H0, shape, gables, TrackGraph(), DrawingState())
    assembled = chain.assemble(measured, measured.code_pairs(), drawing)
    return scene, measured, assembled


def distances(scene: syntetisk.Scene, assembled: chain.Assembled) -> np.ndarray:
    """How far the truth's centre lines lie from the drawn track plan, every 5 mm."""
    segs = [seg for piece in assembled.built.drawing.pieces.values() for seg in piece.segs]
    truth = [p for r in scene.routes for p in curves.sample_path(r, 5.0)]
    return np.array([min(curves.distance([s], p) for s in segs) for p in truth])


# The tolerances: the median and the largest distance from the truth, in mm.
ACCURACY = {"rak": (0.3, 1.0), "kurva": (0.6, 1.5), "trapets": (0.7, 1.5), "station": (0.3, 1.5)}


@pytest.mark.parametrize("name", list(ACCURACY))
def test_the_track_plan_lies_on_the_truth(name: str) -> None:
    scene, measured, assembled = read(name)
    found = distances(scene, assembled)
    median, most = ACCURACY[name]
    assert float(np.median(found)) <= median, (name, float(np.median(found)))
    assert float(found.max()) <= most, (name, float(found.max()))
    assert measured.quality.tilt == pytest.approx(10.0, abs=0.6)


@pytest.mark.parametrize("name", list(ACCURACY))
def test_the_length_and_the_gables_come_from_the_photo(name: str) -> None:
    scene, measured, assembled = read(name)
    pm = chain.length_plus_minus(measured, assembled.spread) or 0.0
    assert abs(measured.length - scene.length) <= max(1.5, pm), (measured.length, pm)
    assert abs(measured.offset - scene.offset) <= 1.5
    for t in measured.terminals:
        if t.kind != "gable" or t.track is None:
            continue
        truth = (scene.gables_a if t.gable == "A" else scene.gables_b)[t.track - 1]
        at = assembled.gable_positions[t.id]
        assert abs(at - truth) <= 0.5, (t.id, at, truth)
        # The ± covers the truth.
        assert abs(at - truth) <= assembled.gable_plus_minus[t.id] + 0.1, t.id


def test_the_station_has_its_switches_crossing_and_end() -> None:
    scene, measured, assembled = read("station")
    assert chain.pairs_text(measured.code_pairs()) == "A1–B1, A1–B2, A1–E1, A2–B2, A2–E1, A3–B3"
    ends = [t for t in measured.terminals if t.kind == "end"]
    assert len(ends) == 1
    assert math.dist(ends[0].at, scene.ends[0]) <= 5.0
    crossings = questions.crossing_points(measured.paths, measured.code_pairs())
    assert len(crossings) == 1
    assert math.dist(next(iter(crossings.values())), scene.crossings[0]) <= 5.0
    infos = sorted(views.switch_infos(assembled.built.drawing), key=lambda s: s.from_a)
    assert len(infos) == 3
    for info, truth in zip(infos, sorted(scene.switches, key=lambda s: s.at[0]), strict=True):
        assert abs(info.from_a - truth.at[0]) <= 2.5, (info.from_a, truth.at[0])
        # The radius is the library's switch type nearest the truth.
        assert info.matched is not None and f"r{round(truth.radius)}" in info.matched


def test_the_gauge_and_the_sleepers_check_the_scale() -> None:
    _, _, station = read("station")
    assert station.gauge.value == pytest.approx(16.5, abs=0.1)
    assert station.gauge.places >= 20
    assert station.sleepers.straight == pytest.approx(syntetisk.SLEEPER_SPACING, abs=0.05)
    assert station.sleepers.slanting == pytest.approx(syntetisk.SLEEPER_SPACING, abs=0.05)
    assert station.sleepers.agree


def test_small_shifts_of_the_corners_keep_the_topology() -> None:
    """The owner's corners come back from the browser rounded: the topology must not hang on a
    pixel."""
    scene = syntetisk.station_scene()
    photo = photo_of("station")
    prepared = chain.prepare([intake.take(intake.jpeg(intake.take(photo.jpeg).pixels))])
    kant1 = _truth_kant1(prepared, photo)
    rng = np.random.default_rng(5)
    shifted = _corners(prepared) + rng.uniform(-1.0, 1.0, (4, 2))
    setup = chain.Setup(
        Scale.H0,
        "straight",
        scene.width_a,
        scene.width_b,
        corners=tuple((float(x), float(y)) for x, y in shifted),
        kant1=kant1,
    )
    measured = chain.measure(prepared, setup)
    assert chain.pairs_text(measured.code_pairs()) == "A1–B1, A1–B2, A1–E1, A2–B2, A2–E1, A3–B3"


def test_two_photos_of_a_long_module_are_stitched_with_wider_tolerances() -> None:
    scene = syntetisk.long_scene()
    tex = syntetisk.texture(scene)
    shots = [
        syntetisk.Shot(centre=(0.32, 0.5), fill=1.45, turn=4, tilt=8, tilt_toward=10, seed=21),
        syntetisk.Shot(centre=(0.68, 0.5), fill=1.45, turn=6, tilt=9, tilt_toward=200, seed=22),
    ]
    # Phones take the lens out of their JPEGs; a mosaic's photos are not straightened one by one.
    shots = [replace(s, distortion=0.0) for s in shots]
    photos = [syntetisk.take(scene, s, tex) for s in shots]
    prepared = chain.prepare([intake.take(p.jpeg) for p in photos])
    assert prepared.photos == 2 and prepared.mosaic is not None
    found = _corners(prepared)
    kant1 = int(np.argmin([found[i][1] + found[(i + 1) % 4][1] for i in range(4)]))
    measured = chain.measure(prepared, chain.Setup(Scale.H0, "straight", 500, 500, kant1=kant1))
    assert measured.stitch_mm is not None and measured.stitch_mm <= 1.0
    assert abs(measured.length - scene.length) <= 3.0
    assert chain.pairs_text(measured.code_pairs()) == "A1–B1, A2–B2"
    gate = next(g for g in measured.quality.gates if g.key == "stitch")
    assert gate.level == "warn"
    assert measured.quality.widen >= measures.MOSAIC_WIDEN
    # The tracks within the mosaic's tolerance: a few millimetres (what is weaker).
    for t in measured.terminals:
        assert abs(t.at[1] - (200 if t.track == 1 else 257)) <= 8.0, (t.id, t.at)


def test_the_same_photo_gives_the_same_measures() -> None:
    """Reproducibility: fixed seeds and one thread, so the same photo gives the same job."""
    photo = photo_of("rak")
    twice = []
    for _ in range(2):
        prepared = chain.prepare([intake.take(photo.jpeg)])
        setup = chain.Setup(Scale.H0, "straight", 480, 480, kant1=_truth_kant1(prepared, photo))
        measured = chain.measure(prepared, setup)
        twice.append(json.dumps(chain.to_json(measured), sort_keys=True))
    assert twice[0] == twice[1]


# --- The gates -----------------------------------------------------------------------------


def test_the_intake_takes_out_exif_and_gps_and_refuses_what_it_cannot_read() -> None:
    photo = photo_of("rak")
    assert {"EXIF", "GPS"} <= set(intake.has_metadata(photo.jpeg))
    taken = intake.take(photo.jpeg)
    assert taken.focal_35mm == pytest.approx(26.0)
    assert intake.has_metadata(intake.jpeg(taken.pixels)) == []
    assert intake.has_metadata(intake.png(taken.pixels)) == []
    with pytest.raises(intake.Refused) as heic:
        intake.take(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
    assert heic.value.status == 415
    with pytest.raises(intake.Refused) as large:
        intake.take(b"\xff\xd8" + b"\x00" * (intake.MAX_BYTES + 1))
    assert large.value.status == 413
    with pytest.raises(intake.Refused):
        intake.take(b"inte ett foto")


def test_the_intake_turns_the_photo_upright_as_its_exif_says() -> None:
    image = Image.new("RGB", (40, 20), (200, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # turned a quarter
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif.tobytes())
    taken = intake.take(out.getvalue())
    assert taken.pixels.shape[:2] == (40, 20)


def test_the_quality_gate_widens_and_refuses() -> None:
    scene = syntetisk.straight_scene()
    # Small: low resolution, wider tolerances.
    small = syntetisk.take(scene, syntetisk.Shot(size=(2000, 1500)))
    prepared = chain.prepare([intake.take(small.jpeg)])
    measured = chain.measure(
        prepared, chain.Setup(Scale.H0, "straight", 480, 480, kant1=_truth_kant1(prepared, small))
    )
    gate = next(g for g in measured.quality.gates if g.key == "resolution")
    assert gate.level == "low"
    assert measured.quality.widen > 1.0
    assert not measured.quality.length_from_photo or measured.quality.px_per_mm >= 1.0
    # Too slanted: a new photo.
    slanted = syntetisk.take(scene, syntetisk.Shot(tilt=40.0, fill=0.6))
    prepared = chain.prepare([intake.take(slanted.jpeg)])
    with pytest.raises(chain.Stop, match="snett"):
        chain.measure(
            prepared,
            chain.Setup(Scale.H0, "straight", 480, 480, kant1=_truth_kant1(prepared, slanted)),
        )


def test_blur_is_measured() -> None:
    import cv2

    photo = photo_of("rak")
    gray = cv2.cvtColor(photo.pixels, cv2.COLOR_BGR2GRAY)
    sharp = measures.blur(gray)
    blurred = measures.blur(cv2.GaussianBlur(gray, (0, 0), 6))
    assert sharp < measures.SHARPNESS_WARN <= blurred


# --- What AI may answer -----------------------------------------------------------------------


LABELS = ["A1", "A2", "B1", "B2", "E1"]


def test_the_ai_answer_is_read_failing_closed() -> None:
    good = {
        "forbindelser": [["A1", "B1"], ["B2", "A2"]],
        "noder": {"X1": "korsning"},
        "osakert": "",
    }
    reading = questions.understand("Här är svaret: " + json.dumps(good), LABELS, ["X1"])
    assert reading.pairs == {("A1", "B1"), ("A2", "B2")}
    assert reading.nodes == {"X1": "korsning"}
    for bad in (
        "inget svar",
        json.dumps({**good, "matt": 12}),  # a key outside the form
        json.dumps({**good, "forbindelser": [["A1", "Q9"]]}),  # an end that is not marked
        json.dumps({**good, "forbindelser": [["A1", "A1"]]}),
        json.dumps({**good, "noder": {"X1": "tre-vaxlar"}}),  # not a fixed answer
        json.dumps({**good, "noder": {"X7": "korsning"}}),
        json.dumps({**good, "osakert": "x" * 401}),
        '{"forbindelser": [], "noder": {}, "osakert": NaN}',
        json.dumps(good) + " " * questions.MAX_ANSWER,
    ):
        with pytest.raises(questions.Unreadable):
            questions.understand(bad, LABELS, ["X1"])


def test_without_ai_the_owner_gets_the_questions() -> None:
    _, measured, _ = read("station")
    crossings = questions.crossing_points(measured.paths, measured.code_pairs())
    decision = result.decide(measured, None, {}, crossings)
    kinds = {q.kind for q in decision.questions}
    assert PhotoQuestionKind.CONNECTION in kinds and PhotoQuestionKind.NODE in kinds
    summary = next(q for q in decision.questions if q.key == "forbindelser")
    assert summary.ai is None and "Ingen AI har läst fotot" in summary.text
    assert decision.connections == measured.code_pairs()
    # The owner's answer counts: a crossing stays a crossing.
    node = next(q for q in decision.questions if q.kind == PhotoQuestionKind.NODE)
    answered = result.decide(
        measured, None, {node.key: "korsning", "forbindelser": "ja"}, crossings
    )
    assert all(q.answer for q in answered.questions if q.key in (node.key, "forbindelser"))


def test_ai_and_code_disagreeing_ask_the_owner_and_the_ai_draws_the_draft() -> None:
    _, measured, _ = read("station")
    code = measured.code_pairs()
    crossings = questions.crossing_points(measured.paths, code)
    ai = questions.AiReading(pairs=set(code) - {("A2", "E1")}, nodes={"X1": "tva-vaxlar"}, note="")
    decision = result.decide(measured, ai, {}, crossings)
    keys = {q.key for q in decision.questions}
    assert "forbindelse:a2-e1" in keys and "nod:x1" in keys
    assert ("A2", "E1") not in decision.connections  # the AI's answer draws the draft (CAD2)
    agreed = result.decide(
        measured, questions.AiReading(set(code), {"X1": "korsning"}, ""), {}, crossings
    )
    assert agreed.questions == []
