"""The AnyRail import on the reference stations' own files (#91, ANYRAIL-19, the import's
section 7): one station's XML export and another's own AnyRail file, against the specification's
numbers and the prototype's switch list and gable profiles.

The files are not in the repo (they are the owners'; CAD17 covers the reference stations' photos
only). They are read where they lie, in the folder CAD_ANYRAIL_FILER names or in the specification's
checkout beside this one (../trainmeet-spec/ref/<station>/), and the test is skipped without them.
Each station's facts, and where the import differs from the prototype and why, are in
referensanyrail/<station>/fall.json. An expected value is exact, or [least, most]; the joints in
som_prototypen are compared with the prototype's gable profiles, track by track within 2 mm."""

from __future__ import annotations

import csv
import json
import os
import statistics
from pathlib import Path
from typing import Any

import pytest

from cad.anyrail import interpret, reader
from contracts.cad import AnyRailMeasures, Scale

REFERENCE = Path(__file__).parent / "referensanyrail"
SIDES = {"left": "vänster", "right": "höger", "y": "Y"}


def _folders() -> list[Path]:
    found = []
    given = os.environ.get("CAD_ANYRAIL_FILER")
    if given:
        found.append(Path(given))
    found.append(Path(__file__).resolve().parents[3] / "trainmeet-spec" / "ref")
    return found


def _file(station: str, name: str) -> Path | None:
    for folder in _folders():
        for there in (folder / station / name, folder / station / Path(name).name):
            if there.exists():
                return there
    return None


def _cases() -> list[tuple[str, dict[str, Any]]]:
    return [
        (path.parent.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(REFERENCE.glob("*/fall.json"))
    ]


def _within(found: float | None, expected: Any, what: str) -> None:
    assert found is not None, what
    if isinstance(expected, list):
        assert expected[0] <= found <= expected[1], f"{what}: {found} utanför {expected}"
    else:
        assert found == expected, f"{what}: {found}, väntat {expected}"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as rows:
        return list(csv.DictReader(rows, delimiter=";"))


@pytest.mark.parametrize(("station", "case"), _cases(), ids=[s for s, _ in _cases()])
def test_the_reference_station(station: str, case: dict[str, Any]) -> None:
    path = _file(station, str(case["fil"]))
    if path is None:
        pytest.skip(f"{case['fil']} finns inte här: inget referensprov för {station}.")
    layout = reader.read(path.read_bytes(), path.name)
    scale = Scale(case["skala"])
    assert interpret.scale_of(layout) == scale
    result = interpret.interpret(layout, scale, AnyRailMeasures())
    stats = result.stats.model_dump()
    for key, expected in case["facit"].items():
        _within(stats[key], expected, key)
    assert [m.number for m in result.modules] == case["moduler"]
    skipped = case["avvikelser"]

    # Gable profiles: every joint the prototype has, its tracks within 2 mm.
    rows = {r.joint: r for r in result.profiles}
    gables = _file(station, str(case["gavelprofiler"]))
    if gables is not None:
        for row in _rows(gables):
            joint = row["skarv"]
            if joint in skipped["gavelprofiler"]:
                continue
            assert joint in rows, f"Skarven {joint} saknas."
            their_tracks = [float(v) for v in row["spar_mm_fran_bakkant_kant1"].split()]
            my_tracks = list(rows[joint].tracks)
            assert len(my_tracks) == len(their_tracks), f"{joint}: {my_tracks} mot {their_tracks}"
            pairs = zip(my_tracks, their_tracks, strict=True)
            assert all(abs(a - b) <= 2 for a, b in pairs), joint
    for joint in case.get("som_prototypen", []):
        assert gables is None or joint not in skipped["gavelprofiler"], joint
        assert joint in rows, f"Skarven {joint} saknas."
    if "huvudspar" in case:
        main = case["huvudspar"]
        main_tracks = rows[main["skarv"]].tracks[: len(main["spar"])]
        pairs = zip(main_tracks, main["spar"], strict=True)
        assert all(abs(a - b) <= main["mm"] for a, b in pairs)

    # The switch list: by AnyRail's id the type, the radius and the module; the places after the
    # prototype's shift of origin.
    switches = _file(station, str(case["vaxellista"]))
    if switches is None:
        return
    theirs = _rows(switches)
    numbers = {m.key: m.number for m in result.modules}
    mine = {s.anyrail: s for s in result.switches if s.anyrail}
    shifts: list[tuple[float, float]] = []
    for row in theirs:
        found = mine.get(row["anyrail_id"])
        if not row["anyrail_id"] or row["anyrail_id"] in skipped["vaxlar"] or found is None:
            continue
        assert SIDES[found.side] == row["typ"], row["anyrail_id"]
        assert numbers.get(found.module or "") == row["modul"], row["anyrail_id"]
        assert row["antagen"] == "nej" and not found.assumed
        if row["radie_mm"] and found.radius:
            assert abs(found.radius - float(row["radie_mm"])) <= 0.02 * float(row["radie_mm"])
        shifts.append((found.at[0] - float(row["x_mm"]), found.at[1] - float(row["y_mm"])))
    assert shifts, "Ingen växel med AnyRails id att jämföra."
    dx = statistics.median(s[0] for s in shifts)
    dy = statistics.median(s[1] for s in shifts)
    assumed = [r for r in theirs if r["antagen"] == "ja"]
    unmatched = 0
    for row in assumed:
        at = (float(row["x_mm"]) + dx, float(row["y_mm"]) + dy)
        near = [
            s
            for s in result.switches
            if s.assumed and abs(s.at[0] - at[0]) + abs(s.at[1] - at[1]) < 30
        ]
        unmatched += not near
    allowed = sum(1 for k in skipped["vaxlar"] if not k.isdigit() or k not in mine)
    assert unmatched <= allowed + 1, f"{unmatched} antagna växlar i prototypen hittas inte."
