"""Studio, Dela stationen through the API (#87 del b): the parts kept as a draft until Använd,
then the station model's, versioned with it and run by the interlocking, never under set
routes; and the reference station with a part round-trips unchanged. Nothing here names a
station (RS13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.station_model import StationModel, StationPart
from contracts.tkl import TklDela, TklDelaState, TklDrawing, TklInterlocking, TklStudio
from tkl.store import LOCAL
from tkl.tests.provstation import bangard
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import with_model
from tkl.tests.test_studio_dela import drawn

D = API + "/studio/dela"
MODELS = Path(__file__).resolve().parents[1] / "referens"


def dela(response: Any) -> TklDela:
    assert response.status_code == 200, response.text
    return TklDela.model_validate(response.json())


def edit(*parts: StationPart) -> dict[str, Any]:
    return {"parts": [p.model_dump(mode="json") for p in parts]}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made, bangard().model_copy(update={"parts": []}))
    return made


def test_dela_stationen_needs_a_model_and_the_pin(tmp_path: Path) -> None:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    assert made.get(D).status_code == 404
    made.post(API + "/lock")
    assert made.get(D).status_code == 401
    assert made.put(D, json=edit()).status_code == 401
    assert made.post(D + "/use").status_code == 401
    assert made.delete(D).status_code == 401


def test_a_part_is_drafted_checked_and_used(client: TestClient) -> None:
    """Made on the station without parts: a draft with its checks, Använd refused while a
    problem stands, then the model's, run by the interlocking and in the outside."""
    empty = dela(client.get(D))
    assert (empty.state, empty.parts) == (TklDelaState.IN_USE, [])
    first = drawn().model_copy(update={"border": []})
    draft = dela(client.put(D, json=edit(first)))
    assert draft.state == TklDelaState.DRAFT
    assert [c.id for c in draft.checks if c.problem] == ["3"], "the border switch's owner"
    refused = client.post(D + "/use")
    assert refused.status_code == 422
    assert refused.json()["detail"]["problems"][0].startswith("Bangården: växel 3")
    assert dela(client.get(D)).state == TklDelaState.DRAFT, "the draft is kept on the computer"
    [found] = draft.found
    street = next(s for s in found.streets if s.track == "51")
    out = next(r for r in found.routes_out if (r.start, r.end) == ("U1", "Ut"))
    part = drawn().model_copy(
        update={"streets": [street.model_copy(update={"name": "Till 51"})], "routes_out": [out]}
    )
    ready = dela(client.put(D, json=edit(part)))
    assert [c.text for c in ready.checks if c.problem] == []
    used = dela(client.post(D + "/use"))
    assert used.state == TklDelaState.IN_USE and used.parts == [part]
    state = TklInterlocking.model_validate(client.get(API + "/stallverk").json())
    [shown] = state.parts
    assert (shown.id, [s.name for s in shown.streets]) == ("bangarden", ["Till 51"])
    studio = TklStudio.model_validate(client.get(API + "/studio").json())
    assert [(p.id, p.name, p.code) for p in studio.draft.parts] == [
        ("bangarden", "Bangården", "Bg")
    ], "the outside lists the part that is its own driftplats (TKL101)"
    assert studio.changed, "Ny version av utsidan takes the parts along"


def test_the_parts_are_versioned_with_the_model(client: TestClient) -> None:
    dela(client.put(D, json=edit(drawn())))
    dela(client.post(D + "/use"))
    assert client.post(API + "/studio/version").status_code == 200
    store = client.app.state.store  # type: ignore[attr-defined]
    _, outside, model = store.latest_package(LOCAL)
    assert model is not None and [p.id for p in model.parts] == ["bangarden"]
    assert [p.id for p in outside.parts] == ["bangarden"]


def test_anvand_waits_for_the_routes_with_409(client: TestClient) -> None:
    """As every model change: never under set routes or train numbers."""
    laid = client.post(API + "/stallverk/route", json={"start": "In", "end": "11"})
    assert laid.status_code == 200 and laid.json()["accepted"], laid.text
    dela(client.put(D, json=edit(drawn())))
    busy = client.post(D + "/use")
    assert busy.status_code == 409 and "Lös ut vägarna" in busy.json()["detail"]
    assert dela(client.get(D)).state == TklDelaState.DRAFT
    route = laid.json()["route"]
    assert client.post(API + "/stallverk/release", json={"route": route}).json()["accepted"]
    assert dela(client.post(D + "/use")).state == TklDelaState.IN_USE


