"""The reference stations' photos as test cases for the photo chain (CAD17, CAD-36): new code
must not move the results outside the tolerance.

Each folder under referensfoton/ holds a station's module photos and fall.json: for each photo
the module's width and length, the corners as the owner confirms them, the side that is Kant 1,
the gables' tracks from Kant 1 as the chain names the gables, how many gable tracks the chain
finds today, and the tolerance. The measures and where each comes from are in fall.json.

The committed photos carry no camera data, position or other metadata: only the JPEG's JFIF
header.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest

from cad.bildkedjan import chain, intake
from cad.editor import Drawing
from contracts.cad import DrawingState, Gable, GableEnd, Scale, Straight, TrackGraph

FOLDER = Path(__file__).parent / "referensfoton"
MAX_BYTES = 4 * 1024 * 1024


def cases() -> list[tuple[Path, dict[str, Any]]]:
    found = []
    for described in sorted(FOLDER.glob("*/fall.json")):
        for case in json.loads(described.read_text(encoding="utf-8"))["fall"]:
            found.append((described.parent / case["foto"], case))
    return found


CASES = cases()


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


def test_there_are_reference_photos() -> None:
    assert len(CASES) >= 4


@pytest.mark.parametrize(("photo", "case"), CASES, ids=[c["foto"] for _, c in CASES])
def test_the_committed_photo_has_no_metadata(photo: Path, case: dict[str, Any]) -> None:
    data = photo.read_bytes()
    assert len(data) <= MAX_BYTES
    assert intake.has_metadata(data) == []
    # Only the JFIF header: no EXIF (camera, position), ICC, XMP or comment.
    found = markers(data)
    assert [m for m, _ in found] == [0xE0], case["foto"]
    assert found[0][1].startswith(b"JFIF\x00")


@pytest.mark.parametrize(("photo", "case"), CASES, ids=[c["foto"] for _, c in CASES])
def test_the_chain_keeps_to_the_owners_measures(photo: Path, case: dict[str, Any]) -> None:
    tolerance = float(case["tolerans_mm"])
    width = float(case["bredd"])
    prepared = chain.prepare([intake.take(photo.read_bytes())])
    setup = chain.Setup(
        Scale.H0,
        "straight",
        width,
        width,
        corners=tuple((float(x), float(y)) for x, y in case["horn"]),
        kant1=int(case["kant1"]),
    )
    measured = chain.measure(prepared, setup)
    # The length from the corners and the width.
    assert abs(measured.length - float(case["langd"])) <= tolerance, measured.length
    drawing = Drawing.of(
        Scale.H0,
        Straight(length=round(measured.length, 1), width=width),
        [Gable(end=GableEnd.A, tracks=[]), Gable(end=GableEnd.B, tracks=[])],
        TrackGraph(),
        DrawingState(),
    )
    assembled = chain.assemble(measured, measured.code_pairs(), drawing)
    found = 0
    for t in measured.terminals:
        if t.kind != "gable" or t.gable is None:
            continue
        owner = case["gavel_a"] if t.gable == "A" else case["gavel_b"]
        at = assembled.gable_positions[t.id]
        nearest = min(owner, key=lambda o: abs(o - at))
        # Every track the chain finds is one of the owner's, within the tolerance.
        assert abs(at - nearest) <= tolerance, (case["foto"], t.id, at, nearest)
        found += 1
    assert found >= int(case["minst_hittade"]), (case["foto"], found)
