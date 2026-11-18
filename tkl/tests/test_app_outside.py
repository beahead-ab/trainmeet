"""TKL's API for the outside of a station with a model (STD-08, TKL92): Studio's draft is
derived from the model when it is imported or a reference station is used, the list cannot be
written while the model is there, and removing the model makes the last outside the list again.
The model and its outside go together in the station package. Nothing here names a station
(RS13); the expected outsides are in tkl/tests/utsidor/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.station_outside import StationOutside
from contracts.tkl import TklStudio
from tkl.standard import outside_of
from tkl.standard.outside import outside_id
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_model import STATIONS, file_of, model_of

EXPECTED = Path(__file__).resolve().parent / "utsidor"
HAS_MODEL = (
    "Utsidan räknas fram ur stationens spårplan. Ta bort stationsmodellen i Spårplan för att "
    "skriva listan själv."
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    return made


def studio(client: TestClient) -> TklStudio:
    return TklStudio.model_validate(client.get(API + "/studio").json())


def derived(station: str) -> StationOutside:
    """The station's outside under the test station's own id and name."""
    return outside_of(model_of(station), "exb", "Exempelby")


def folded() -> str:
    """A reference station whose line exits are named with text that is no id."""
    return next(
        s for s in STATIONS if any(outside_id(e.id) != e.id for e in model_of(s).line_exits)
    )


def imported(client: TestClient, station: str) -> None:
    answer = client.put(API + "/studio/model", content=file_of(station))
    assert answer.status_code == 200, answer.text


def test_an_imported_model_gives_the_draft_its_outside(client: TestClient) -> None:
    station = folded()
    imported(client, station)
    shown = studio(client)
    assert shown.station_model and shown.changed
    assert shown.draft == derived(station)
    assert (shown.draft.station_id, shown.draft.name) == ("exb", "Exempelby")
    model = model_of(station)
    assert [e.name for e in shown.draft.exits] == [e.id for e in model.line_exits]
    assert [e.id for e in shown.draft.exits] != [e.id for e in model.line_exits]
    assert [t.label for t in shown.draft.tracks] == [t.label for t in model.station_tracks]


def test_the_list_cannot_be_written_while_the_station_has_a_model(client: TestClient) -> None:
    imported(client, STATIONS[0])
    before = studio(client).draft
    data: dict[str, Any] = before.model_dump(mode="json")
    data["tracks"][0]["label"] = "Ett annat spår"
    answer = client.put(API + "/studio", json=data)
    assert answer.status_code == 409
    assert answer.json()["detail"] == HAS_MODEL
    assert studio(client).draft == before


def test_removing_the_model_makes_the_last_outside_the_list_again(client: TestClient) -> None:
    station = folded()
    imported(client, station)
    gone = TklStudio.model_validate(client.delete(API + "/studio/model").json())
    assert not gone.station_model
    assert gone.draft == derived(station), "the last outside, now as the list"
    data: dict[str, Any] = gone.draft.model_dump(mode="json")
    data["exits"][0]["id"] = "V"
    saved = client.put(API + "/studio", json=data)
    assert saved.status_code == 200, saved.text
    assert TklStudio.model_validate(saved.json()).draft.exits[0].id == "V"
    # Importing again derives the outside again; the list is set aside.
    imported(client, station)
    assert studio(client).draft == derived(station)


@pytest.mark.parametrize("station", STATIONS)
def test_using_a_reference_station_gives_its_outside(client: TestClient, station: str) -> None:
    used = client.post(API + f"/referens/{station}/use")
    assert used.status_code == 200, used.text
    shown = studio(client)
    assert shown.station_model
    text = (EXPECTED / f"{station}.utsida.json").read_text("utf-8")
    expected = StationOutside.model_validate_json(text)
    assert shown.draft == expected.model_copy(update={"station_id": "exb", "name": "Exempelby"})


def test_the_station_package_carries_the_model_and_its_outside(client: TestClient) -> None:
    """A new version is made as before (TKL25); the package holds the model as it was then and
    the outside derived from it (SYNK-30)."""
    first, second = STATIONS[0], STATIONS[1]
    imported(client, first)
    made = TklStudio.model_validate(client.post(API + "/studio/version").json())
    assert (made.versions[0].number, made.changed) == (1, False)
    store = client.app.state.store  # type: ignore[attr-defined]
    number, outside, model = store.latest_package("lokal")
    assert (number, outside) == (1, derived(first))
    assert model == model_of(first).model_copy(update={"station_id": "exb", "name": "Exempelby"})
    imported(client, second)
    assert studio(client).changed
    client.post(API + "/studio/version")
    number, outside, model = store.latest_package("lokal")
    assert (number, outside) == (2, derived(second))
    assert model is not None and model.line_exits == model_of(second).line_exits
