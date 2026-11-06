"""trainmeet.meet/1: the example follows the contract, and structural errors are caught."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from contracts import MeetPackage, checksum
from contracts.meet import ClearanceMode, PlaceKind

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def provbanan() -> dict[str, Any]:
    data = json.loads((EXAMPLES / "provbanan.meet.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def problems(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as error:
        MeetPackage.model_validate(data)
    return str(error.value)


def place(data: dict[str, Any], place_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(p for p in data["places"] if p["id"] == place_id)
    return found


def test_the_example_follows_the_contract() -> None:
    package = MeetPackage.model_validate(provbanan())
    assert package.meet.name == "Provbanan"
    assert [p.code for p in package.places if p.kind == PlaceKind.MANNED] == [
        "Nby",
        "Ån",
        "Mlå",
        "Sjv",
    ]
    assert len(package.trains) == 10


def test_the_example_has_what_step_2_needs() -> None:
    package = MeetPackage.model_validate(provbanan())
    manned = [p for p in package.places if p.kind == PlaceKind.MANNED]
    assert all(p.phone for p in manned), "var sin telefon"
    assert any(s.tracks == "double" for s in package.sections), "en dubbelspårssträcka"
    assert [s.clearance_mode for s in package.sections].count(ClearanceMode.DIRECT) == 1
    assert package.meet.clearance_mode == ClearanceMode.REQUESTED
    first, last = manned[0].id, manned[-1].id
    eastbound = [t for t in package.trains if t.calls[0].place == first]
    westbound = [t for t in package.trains if t.calls[0].place == last]
    assert eastbound and westbound, "tåg i båda riktningarna"
    assert any(p.station is not None for p in package.places), "en station med utsida"


def test_checksum_is_the_same_for_the_same_content() -> None:
    data = provbanan()
    shuffled = json.loads(json.dumps(data, sort_keys=True))
    assert checksum(data) == checksum(shuffled)
    changed = copy.deepcopy(data)
    changed["meet"]["name"] = "Provbanan 2"
    assert checksum(changed) != checksum(data)


def test_unknown_fields_are_kept() -> None:
    data = provbanan()
    data["meet"]["kommer_senare"] = {"x": 1}
    place(data, "nby")["ny_egenskap"] = True
    package = MeetPackage.model_validate(data)
    dumped = package.model_dump(mode="json")
    assert dumped["meet"]["kommer_senare"] == {"x": 1}
    assert dumped["places"][0]["ny_egenskap"] is True


def test_another_format_is_refused() -> None:
    data = provbanan()
    data["format"] = "trainmeet.meet/2"
    assert "trainmeet.meet/1" in problems(data)


def test_ids_must_be_unique() -> None:
    data = provbanan()
    data["trains"][1]["id"] = data["trains"][0]["id"]
    assert "Två tåg har id t101" in problems(data)


def test_call_ids_are_unique_across_trains() -> None:
    data = provbanan()
    data["trains"][1]["calls"][0]["id"] = data["trains"][0]["calls"][0]["id"]
    assert "Två tågbesök har id" in problems(data)


def test_a_section_must_point_at_known_places() -> None:
    data = provbanan()
    data["sections"][0]["place_b"] = "okand"
    assert "pekar på en okänd driftplats: okand" in problems(data)


def test_parts_must_run_from_a_to_b() -> None:
    data = provbanan()
    data["sections"][1]["parts"].reverse()
    assert "delsträckorna går inte i följd" in problems(data)


def test_a_remote_place_names_who_runs_it() -> None:
    data = provbanan()
    place(data, "mla")["kind"] = "remote"
    assert "fjärrstyrd men saknar remote_from" in problems(data)
    place(data, "mla")["remote_from"] = "asn"
    MeetPackage.model_validate(data)


def test_a_call_uses_a_track_the_place_has() -> None:
    data = provbanan()
    data["trains"][0]["calls"][0]["track"] = "9"
    assert "har spår 9 som inte finns på nby" in problems(data)


def test_the_track_table_points_at_the_stations_tracks() -> None:
    data = provbanan()
    place(data, "asn")["station"]["track_map"]["2"] = "2b"
    assert "pekar på okänt spår 2b" in problems(data)


def test_the_exit_table_points_at_known_sections_and_exits() -> None:
    data = provbanan()
    place(data, "asn")["station"]["exit_map"]["s-nby-asn"] = "x"
    assert "okänd utfart x" in problems(data)


def test_a_duty_points_at_calls_of_its_own_train() -> None:
    data = provbanan()
    data["duties"][0]["legs"][0]["to_call"] = "t104-sjv"
    assert "okänt tågbesök t104-sjv" in problems(data)


def test_times_are_hours_and_minutes() -> None:
    data = provbanan()
    data["trains"][0]["calls"][0]["departure"] = "6.00"
    problems(data)


def test_the_outside_carries_no_phone_number_field() -> None:
    package = MeetPackage.model_validate(provbanan())
    station = next(p.station for p in package.places if p.station is not None)
    assert "phone" not in station.outside.model_dump()
