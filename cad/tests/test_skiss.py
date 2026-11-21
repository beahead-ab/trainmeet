"""Profile Skiss (#89 del c2): a hand-drawn track plan read into a module.

In CI only synthetic sketches (cad/bildkedjan/syntetisk.py): two module frames on a sheet, thick
black tracks, coloured pencil, pencil text in Norwegian and leader lines across the tracks,
scanned or photographed on a table.

The reference stations' hand-drawn sketches are not in the repository yet (CAD17 covers the
photos, not the sketches): test_the_reference_sketches reads them where they lie, the folder in
CAD_REFERENSSKISSER or the specification's checkout beside this one, and is skipped when they
are not there. Its cases are in referensskisser/<station>/fall.json; when the sketches may be
committed, they are put beside it and the test reads them from there.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pytest

from cad import curves, sketches
from cad.bildkedjan import chain, intake, skiss, syntetisk
from cad.editor import Drawing
from cad.tests.conftest import API, A, World
from contracts.cad import DrawingState, Gable, GableEnd, GraphSource, Scale, Straight, TrackGraph

PHOTOS = f"{API}/photos"
REFERENCE = Path(__file__).parent / "referensskisser"
SWITCH_MM = skiss.SKETCH_MM
"""A switch's points from a sketch: the ink parts well behind them, so they are read from how
much wider the ink is where the strokes overlap (part c3): within the document's ± 20 mm."""


@cache
def sketch(photographed: bool) -> syntetisk.Sketch:
    return syntetisk.sketch(photographed=photographed)


@cache
def read_first(photographed: bool) -> tuple[skiss.Sheet, skiss.Sketched]:
    """The sketch taken in and straightened, and its left frame read as a 1500 × 600 module
    with Kant 1 its upper side and gable A its left."""
    drawn = sketch(photographed)
    sheet = skiss.prepare(intake.take(drawn.jpeg).pixels)
    assert len(sheet.frames) == 2, len(sheet.frames)
    left = min(sheet.frames, key=lambda q: float(q[:, 0].min()))
    corners = chain.ordered(left, 0, 3)
    return sheet, skiss.read(sheet.pixels, sheet.paper, corners, 1500.0, 600.0, 600.0)


def _nearest(found: list[tuple[float, float]], truth: list[tuple[float, float]]) -> list[float]:
    return [min(math.dist(t, f) for f in found) for t in truth]


@pytest.mark.parametrize("photographed", [False, True], ids=["skannad", "fotograferad"])
def test_a_sketch_gives_its_switches_crossings_and_gables(photographed: bool) -> None:
    drawn = sketch(photographed)
    sheet, found = read_first(photographed)
    nodes = list(found.graph.nodes.values())
    kinds = {kind: sum(n.kind == kind for n in nodes) for kind in {n.kind for n in nodes}}
    # Text, leader lines across the tracks, the frames and the coloured pencil are not tracks:
    # 3 switches, 2 crossings, the siding's end and the diagonal's two, 2 tracks at each gable.
    assert kinds == {"switch": 3, "crossing": 2, "end": 3, "gable": 4}, kinds
    assert skiss.counts(found) == (3, 2)
    switches_at = [n.at for n in nodes if n.kind == "switch"]
    crossings_at = [n.at for n in nodes if n.kind == "crossing"]
    assert max(_nearest(switches_at, drawn.switches)) <= SWITCH_MM
    assert max(_nearest(crossings_at, drawn.crossings)) <= skiss.SKETCH_MM
    for n in nodes:
        if n.kind == "gable":
            truth = drawn.gables_a if n.gable == "A" else drawn.gables_b
            assert min(abs(n.at[1] - t) for t in truth) <= skiss.SKETCH_MM, n
    # Two tracks crossing are one node with 4 ends that the ink merged: code cannot tell a
    # crossing from two switches, so they are asked.
    assert sorted(found.uncertain) == ["X1", "X2"]
    del sheet


