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


# --- Fjärrstyrning (#36, TKL46, FR10, FR16, FR24, FR31) ------------------------------------------


def remote(data: dict[str, Any]) -> dict[str, Any]:
    """Åsen with a remote catalogue, two automats and the overview."""
    data["remote_routes"] = [
        {"id": "A-1", "start": "A", "end": "1", "exit": "v", "track": "1", "direction": "in"},
        {"id": "1-B", "start": "N1", "end": "B", "exit": "o", "track": "1", "direction": "out"},
    ]
    data["automats"] = [
        {"code": "A3", "kind": "a3", "default": True},
        {"code": "L01", "kind": "local_release"},
    ]
    data["overview"] = {
        "columns": 6,
        "rows": 2,
        "tracks": [{"id": "t1", "row": 0, "start": 0, "end": 6, "track": "1", "platform": True}],
        "links": [{"id": "l1", "from_row": 0, "from_column": 1, "to_row": 1, "to_column": 2}],
        "signals": [{"name": "A", "row": 0, "column": 0, "towards": "right"}],
        "exits": [{"exit": "v", "row": 0, "column": 0}, {"exit": "o", "row": 0, "column": 6}],
        "routes": {"A-1": ["t1"]},
    }
    data["remote_receivers"] = ["remote"]
    return data


def test_an_old_outside_has_no_catalogue_and_still_reads() -> None:
    outside = StationOutside.model_validate(asen())
    assert outside.remote_routes == [] and outside.automats == []
    assert outside.overview is None and outside.remote_receivers == []


def test_the_catalogue_points_at_the_stations_tracks_and_exits() -> None:
    outside = StationOutside.model_validate(remote(asen()))
    assert [(r.id, r.direction) for r in outside.remote_routes] == [("A-1", "in"), ("1-B", "out")]
    assert outside.overview is not None and outside.overview.routes == {"A-1": ["t1"]}
    data = remote(asen())
    data["remote_routes"][0]["track"] = "9"
    with pytest.raises(ValidationError, match="okänt spår: 9"):
        StationOutside.model_validate(data)
    data = remote(asen())
    data["remote_routes"][1]["exit"] = "x"
    with pytest.raises(ValidationError, match="okänd utfart: x"):
        StationOutside.model_validate(data)
    data = remote(asen())
    data["remote_routes"][1]["id"] = "A-1"
    with pytest.raises(ValidationError, match="samma id"):
        StationOutside.model_validate(data)


def test_one_a3_per_station_and_one_code_per_automat() -> None:
    data = remote(asen())
    data["automats"].append({"code": "A33", "kind": "a3"})
    with pytest.raises(ValidationError, match="bara en A3"):
        StationOutside.model_validate(data)
    data = remote(asen())
    data["automats"].append({"code": "a3", "kind": "a1"})
    with pytest.raises(ValidationError, match="samma kod"):
        StationOutside.model_validate(data)


def test_the_overview_draws_inside_its_grid_and_only_the_catalogue() -> None:
    data = remote(asen())
    data["overview"]["tracks"][0]["end"] = 7
    with pytest.raises(ValidationError, match="utanför översikten"):
        StationOutside.model_validate(data)
    data = remote(asen())
    data["overview"]["routes"]["B-9"] = ["t1"]
    with pytest.raises(ValidationError, match="utanför katalogen"):
        StationOutside.model_validate(data)
    data = remote(asen())
    data["overview"]["routes"]["A-1"] = ["t9"]
    with pytest.raises(ValidationError, match="okända bitar"):
        StationOutside.model_validate(data)
    data = remote(asen())
    data["overview"]["tracks"][0]["track"] = "9"
    with pytest.raises(ValidationError, match="ritar okända spår"):
        StationOutside.model_validate(data)
