"""The reference stations' drawings read by the profile Stationsritning (#89 del c4, bildkedjan
R1–R4, Reproducerbarhet: the reference stations are regression tests).

The drawings are not in the repo: CAD17 covers the reference stations' photos only. They are read
where they lie, in the folder CAD_REFERENSRITNINGAR names or in the specification's checkout beside
this one (../trainmeet-spec/ref/<station>/underlag), and the test is skipped without them. Each
station's cases and what the reader gives are in referensritningar/<station>/fall.json, with the
source of every number; when the drawings may be in the repo they go beside it.

An expected value is exact, or [least, most]. A raster drawing with "text_ur" gets the text of
that PDF's text layer as its transcription, scaled to the picture: a pretend AI, so that no real
AI is asked."""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from cad.bildkedjan import ritning, ritning_in
from contracts.cad import ReadBy, SymbolKind

REFERENCE = Path(__file__).parent / "referensritningar"


def _folders() -> list[Path]:
    found = []
    given = os.environ.get("CAD_REFERENSRITNINGAR")
    if given:
        found.append(Path(given))
    found.append(Path(__file__).resolve().parents[3] / "trainmeet-spec" / "ref")
    return found


def _file(station: Path, data: dict[str, Any], name: str) -> Path | None:
    here = station / name
    if here.exists():
        return here
    for folder in _folders():
        there = folder / station.name / str(data["mapp"]) / name
        if there.exists():
            return there
    return None


def _truth_signals(
    station: Path, data: dict[str, Any]
) -> dict[str, tuple[str, int | None, int, str]]:
    """The owner's signal list: name -> type, lamps, address and the way it applies."""
    if "signaler_csv" not in data:
        return {}
    for folder in _folders():
        path = folder / station.name / str(data["signaler_csv"])
        if path.exists():
            break
    else:
        return {}
    found = {}
    with path.open(encoding="utf-8-sig") as rows:
        for row in list(csv.reader(rows, delimiter=";"))[1:]:
            name, kind, address, _, way = row[:5]
            lamps = re.search(r"(\d) lampor", kind)
            signal = (
                "hdvsi"
                if kind.startswith("Huvuddvärg")
                else "dvsi"
                if kind.startswith("Dvärg")
                else "hsi"
            )
            facing = "east" if way in ("österut", "mot stationen") else "west"
            found[name] = (signal, int(lamps.group(1)) if lamps else None, int(address), facing)
    return found


def _cases() -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    cases = []
    for described in sorted(REFERENCE.glob("*/fall.json")):
        data = json.loads(described.read_text(encoding="utf-8"))
        cases += [(described.parent, data, drawing) for drawing in data["ritningar"]]
    return cases


def _within(value: int | list[str], expected: Any, what: str) -> None:
    if (
        isinstance(expected, list)
        and len(expected) == 2
        and all(isinstance(x, int) for x in expected)
    ):
        assert expected[0] <= value <= expected[1], f"{what}: {value}, väntat {expected}"
    else:
        assert value == expected, f"{what}: {value}, väntat {expected}"


@pytest.mark.parametrize(
    ("station", "data", "drawing"),
    _cases(),
    ids=[f"{s.name}-{d['fil']}" for s, _, d in _cases()],
)
def test_the_reference_drawings(
    station: Path, data: dict[str, Any], drawing: dict[str, Any]
) -> None:
    path = _file(station, data, drawing["fil"])
    if path is None:
        pytest.skip("Referensritningarna finns inte här (de ligger inte i repot).")
    taken = ritning_in.take(path.read_bytes())
    page = taken.pages[0]
    if page.kind == "raster":
        if taken.format == "pdf":
            page = ritning_in.pdf_pages(path.read_bytes(), only=1)[0]
        assert page.pixels is not None
        page = ritning_in.raster_page(page.pixels)
        if "text_ur" in drawing:
            source = _file(station, data, drawing["text_ur"])
            assert source is not None
            vector = ritning_in.take(source.read_bytes()).pages[0]
            sx, sy = page.width / vector.width, page.height / vector.height
            page.words = [
                ritning_in.Word(
                    w.text,
                    (w.box[0] * sx, w.box[1] * sy, w.box[2] * sx, w.box[3] * sy),
                    ReadBy.AI,
                )
                for w in vector.words
            ]
    made = ritning.assemble(ritning.read(page), page)
    summary = made.summary
    signals = [s for s in made.graph.symbols if s.kind == SymbolKind.SIGNAL]
    named = [s for s in signals if s.name]
    truth = _truth_signals(station, data)
    right = [
        s
        for s in named
        if s.name in truth
        and truth[s.name][0] == s.signal
        and (truth[s.name][0] != "hsi" or truth[s.name][1] == s.lamps)
        and truth[s.name][2] == s.address
        and truth[s.name][3] == s.facing
    ]
    found: dict[str, Any] = {
        "vaxlar": summary.switches,
        "vaxelnummer": sorted(s.number for s in made.graph.switches if s.number),
        "korsningar": summary.crossings,
        "linjeutfarter": summary.line_exits,
        "stoppbockar": summary.buffer_stops,
        "signaler": len(signals),
        "signaler_med_namn": len(named),
        "signaler_ratt": len(right),
        "spargranser": summary.boundaries,
        "fragor": [q.key for q in made.questions],
        "spar": sorted({p.track for p in made.graph.pieces if p.track}),
    }
    for key, expected in drawing["vantat"].items():
        _within(found[key], expected, f"{drawing['fil']} {key}")