def test_the_sketch_becomes_a_proposal_drawn_in_the_module() -> None:
    drawn = sketch(False)
    _, found = read_first(False)
    gables = [
        Gable(end=GableEnd.A, tracks=drawn.gables_a),
        Gable(end=GableEnd.B, tracks=drawn.gables_b),
    ]
    target = Drawing.of(
        Scale.H0, Straight(length=1500, width=600), gables, TrackGraph(), DrawingState()
    )
    built, deviation = skiss.drawing(found, target, {})
    graph = built.graph()
    assert len(graph.switches) == 3
    assert sum(1 for n in graph.nodes if n.type.value == "crossing") == 2
    # Everything from the sketch is a proposal from it until the owner approves (CAD-17).
    assert graph.pieces and all(
        p.origin is not None
        and p.origin.source == GraphSource.SKETCH
        and p.origin.certainty.value != "confirmed"
        for p in graph.pieces
    )
    # Redrawn as straights and arcs that follow the sketch within its ± 20 mm.
    assert deviation and float(np.median(deviation)) <= 3.0
    assert max(deviation) <= skiss.SKETCH_MM


def test_an_x_answered_two_switches_is_drawn_as_two() -> None:
    """Part c3: an uncertain X the owner or the AI calls two switches is split into the two
    nodes with 3 ends the ink merged, each with its two tracks, joined by a piece."""
    drawn = sketch(False)
    _, found = read_first(False)
    gables = [
        Gable(end=GableEnd.A, tracks=drawn.gables_a),
        Gable(end=GableEnd.B, tracks=drawn.gables_b),
    ]

    target = Drawing.of(
        Scale.H0, Straight(length=1500, width=600), gables, TrackGraph(), DrawingState()
    )
    answers = {"X1": skiss.TWO_SWITCHES, "X2": "korsning"}
    built, deviation = skiss.drawing(found, target, answers)
    graph = built.graph()
    assert len(graph.switches) == 5
    assert sum(1 for n in graph.nodes if n.type.value == "crossing") == 1
    assert skiss.counts(found, answers) == (5, 1)
    # The two switches lie where the ink's two nodes were, either side of the X.
    x1 = found.uncertain["X1"]
    near = sorted(
        math.dist(n.at, x1)
        for n in graph.nodes
        if n.type.value == "switch" and math.dist(n.at, x1) <= skiss.SKETCH_MM
    )
    assert len(near) == 2 and all(d > 1.0 for d in near), near
    assert max(deviation) <= skiss.SKETCH_MM
    # Unanswered, or answered a crossing, it stays one (test_the_sketch_becomes_a_proposal…).
    assert skiss.counts(found, {}) == (3, 2)
    # The X's parts survive the job's JSON.
    again = skiss.from_json(skiss.to_json(found), found.image)
    assert skiss.counts(again, answers) == (5, 1)


# --- Från skiss through the service -----------------------------------------------------------


def upload_sketch(world: World, person: UUID, data: bytes) -> dict[str, Any]:
    start = {
        "profile": "skiss",
        "name": "Skissmodul",
        "scale": "H0",
        "kind": "straight",
        "width": 600,
        "length": 1500,
    }
    files: list[tuple[str, Any]] = [
        ("data", (None, json.dumps(start), "application/json")),
        ("images", ("skiss.jpg", data, "image/jpeg")),
    ]
    answer = world.as_(person).post(PHOTOS, files=files)
    assert answer.status_code == 201, answer.text
    found: dict[str, Any] = answer.json()
    return found


def test_fran_skiss_reads_a_frame_with_ai_only_where_code_cannot_decide(world: World) -> None:
    """The sketch is taken in, its frames found; the owner picks the frame that is the module,
    and Kant 1 and gable A. The AI is asked only about the two merged nodes, at the photo's
    price, 12 tokens; the module gets a track plan whose source is the sketch."""
    world.id.answer = lambda prompt: json.dumps(
        {"forbindelser": [], "noder": {"X1": "korsning", "X2": "korsning"}, "osakert": ""}
    )
    job = upload_sketch(world, A.id, sketch(False).jpeg)
    assert job["profile"] == "skiss" and job["state"] == "corners"
    assert len(job["frames"]) == 2
    left = min(range(2), key=lambda i: min(x for x, _ in job["frames"][i]["corners"]))
    frame = job["frames"][left]
    # Kant 1 is the frame's upper side, gable A the side before it: as drawn.
    start = world.id.balance
    body = {
        "corners": frame["corners"],
        "kant1": frame["kant1"],
        "frame": left,
        "ai": True,
        "consent": True,
    }
    answer = world.as_(A.id).post(f"{PHOTOS}/{job['id']}/read", json=body)
    assert answer.status_code == 200, answer.text
    world.app.state.photos.work()
    done = world.as_(A.id).get(f"{PHOTOS}/{job['id']}").json()
    assert done["state"] == "done", done["message"]
    assert done["cost"] == 12 and world.id.balance == start - 12
    assert world.id.reads == 1
    assert done["frame"] == left
    facts = {f["key"]: f for f in done["facts"]}
    assert facts["vaxlar"]["value"] == 3 and facts["vaxlar"]["source"] == "sketch"
    assert facts["korsningar"]["value"] == 2
    assert all(
        f["source"] == "sketch" for k, f in facts.items() if k.startswith(("gavel.", "vaxl"))
    )
    module = world.as_(A.id).get(f"{API}/modules/{job['module']}").json()
    assert module["drawing"]["source"] == "sketch"
    pieces = module["graph"]["pieces"]
    assert pieces and all(
        p["origin"]["source"] == "sketch" and p["origin"]["certainty"] != "confirmed"
        for p in pieces
    )
    assert module["shape"] == {"kind": "straight", "length": 1500.0, "width": 600.0}


