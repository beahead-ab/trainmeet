"""TKL's API for the station's model and the reference stations (#83): Studio imports a model
file, checks it and keeps it with the station; the level follows; the reference stations can be
looked at and used as one's own. Nothing here names a station (RS13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.station_model import StationModel, dump
from contracts.tkl import TklReference, TklStudio, TklTrackPlan
from tkl.tests.test_app import API, set_up, tkl

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))


def file_of(station: str) -> str:
    return (MODELS / f"{station}.tkl.json").read_text("utf-8")


def model_of(station: str) -> StationModel:
    return StationModel.model_validate_json(file_of(station))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    return made


def level(client: TestClient) -> int:
    state = client.get(API + "/state").json()
    return int(state["station"]["level"])


def studio(client: TestClient) -> TklStudio:
    return TklStudio.model_validate(client.get(API + "/studio").json())


def test_studio_imports_a_model_and_the_level_follows(client: TestClient) -> None:
    assert client.get(API + "/studio/model").status_code == 404
    station = next(s for s in STATIONS if model_of(s).level == 2)
    answer = client.put(
        API + "/studio/model",
        content=file_of(station),
        headers={"Content-Type": "application/json"},
    )
    assert answer.status_code == 200, answer.text
    shown = TklTrackPlan.model_validate(answer.json())
    assert shown.checks.problems == []
    assert shown.summary.station_id == "exb", "the station's own id and name"
    assert shown.summary.name == "Exempelby"
    assert shown.panel is not None
    assert sum(shown.routes.values()) == len(shown.route_list) > 0
    assert level(client) == 2
    assert TklTrackPlan.model_validate(client.get(API + "/studio/model").json()) == shown
    # Kept with the station, and versioned with the outside (SYNK-30).
    before = studio(client)
    assert before.station_model and before.changed
    after = TklStudio.model_validate(client.post(API + "/studio/version").json())
    assert not after.changed and after.versions[0].number == 1
    store = client.app.state.store  # type: ignore[attr-defined]
    number, _, kept = store.latest_package("lokal")
    assert number == 1 and kept is not None and kept.station_id == "exb"
    # Back to level 0.
    gone = TklStudio.model_validate(client.delete(API + "/studio/model").json())
    assert not gone.station_model and gone.changed
    assert level(client) == 0


def test_a_level_1_model_makes_a_level_1_station(client: TestClient) -> None:
    station = next(s for s in STATIONS if model_of(s).level == 1)
    answer = client.put(API + "/studio/model", content=file_of(station))
    assert answer.status_code == 200, answer.text
    assert level(client) == 1


def test_a_broken_model_is_refused_with_its_problems(client: TestClient) -> None:
    station = STATIONS[0]
    data: dict[str, Any] = dump(model_of(station))
    data["switches"][0]["trunk"] = None
    answer = client.put(API + "/studio/model", content=json.dumps(data))
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["message"].startswith("Stationsmodellen kan inte köras")
    number = data["switches"][0]["number"]
    assert f"Växel {number} saknar stam." in detail["problems"]
    assert client.get(API + "/studio/model").status_code == 404, "not kept"
    assert level(client) == 0


def test_a_file_that_is_not_a_model_is_refused(client: TestClient) -> None:
    answer = client.put(API + "/studio/model", content='{"format": "något annat"}')
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["message"] == "Filen är inte en stationsmodell (trainmeet.station-model/1)."
    assert detail["problems"]
    assert client.put(API + "/studio/model", content="inte json").status_code == 422


def test_the_reference_stations_are_listed_and_can_be_looked_at(client: TestClient) -> None:
    listed = [TklReference.model_validate(r) for r in client.get(API + "/referens").json()]
    assert [r.id for r in listed] == STATIONS
    assert [r.name for r in listed] == [model_of(s).name for s in STATIONS]
    for reference in listed:
        answer = client.get(API + f"/referens/{reference.id}")
        assert answer.status_code == 200, answer.text
        shown = TklTrackPlan.model_validate(answer.json())
        assert shown.checks.problems == []
        assert shown.summary.station_id == reference.id
        assert shown.panel is not None
        assert shown.panel.source.value == ("plan" if reference.plan else "engine")
        assert sum(shown.routes.values()) == len(shown.route_list) > 0
    assert client.get(API + "/referens/ingenstans").status_code == 404
    assert level(client) == 0, "looking changes nothing"


def test_a_reference_station_can_be_used_as_mine(client: TestClient) -> None:
    for station in STATIONS:
        answer = client.post(API + f"/referens/{station}/use")
        assert answer.status_code == 200, answer.text
        shown = TklTrackPlan.model_validate(answer.json())
        assert shown.summary.station_id == "exb"
        assert level(client) == min(model_of(station).level, 2)
        assert len(shown.route_list) == len(
            TklTrackPlan.model_validate(client.get(API + f"/referens/{station}").json()).route_list
        )
    assert client.post(API + "/referens/ingenstans/use").status_code == 404


def test_the_model_and_the_reference_stations_need_the_pin(tmp_path: Path) -> None:
    made = tkl(tmp_path)
    set_up(made)
    made.post(API + "/lock")
    assert made.get(API + "/referens").status_code == 401
    assert made.get(API + "/studio/model").status_code == 401
    assert made.put(API + "/studio/model", content=file_of(STATIONS[0])).status_code == 401
    assert made.post(API + f"/referens/{STATIONS[0]}/use").status_code == 401