def test_the_draft_is_thrown_away_or_drops_when_it_is_the_models(client: TestClient) -> None:
    dela(client.put(D, json=edit(drawn())))
    thrown = dela(client.delete(D))
    assert (thrown.state, thrown.parts) == (TklDelaState.IN_USE, [])
    same = dela(client.put(D, json=edit()))
    assert same.state == TklDelaState.IN_USE, "the model's parts as they are: no draft"


def test_rita_keeps_the_parts_that_were_used(client: TestClient) -> None:
    """A drawing in Rita's draft gets the parts, so that using it later does not lose them."""
    store = client.app.state.store  # type: ignore[attr-defined]
    model = store.station_model(LOCAL)
    store.save_drawing(LOCAL, TklDrawing(model=model.model_copy(update={"level": 2})))
    dela(client.put(D, json=edit(drawn())))
    dela(client.post(D + "/use"))
    kept = store.drawing(LOCAL)
    assert kept is not None and [p.id for p in kept.model.parts] == ["bangarden"]


def test_the_reference_part_opens_and_round_trips_unchanged(tmp_path: Path) -> None:
    """The reference station with a part, used as one's own: Dela stationen shows its part as
    the model has it, and the same parts sent back change nothing, to the byte."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    models = {
        p.name.removesuffix(".tkl.json"): StationModel.model_validate_json(p.read_text("utf-8"))
        for p in MODELS.glob("*.tkl.json")
    }
    [(station, model)] = [(k, m) for k, m in models.items() if m.parts]
    assert client.post(API + f"/referens/{station}/use").status_code == 200
    store = client.app.state.store  # type: ignore[attr-defined]
    before = store.interlocking(LOCAL)[0]
    shown = dela(client.get(D))
    assert shown.state == TklDelaState.IN_USE and shown.parts == model.parts
    assert [c.text for c in shown.checks if c.problem] == []
    raw = client.get(D).json()["parts"]
    original = json.loads((MODELS / f"{station}.tkl.json").read_text("utf-8"))["parts"]
    again = dela(client.put(D, json={"parts": raw}))
    assert again.state == TklDelaState.IN_USE
    assert [StationPart.model_validate(p) for p in original] == again.parts
    assert store.interlocking(LOCAL)[0] == before, "the model is the same"
    assert dela(client.post(D + "/use")).parts == model.parts


def test_a_browser_that_reorders_the_switch_numbers_changes_no_street(tmp_path: Path) -> None:
    """A browser puts the keys of a map that look like numbers in order, so a street's
    switches come back 127, 130, 132 where the model has them from the end of the area, 132,
    130, 127. Saved, they are in the model's order again, and the street still leads to its
    track; with nothing else changed there is no draft."""
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    [station] = [
        p.name.removesuffix(".tkl.json")
        for p in MODELS.glob("*.tkl.json")
        if StationModel.model_validate_json(p.read_text("utf-8")).parts
    ]
    assert client.post(API + f"/referens/{station}/use").status_code == 200
    raw = client.get(D).json()["parts"]
    for street in raw[0]["streets"]:
        street["positions"] = dict(sorted(street["positions"].items(), key=lambda kv: int(kv[0])))
    same = dela(client.put(D, json={"parts": raw}))
    assert same.state == TklDelaState.IN_USE
    raw[0]["border"] = raw[0]["border"][1:]
    changed = dela(client.put(D, json={"parts": raw}))
    assert changed.state == TklDelaState.DRAFT
    assert not [c.text for c in changed.checks if "leder" in c.text], "every street leads home"
    store = client.app.state.store  # type: ignore[attr-defined]
    model = store.station_model(LOCAL)
    kept = {s.id: list(s.positions) for s in model.parts[0].streets}
    drafted = {s.id: list(s.positions) for s in store.parts_draft(LOCAL)[0].streets}
    assert drafted == kept