def _depot_job(world: World, answer: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The synthetic depot sketch uploaded and read with AI: the AI answers the bridge's
    question as given (part c5)."""

    def ai(prompt: str) -> str:
        assert "Vilka spårändar hänger ihop under bron?" in prompt, prompt
        return json.dumps({"svar": answer, "osakert": ""})

    world.id.answer = ai
    drawn = syntetisk.depot_sketch()
    files: list[tuple[str, Any]] = [
        (
            "data",
            (
                None,
                json.dumps({"profile": "skiss", "kind": "straight", "width": 700, "length": 1500}),
                "application/json",
            ),
        ),
        ("images", ("skiss.jpg", drawn.jpeg, "image/jpeg")),
    ]
    uploaded = world.as_(A.id).post(PHOTOS, files=files)
    assert uploaded.status_code == 201, uploaded.text
    job = uploaded.json()
    # The frame in faint pencil with its corner cut, found by code.
    assert len(job["frames"]) == 1
    frame = job["frames"][0]
    body = {"corners": frame["corners"], "kant1": frame["kant1"], "frame": 0, "ai": True}
    body["consent"] = True
    answered = world.as_(A.id).post(f"{PHOTOS}/{job['id']}/read", json=body)
    assert answered.status_code == 200, answered.text
    world.app.state.photos.work()
    done = world.as_(A.id).get(f"{PHOTOS}/{job['id']}").json()
    assert done["state"] == "done", done["message"]
    return job, done


def _straights(points: list[tuple[float, float]], min_radius: float) -> list[curves.Seg]:
    """The ink as straights every 100 mm: the geometry is another test's (Ren geometri takes
    seconds a piece); here it is the question's way through the service."""
    del min_radius
    kept = [points[0]]
    for p in points[1:]:
        if math.dist(p, kept[-1]) >= 100.0:
            kept.append(p)
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return [curves.Line(a, b) for a, b in itertools.pairwise(kept) if math.dist(a, b) > 0]


