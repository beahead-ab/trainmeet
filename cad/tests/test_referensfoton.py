"""The reference stations' photos as test cases for the photo chain (CAD17, CAD-36): new code
must not move the results outside the tolerance.

Each folder under referensfoton/ holds a station's module photos and fall.json: for each photo
the module's form and measures, the corners as the owner confirms them, the sides the owner
taps as Kant 1 and gable A, the gables' tracks from Kant 1, the connections and the switches as
the station has them, how many of them the chain finds today, and the tolerances. The measures
and where each comes from are in fall.json.

Part c3: where code finds the corners within 1 % of the module's width of the hand-set ones
(horn_ur_koden), the photo is read with the code's corners; the hand-set ones stay the truth.
Part c5: code finds them on every photo (past a shadow the module casts, a curve's outline by
its shape), and every photo but one is read with them (las_med_hand, with the reason in the
case's source).
A switch's position is what its source means by it (vaxel_lage): the drawn node where the
diverging arc leaves the straight (AnyRail's), or the blade tips (tungspetsarna, the station
page's); the median distance is held to vaxel_median_mm.

Each photo is read once per run (read() is cached) and the tests share it: a photo takes 6–40 s.

The committed photos carry no camera data, position or other metadata: only the JPEG's JFIF
header.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cad import curves, geometry
from cad.bildkedjan import chain, intake, orient
from cad.bildkedjan import corners as corners_
from cad.bildkedjan.chain import Assembled, Measured
from cad.editor import Drawing
from contracts.cad import (
    Curve,
    DrawingState,
    Gable,
    GableEnd,
    Scale,
    Straight,
    TrackGraph,
)

FOLDER = Path(__file__).parent / "referensfoton"
MAX_BYTES = 4 * 1024 * 1024


def cases() -> list[tuple[Path, dict[str, Any]]]:
    found = []
    for described in sorted(FOLDER.glob("*/fall.json")):
        for case in json.loads(described.read_text(encoding="utf-8"))["fall"]:
            found.append((described.parent / case["foto"], case))
    return found


CASES = cases()
BY_NAME = {case["foto"]: (photo, case) for photo, case in CASES}
STRAIGHT = [c["foto"] for _, c in CASES if c["form"] == "straight"]
CURVES = [c["foto"] for _, c in CASES if c["form"] == "curve"]


def markers(data: bytes) -> list[tuple[int, bytes]]:
    """The JPEG's application and comment segments before the image data."""
    found: list[tuple[int, bytes]] = []
    i = 2
    while i < len(data) - 4 and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:
            break
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            found.append((marker, data[i + 4 : i + 4 + length - 2]))
        i += 2 + length
    return found


@dataclass(frozen=True)
class Read:
    measured: Measured
    assembled: Assembled


def setup_of(case: dict[str, Any]) -> chain.Setup:
    corners = tuple((float(x), float(y)) for x, y in case["horn"])
    width = float(case["bredd"])
    if case["form"] == "curve":
        edge = float(case["radie_spar1"]) + float(case["gavel_a_mm"][0])
        angle = float(case["vinkel"])
        return chain.Setup(
            Scale.H0,
            "curve",
            width,
            width,
            length=edge * math.radians(angle),
            corners=corners,
            kant1=int(case["kant1"]),
            gable_a=int(case["gavel_a"]),
            radius=edge,
            angle=angle,
        )
    return chain.Setup(
        Scale.H0,
        "straight",
        width,
        width,
        length=float(case["langd"]) if case.get("langd_given") else None,
        corners=corners,
        kant1=int(case["kant1"]),
        gable_a=int(case["gavel_a"]),
    )


def aspect_of(case: dict[str, Any]) -> float | None:
    """The module's length over its width, as CAD knows them for a module the photo is for."""
    return chain.aspect_of(case["form"], case.get("bredd"), case.get("langd"))


def bend_of(case: dict[str, Any]) -> corners_.Bend | None:
    """A curve module's outline as CAD knows it: Kant 1's radius, the width and the angle."""
    if case["form"] != "curve":
        return None
    edge = float(case["radie_spar1"]) + float(case["gavel_a_mm"][0])
    return chain.bend_of("curve", float(case["bredd"]), edge, float(case["vinkel"]))


@cache
def prepared_of(name: str) -> chain.Prepared:
    """The photo taken in, and the corners code finds in it, once."""
    photo, case = BY_NAME[name]
    return chain.prepare(
        [intake.take(photo.read_bytes())],
        curve=case["form"] == "curve",
        aspect=aspect_of(case),
        bend=bend_of(case),
    )


@cache
def read(name: str) -> Read:
    """The photo measured as the owner sets it up, and drawn with the code's connections."""
    _, case = BY_NAME[name]
    prepared = prepared_of(name)
    setup = setup_of(case)
    if case.get("horn_ur_koden") and not case.get("las_med_hand"):
        setup = replace(setup, corners=None)
    measured = chain.measure(prepared, setup)
    gables = [
        Gable(end=GableEnd.A, tracks=[float(v) for v in case["gavel_a_mm"]]),
        Gable(end=GableEnd.B, tracks=[float(v) for v in case["gavel_b_mm"]]),
    ]
    if case["form"] == "curve":
        shape: Straight | Curve = Curve(
            radius=float(case["radie_spar1"]),
            angle=float(case["vinkel"]),
            width=float(case["bredd"]),
        )
    else:
        shape = Straight(length=round(measured.length, 1), width=float(case["bredd"]))
    drawing = Drawing.of(Scale.H0, shape, gables, TrackGraph(), DrawingState())
    return Read(measured, chain.assemble(measured, measured.code_pairs(), drawing))


