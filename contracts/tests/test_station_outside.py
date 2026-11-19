"""trainmeet.station-outside/1: what TKL Studio publishes about a station."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from contracts import StationOutside

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "asen.station-outside.json"


def asen() -> dict[str, Any]:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_example_follows_the_contract() -> None:
    outside = StationOutside.model_validate(asen())
    assert outside.station_id == "asen"
    assert [t.id for t in outside.tracks] == ["1", "2", "3"]
    assert {e.side for e in outside.exits} == {"left", "right"}


def test_two_tracks_cannot_share_an_id() -> None:
    data = asen()
    data["tracks"][1]["id"] = "1"
    with pytest.raises(ValidationError, match="Två stationsspår har samma id"):
        StationOutside.model_validate(data)


def test_an_exit_points_at_the_stations_tracks() -> None:
    data = asen()
    data["exits"][0]["tracks"] = ["1", "7"]
    with pytest.raises(ValidationError, match="okända spår: 7"):
        StationOutside.model_validate(data)


def test_a_station_needs_tracks_and_exits() -> None:
    data = asen()
    data["exits"] = []
    with pytest.raises(ValidationError):
        StationOutside.model_validate(data)


def test_the_parts_that_are_their_own_places_are_optional() -> None:
    """TKL101, PLAN-34: an outside from before parts reads with none; a part has an id and a
    name, and a code only if the owner gives one."""
    assert StationOutside.model_validate(asen()).parts == []
    data = asen()
    data["parts"] = [{"id": "bangard", "name": "Åsens bangård"}]
    [part] = StationOutside.model_validate(data).parts
    assert (part.id, part.name, part.code) == ("bangard", "Åsens bangård", None)


def test_two_parts_cannot_share_an_id() -> None:
    data = asen()
    data["parts"] = [{"id": "bangard", "name": "Bangården"}, {"id": "bangard", "name": "Depån"}]
    with pytest.raises(ValidationError, match="Två delar har samma id"):
        StationOutside.model_validate(data)