def test_a_bridge_code_is_not_sure_of_is_a_hard_question_the_owner_decides(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Part c5: a track parting under a bridge drawn over the tracks. The AI is asked about it
    with fixed answers, as a hard question (CAD18), on a crop around the bridge, inside the
    sketch's 12 tokens. It says the track ends at the bridge: the sketch is read so, and the
    owner is asked, with code's and the AI's answers and the ends marked; answered as code
    reads it, the sketch is read again so. The same question is never asked twice."""
    monkeypatch.setattr(skiss, "_fit", _straights)
    start = world.id.balance
    job, done = _depot_job(world, "slutar")
    assert done["cost"] == 12 and world.id.balance == start - 12
    assert world.id.reads == 1 and world.id.hard == [True]
    asked = [q for q in done["questions"] if q["kind"] == "bridge"]
    assert len(asked) == 1
    question = asked[0]
    assert question["code"] == "grenar" and question["ai"] == "slutar"
    assert question["answer"] is None and question["topology"]
    assert {c["id"] for c in question["choices"]} == {"grenar", "slutar"}
    assert [m["label"] for m in question["marks"]] == ["A", "B", "C", "D", "E"]
    assert {f["key"]: f for f in done["facts"]}["vaxlar"]["value"] == 1
    answer = {"answers": [{"key": question["key"], "answer": "grenar"}]}
    given = world.as_(A.id).post(f"{PHOTOS}/{job['id']}/answers", json=answer)
    assert given.status_code == 200, given.text
    assert {f["key"]: f for f in given.json()["facts"]}["vaxlar"]["value"] == 2
    # A follow-up question on the sketch already paid for: read, and nothing drawn (the
    # meter holds a picture's price while it reads, and it all goes back); asked again, the
    # transcript answers, without reading.
    photos = world.app.state.photos
    with photos.db.transaction() as conn:
        row = photos._row(conn, job["id"])
    sketched, _ = sketches.stored(photos, row)
    choice = sketches.choice_of(sketched, "B1", sketched.asked["B1"])
    assert photos._ask_choice(row, choice) == "slutar"
    assert world.id.reads == 2 and world.id.balance == start - 12
    assert photos._ask_choice(row, choice) == "slutar"
    assert world.id.reads == 2 and world.id.balance == start - 12


def test_fran_skiss_needs_the_modules_measures(world: World) -> None:
    files: list[tuple[str, Any]] = [
        (
            "data",
            (
                None,
                json.dumps({"profile": "skiss", "kind": "straight", "width": 600}),
                "application/json",
            ),
        ),
        ("images", ("skiss.jpg", sketch(False).jpeg, "image/jpeg")),
    ]
    answer = world.as_(A.id).post(PHOTOS, files=files)
    assert answer.status_code == 422
    assert "ramen ger skissen dess skala" in answer.text


# --- The reference stations' sketches, where they lie (local) ---------------------------------


def _sketch_folders() -> list[Path]:
    """Where a station's sketches are looked for: beside its fall.json first, then in the
    folder CAD_REFERENSSKISSER names, then in the specification's checkout beside this one."""
    found = []
    given = os.environ.get("CAD_REFERENSSKISSER")
    if given:
        found.append(Path(given))
    found.append(Path(__file__).resolve().parents[3] / "trainmeet-spec" / "ref")
    return found


def _reference_cases() -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for described in sorted(REFERENCE.glob("*/fall.json")):
        station = described.parent
        data = json.loads(described.read_text(encoding="utf-8"))
        cases.append((station, data))
    return cases


def _image(station: Path, data: dict[str, Any], name: str) -> Path | None:
    here = station / name
    if here.exists():
        return here
    for folder in _sketch_folders():
        there = folder / station.name / str(data["mapp"]) / name
        if there.exists():
            return there
    return None


@pytest.mark.parametrize(
    ("station", "data"), _reference_cases(), ids=[s.name for s, _ in _reference_cases()]
)
def test_the_reference_sketches(station: Path, data: dict[str, Any]) -> None:
    """Every module frame on the station's sketches read: the switches and crossings in all,
    as fall.json gives them, and at least as many as before."""
    images = {s["skiss"]: _image(station, data, s["skiss"]) for s in data["skisser"]}
    if any(path is None for path in images.values()):
        pytest.skip("Referensskisserna finns inte här (de ligger inte i repot än).")
    switches = crossings = 0
    for described in data["skisser"]:
        path = images[described["skiss"]]
        assert path is not None
        sheet = skiss.prepare(intake.take(path.read_bytes()).pixels)
        for module in described["moduler"]:
            # Every frame found by code (part c5), the one whose middle is nearest ram_nara.
            near = np.array(module["ram_nara"], np.float64)
            corners = min(sheet.frames, key=lambda q: float(np.linalg.norm(q.mean(0) - near)))
            assert float(np.linalg.norm(corners.mean(0) - near)) <= 60, module["modul"]
            if "horn" in module:
                # Where the frame's corners were set by hand, code's lie within the sketch's
                # ± 20 mm of them.
                hand = chain.ordered(np.array(module["horn"], np.float64), 0, 3)
                mm_per_px = float(module["langd"]) / float(np.linalg.norm(hand[1] - hand[0]))
                off = np.linalg.norm(chain.ordered(corners, 0, 3) - hand, axis=1) * mm_per_px
                assert float(off.max()) <= skiss.SKETCH_MM, (module["modul"], off)
            found = skiss.read(
                sheet.pixels,
                sheet.paper,
                chain.ordered(corners, 0, 3),
                float(module["langd"]),
                float(module["bredd"]),
                float(module["bredd"]),
            )
            s, c = skiss.counts(found)
            assert s >= int(module["minst_vaxlar"]), (module["modul"], s)
            switches += s
            crossings += c
    assert switches >= int(data["minst_vaxlar"]), switches
    assert crossings == int(data["korsningar"]), crossings