def found_pairs(measured: Measured) -> set[str]:
    return {f"{a}-{b}" for a, b in measured.code_pairs()}


def station_pairs(name: str) -> set[str]:
    """The connections found, each gable track named as the station names it: the nearest of
    the station's tracks at that gable. A track the chain did not find leaves a gap in its own
    numbering, never in the station's."""
    _, case = BY_NAME[name]
    found = read(name)
    names: dict[str, str] = {}
    for t in found.measured.terminals:
        if t.kind != "gable" or t.gable is None:
            names[t.id] = t.id
            continue
        owner = case["gavel_a_mm"] if t.gable == "A" else case["gavel_b_mm"]
        at = found.assembled.gable_positions[t.id]
        nearest = min(range(len(owner)), key=lambda i: abs(owner[i] - at))
        names[t.id] = f"{t.gable}{nearest + 1}"
    return {f"{names[a]}-{names[b]}" for a, b in found.measured.code_pairs()}


def switch_positions(assembled: Assembled, meaning: str = "nod") -> list[tuple[float, float]]:
    """The switches found: their drawn nodes, or their blade tips (tungspetsar)."""
    if meaning == "tungspetsar":
        return sorted((round(x, 1), round(y, 1)) for x, y in assembled.switch_tips.values())
    d = assembled.built.drawing
    return sorted(
        (round(d.nodes[s.node].at[0], 1), round(d.nodes[s.node].at[1], 1))
        for s in d.switches.values()
    )


def matched(case: dict[str, Any], assembled: Assembled) -> list[float]:
    """The station's switches each paired with one found, nearest first: the distances of
    those within the case's tolerance."""
    found = switch_positions(assembled, case.get("vaxel_lage", "nod"))
    pairs = sorted(
        (math.dist(tuple(truth), at), i, j)
        for i, truth in enumerate(case["vaxlar"])
        for j, at in enumerate(found)
    )
    used_t: set[int] = set()
    used_f: set[int] = set()
    distances = []
    for distance, i, j in pairs:
        if i in used_t or j in used_f or distance > case.get("vaxel_tolerans_mm", 0):
            continue
        used_t.add(i)
        used_f.add(j)
        distances.append(round(distance, 1))
    return distances


def arc_radii(assembled: Assembled) -> list[float]:
    """The radii of the drawn pieces' arcs, longest first: a curve module's tracks."""
    arcs = [
        seg
        for piece in assembled.built.drawing.pieces.values()
        for seg in piece.segs
        if isinstance(seg, curves.Arc)
    ]
    return [round(a.radius) for a in sorted(arcs, key=curves.length, reverse=True)]


def test_there_are_reference_photos() -> None:
    assert len(CASES) >= 7
    assert {c["form"] for _, c in CASES} == {"straight", "curve"}


@pytest.mark.parametrize(("photo", "case"), CASES, ids=[c["foto"] for _, c in CASES])
def test_the_committed_photo_has_no_metadata(photo: Path, case: dict[str, Any]) -> None:
    data = photo.read_bytes()
    assert len(data) <= MAX_BYTES
    assert intake.has_metadata(data) == []
    # Only the JFIF header: no EXIF (camera, position), ICC, XMP or comment.
    found = markers(data)
    assert [m for m, _ in found] == [0xE0], case["foto"]
    assert found[0][1].startswith(b"JFIF\x00")


@pytest.mark.parametrize("name", [c["foto"] for _, c in CASES])
def test_the_gables_keep_to_the_stations_measures(name: str) -> None:
    """Every gable track the chain finds is one of the station's, within the tolerance, at the
    gable the station calls by that name; and at least as many as before."""
    _, case = BY_NAME[name]
    found = read(name)
    tolerance = float(case["tolerans_mm"])
    count = 0
    for t in found.measured.terminals:
        if t.kind != "gable" or t.gable is None:
            continue
        owner = case["gavel_a_mm"] if t.gable == "A" else case["gavel_b_mm"]
        at = found.assembled.gable_positions[t.id]
        nearest = min(owner, key=lambda o: abs(o - at))
        assert abs(at - nearest) <= tolerance, (name, t.id, at, nearest)
        count += 1
    assert count >= int(case["minst_hittade"]), (name, count)


@pytest.mark.parametrize("name", STRAIGHT)
def test_the_length_comes_from_the_photo(name: str) -> None:
    _, case = BY_NAME[name]
    found = read(name)
    if case.get("langd_given"):
        # Under 1 px per mm the photo gives no length (bildkedjan step 3).
        assert not found.measured.quality.length_from_photo
        return
    assert abs(found.measured.length - float(case["langd"])) <= float(case["tolerans_mm"])


