"""Manöver, the owner's free panel (STV-46, TKL86): the settings in TKL's API. The symbols come
from one of the standard skins 59, 85 or 95; the owner's labels rename what is shown and the
ids stay; what is shown is on or off. The settings are kept with the station, versioned with
its model, and refused when they name something the panel lacks. Nothing here names a station
(RS13): the stations are found from the model files and picked by what their data has.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.tkl import TklManover, TklStudio, TklTrackPlan
from tkl import track_plan
from tkl.tests.test_app import API, set_up, tkl

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
SETTINGS = API + "/studio/manover"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    return made


def used(client: TestClient, station: str) -> TklTrackPlan:
    answer = client.post(API + f"/referens/{station}/use")
    assert answer.status_code == 200, answer.text
    return TklTrackPlan.model_validate(answer.json())


def with_everything() -> tuple[str, TklTrackPlan]:
    """A reference station whose panel has track names, signals and switches."""
    for station in STATIONS:
        plan = track_plan.reference_view(station)
        if plan is None or plan.panel is None:
            continue
        panel = plan.panel
        if panel.track_names and panel.signals and panel.switches:
            return station, plan
    raise AssertionError("no reference station has tracks, signals and switches")


def owners(plan: TklTrackPlan) -> dict[str, Any]:
    """The owner's settings: 95's symbols, the signal ids hidden, a label of each kind."""
    panel = plan.panel
    assert panel is not None
    return {
        "symbols": "95",
        "shown": {"signal_ids": False, "functions": False},
        "labels": {
            "tracks": {panel.track_names[0].name: "Plattform"},
            "signals": {panel.signals[0].name: "Infart A"},
            "switches": {panel.switches[0].number: "V1"},
        },
    }


def studio(client: TestClient) -> TklStudio:
    return TklStudio.model_validate(client.get(API + "/studio").json())


def test_without_a_model_there_are_no_settings(client: TestClient) -> None:
    assert client.get(SETTINGS).status_code == 404
    assert client.put(SETTINGS, json={"symbols": "59"}).status_code == 404


def test_the_defaults_until_the_owner_chooses(client: TestClient) -> None:
    station, _ = with_everything()
    used(client, station)
    shown = TklManover.model_validate(client.get(SETTINGS).json())
    assert shown == TklManover()
    assert shown.symbols.value == "85"
    assert shown.shown.track_names and shown.shown.train_numbers and shown.shown.functions
    assert shown.labels.signals == {}


def test_the_owner_s_settings_are_saved_and_shown_on_every_screen(client: TestClient) -> None:
    station, plan = with_everything()
    used(client, station)
    given = owners(plan)
    saved = client.put(SETTINGS, json=given)
    assert saved.status_code == 200, saved.text
    shown = TklManover.model_validate(client.get(SETTINGS).json())
    assert shown.symbols.value == "95"
    assert (shown.shown.signal_ids, shown.shown.functions, shown.shown.track_names) == (
        False,
        False,
        True,
    )
    assert shown.labels.model_dump() == given["labels"]
    # The ids stay: the interlocking still knows the signal by its id, not by the label.
    signal = next(iter(given["labels"]["signals"]))
    assert signal in client.get(API + "/stallverk").json()["signals"]
    assert client.get(API + "/stallverk/targets", params={"start": "Infart A"}).status_code == 404
    # Back to the defaults: nothing is stored.
    assert client.put(SETTINGS, json={}).status_code == 200
    assert TklManover.model_validate(client.get(SETTINGS).json()) == TklManover()


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"labels": {"signals": {"Ingen sådan": "X"}}}, "Panelen har inte signalen Ingen sådan."),
        ({"labels": {"switches": {"0000": "X"}}}, "Panelen har inte växeln 0000."),
        ({"labels": {"tracks": {"Spår 999": "X"}}}, "Panelen har inte spåret Spår 999."),
    ],
)
def test_a_label_for_something_the_panel_lacks_is_refused(
    client: TestClient, change: dict[str, Any], said: str
) -> None:
    station, plan = with_everything()
    used(client, station)
    assert client.put(SETTINGS, json=owners(plan)).status_code == 200
    refused = client.put(SETTINGS, json=change)
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["message"] == "Manövers inställningar sparades inte."
    assert said in detail["problems"]
    kept = TklManover.model_validate(client.get(SETTINGS).json())
    assert kept.symbols.value == "95", "nothing changed"


@pytest.mark.parametrize(
    "wrong",
    [
        {"symbols": "68"},
        {"symbols": "manover"},
        {"shown": {"signal_ids": "kanske"}},
        {"labels": {"signals": {"21": ""}}},
        {"labels": {"signals": {"21": "x" * 25}}},
        {"labels": {"signals": {"21": "två\nrader"}}},
    ],
)
def test_settings_of_the_wrong_shape_are_refused(client: TestClient, wrong: dict[str, Any]) -> None:
    station, _ = with_everything()
    used(client, station)
    assert client.put(SETTINGS, json=wrong).status_code == 422
    assert TklManover.model_validate(client.get(SETTINGS).json()) == TklManover()


def test_the_settings_are_versioned_with_the_model(client: TestClient) -> None:
    """A new version of the outside holds the settings as they were, and goes to the cloud with
    the model as the station package's inside (SYNK-30)."""
    station, plan = with_everything()
    used(client, station)
    made = TklStudio.model_validate(client.post(API + "/studio/version").json())
    assert not made.changed
    given = owners(plan)
    assert client.put(SETTINGS, json=given).status_code == 200
    assert studio(client).changed, "the settings changed since the version"
    made = TklStudio.model_validate(client.post(API + "/studio/version").json())
    assert (made.versions[0].number, made.changed) == (2, False)
    store = client.app.state.store  # type: ignore[attr-defined]
    assert store.manover_of_version("lokal", 1) is None
    kept = store.manover_of_version("lokal", 2)
    assert kept is not None and kept.symbols.value == "95"
    assert kept.labels.model_dump() == given["labels"]
    # A change after the version is a change; the same settings again are none.
    assert client.put(SETTINGS, json={**given, "symbols": "59"}).status_code == 200
    assert studio(client).changed
    assert client.put(SETTINGS, json=given).status_code == 200
    assert not studio(client).changed
    # Without the model the settings go too; the version keeps its own.
    assert client.delete(API + "/studio/model").status_code == 200
    assert client.get(SETTINGS).status_code == 404
    assert store.manover_of_version("lokal", 2) is not None


def test_a_new_model_leaves_out_labels_for_what_its_panel_lacks(client: TestClient) -> None:
    station, plan = with_everything()
    assert plan.panel is not None
    signal = plan.panel.signals[0].name
    used(client, station)
    assert client.put(SETTINGS, json=owners(plan)).status_code == 200
    for other in STATIONS:
        made = used(client, other).panel
        if other != station and made is not None and signal not in {x.name for x in made.signals}:
            break
    else:
        raise AssertionError("every reference station has the signal")
    shown = TklManover.model_validate(client.get(SETTINGS).json())
    assert shown.symbols.value == "95", "the owner's choice stays"
    assert shown.labels.signals == {}


def test_the_settings_need_the_pin(client: TestClient) -> None:
    station, _ = with_everything()
    used(client, station)
    client.post(API + "/lock")
    assert client.get(SETTINGS).status_code == 401
    assert client.put(SETTINGS, json={"symbols": "59"}).status_code == 401