@pytest.mark.parametrize("name", [c["foto"] for _, c in CASES])
def test_the_stations_connections_are_found(name: str) -> None:
    """The switches' and the crossovers' connections that c1 missed (part c2)."""
    _, case = BY_NAME[name]
    found = station_pairs(name)
    assert set(case["forbindelser"]) <= found, (name, sorted(found))


@pytest.mark.parametrize("name", [c["foto"] for _, c in CASES if c["vaxlar"]])
def test_the_stations_switches_are_found_where_they_are(name: str) -> None:
    _, case = BY_NAME[name]
    distances = matched(case, read(name).assembled)
    assert len(distances) >= int(case["minst_vaxlar"]), (name, distances)


@pytest.mark.parametrize("name", [c["foto"] for _, c in CASES if c.get("vaxel_median_mm")])
def test_the_switches_lie_within_their_median(name: str) -> None:
    """Part c3: the switches read from their legs' rails, fitted with the library's types."""
    _, case = BY_NAME[name]
    distances = matched(case, read(name).assembled)
    assert distances and float(np.median(distances)) <= float(case["vaxel_median_mm"]), (
        name,
        distances,
    )


def corner_distances_mm(name: str) -> list[float]:
    """How far the corners code finds lie from the hand-set ones, mm on the module: the px
    over the photo's px per mm there."""
    _, case = BY_NAME[name]
    prepared = prepared_of(name)
    assert prepared.corners is not None, name
    hand = corners_.clockwise(np.array(case["horn"], np.float64))
    found = corners_.clockwise(np.asarray(prepared.corners, np.float64))
    ppm = read(name).measured.quality.px_per_mm
    return [float(v) / ppm for v in np.linalg.norm(found - hand, axis=1)]


@pytest.mark.parametrize("name", [c["foto"] for _, c in CASES if c.get("horn_ur_koden")])
def test_the_corners_come_from_code(name: str) -> None:
    """Part c3 (bildkedjan step 4): code's corners within 1 % of the module's width of the
    hand-set ones, and the photo read with them keeps to the station's measures above."""
    _, case = BY_NAME[name]
    assert max(corner_distances_mm(name)) <= 0.01 * float(case["bredd"]), (
        name,
        corner_distances_mm(name),
    )


def test_code_finds_the_corners_on_every_photo() -> None:
    """Part c5: on every reference photo, and all but one are read with them (the one read
    with the hand-set ones says why in its source)."""
    assert all(c.get("horn_ur_koden") for _, c in CASES)
    assert sum(bool(c.get("las_med_hand")) for _, c in CASES) <= 1


@pytest.mark.parametrize("name", CURVES)
def test_a_curve_module_straightens_to_its_arcs(name: str) -> None:
    """Kurvmodul (bildkedjan step 6): the corners and the owner's chord and sagitta give the
    measuring image, and its long sides are circular arcs there."""
    found = read(name)
    edges = found.measured.edges
    assert edges is not None and edges.sides
    _, case = BY_NAME[name]
    if case.get("kanter") == "oklara":
        # Grass or scenery over the edges: the check abstains rather than guess.
        assert edges.clear == [], (name, edges)
    assert edges.round, (name, edges)
    # Each track is drawn as arcs near its own radius: track 1's is the longest.
    radius = float(case["radie_spar1"])
    longest = arc_radii(found.assembled)[0]
    assert abs(longest - radius) / radius <= 0.15, (name, longest)


@pytest.mark.parametrize("name", [c["foto"] for _, c in CASES if c["form"] == "straight"])
def test_kant1_and_gable_a_are_derived_only_from_an_asymmetric_profile(name: str) -> None:
    """Tapped the other way round, the chain sees from the gables' tracks which way the module
    lies when its known profile is asymmetric, and says nothing when it is symmetric."""
    _, case = BY_NAME[name]
    measured = read(name).measured
    kant1, gable_a = int(case["kant1"]), int(case["gavel_a"])
    known_a = [float(v) for v in case["gavel_a_mm"]]
    known_b = [float(v) for v in case["gavel_b_mm"]]
    for way in orient.WAYS[1:]:
        wrong_k, wrong_a = orient.sides_for(kant1, gable_a, way)
        tapped = orient.reorient(measured, wrong_k, wrong_a).measured
        found_a, found_b = orient.gable_positions(tapped)
        derived = orient.derive(
            found_a,
            found_b,
            tapped.setup.width_a,
            tapped.setup.width_b,
            known_a,
            known_b,
        )
        if case["harleds"]:
            assert derived.decided, (name, way, derived)
            assert orient.sides_for(wrong_k, wrong_a, derived.way) == (kant1, gable_a)
        else:
            assert not derived.decided or orient.sides_for(wrong_k, wrong_a, derived.way) == (
                kant1,
                gable_a,
            ), (name, way, derived)


def test_a_curve_is_measured_with_kant_1_s_radius() -> None:
    """The curve's Kant 1 radius from the module's: track 1's radius and its distance."""
    curve = Curve(radius=3014, angle=10, width=337)
    assert geometry.edge_radius(curve, 140) == 3154
