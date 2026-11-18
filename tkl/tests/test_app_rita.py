"""Rita's API (#85 del a) under /api/tkl/1/studio/rita: a drawing is kept as a draft, problems
and all; Använd ritningen makes it the station's model only without problems and never while
the interlocking has set routes; a station's model opens as a drawing and comes back the same.
Nothing here names a station (RS13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.station_model import NodeType, to_json
from contracts.tkl import TklDrawing, TklDrawingState, TklInterlocking, TklRita, TklStudio
from tkl.tests.ritning import drawing
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_studio_rita import STATIONS, broken_plan, reference

R = API + "/studio/rita"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    return made


def rita(answer: Any) -> TklRita:
    assert answer.status_code == 200, answer.text
    return TklRita.model_validate(answer.json())


def put(client: TestClient, given: TklDrawing) -> TklRita:
    return rita(client.put(R, content=given.model_dump_json()))


def level(client: TestClient) -> int:
    return int(client.get(API + "/state").json()["station"]["level"])


def broken() -> TklDrawing:
    """The drawing with its buffer stop taken away: a track that ends in the air."""
    good = drawing()
    nodes = [
        n.model_copy(update={"type": NodeType.JOINT}) if n.type == NodeType.BUFFER_STOP else n
        for n in good.model.nodes
    ]
    return drawing(nodes=nodes)


def neighbours() -> TklDrawing:
    """The drawing with a neighbour at each exit: a change that is no problem."""
    exits = drawing().model.line_exits
    return drawing(line_exits=[e.model_copy(update={"neighbour": "Västby"}) for e in exits])


def test_a_new_station_starts_with_an_empty_grid(client: TestClient) -> None:
    shown = rita(client.get(R))
    assert shown.state == TklDrawingState.NEW
    assert shown.drawing.model.station_id == "exb" and shown.drawing.model.pieces == []
    assert shown.drawing.model.panel is not None and shown.drawing.model.panel.grid.dx == 24
    assert not shown.drawing.proposal
    assert client.post(R + "/use").status_code == 404


def test_a_draft_is_kept_with_its_problems_and_cannot_be_used(client: TestClient) -> None:
    shown = put(client, broken())
    assert shown.state == TklDrawingState.DRAFT
    assert shown.drawing.model.station_id == "exb", "the station's own id and name"
    assert shown.loose == ["Stoppbock 1"]
    assert any(f.problem and f.text.startswith("Spåret slutar") for f in shown.findings)
    # Kept on the computer: the same draft comes back.
    assert rita(client.get(R)).drawing == shown.drawing
    used = client.post(R + "/use")
    assert used.status_code == 422
    detail = used.json()["detail"]
    assert detail["message"] == "Ritningen kan inte användas än. Rätta problemen först."
    assert "Noden Stoppbock 1 ska ha två spårbitar men har 1." in detail["problems"]
    assert level(client) == 0
    assert client.get(API + "/studio/model").status_code == 404


def test_using_the_drawing_makes_it_the_station_s_model(client: TestClient) -> None:
    shown = put(client, drawing())
    assert shown.state == TklDrawingState.DRAFT
    assert sum(shown.routes.values()) == 6
    used = rita(client.post(R + "/use"))
    assert used.state == TklDrawingState.IN_USE
    assert level(client) == 2
    assert client.get(API + "/studio/model").json()["summary"]["plan"] is True
    kept = client.app.state.store.station_model("lokal")  # type: ignore[attr-defined]
    assert kept is not None and kept.panel is not None and kept.station_id == "exb"
    assert used.model == kept
    # The outside is derived from it (TKL92), ready for a new version (STUDIO-06).
    studio = TklStudio.model_validate(client.get(API + "/studio").json())
    assert studio.station_model and studio.changed
    assert [t.id for t in studio.draft.tracks] == ["1", "2"]
    assert [e.id for e in studio.draft.exits] == ["A", "B"]
    version = TklStudio.model_validate(client.post(API + "/studio/version").json())
    assert version.versions[0].number == 1 and not version.changed
    # And Ställverket runs it.
    state = TklInterlocking.model_validate(client.get(API + "/stallverk").json())
    assert state.level == 2 and "S1v" in state.sections
    # The drawing of the model in use is no draft; saving it unchanged keeps it in use.
    again = rita(client.get(R))
    assert again.state == TklDrawingState.IN_USE
    assert put(client, again.drawing).state == TklDrawingState.IN_USE
    assert client.app.state.store.drawing("lokal") is None  # type: ignore[attr-defined]


def test_a_draft_can_be_thrown_away(client: TestClient) -> None:
    put(client, drawing())
    rita(client.post(R + "/use"))
    assert put(client, neighbours()).state == TklDrawingState.DRAFT
    back = rita(client.delete(R))
    assert back.state == TklDrawingState.IN_USE
    assert back.drawing.model.line_exits[0].neighbour is None


def test_the_drawing_is_not_used_while_the_interlocking_has_routes(client: TestClient) -> None:
    put(client, drawing())
    rita(client.post(R + "/use"))
    laid = client.post(API + "/stallverk/route", json={"start": "A1", "end": "1Ö"})
    assert laid.status_code == 200 and laid.json()["accepted"], laid.text
    assert put(client, neighbours()).state == TklDrawingState.DRAFT, "a draft is always kept"
    refused = client.post(R + "/use")
    assert refused.status_code == 409
    assert "Lös ut vägarna" in refused.json()["detail"]
    assert rita(client.get(R)).state == TklDrawingState.DRAFT, "the draft stays"
    route = client.get(API + "/stallverk").json()["routes"][0]["id"]
    assert client.post(API + "/stallverk/release", json={"route": route}).json()["accepted"]
    assert rita(client.post(R + "/use")).state == TklDrawingState.IN_USE


@pytest.mark.parametrize("station", STATIONS)
def test_a_reference_station_is_redrawn_and_comes_back_the_same(
    client: TestClient, station: str
) -> None:
    """STUDIO-30: the station's model opens in Rita; saved without a change, nothing changes."""
    assert client.post(API + f"/referens/{station}/use").status_code == 200
    store = client.app.state.store  # type: ignore[attr-defined]
    before = to_json(store.station_model("lokal"))
    opened = rita(client.get(R))
    assert opened.state == TklDrawingState.IN_USE
    assert opened.drawing.proposal == (reference(station).panel is None)
    sent = json.loads(opened.drawing.model_dump_json())
    assert rita(client.put(R, json=sent)).state == TklDrawingState.IN_USE
    assert rita(client.post(R + "/use")).state == TklDrawingState.IN_USE
    assert to_json(store.station_model("lokal")) == before


def test_a_redrawn_plan_that_breaks_the_grid_is_refused_with_the_reason(
    client: TestClient,
) -> None:
    """STD-26: the redrawn plan is kept as a draft, with the problem, and not taken into use."""
    station = next(s for s in STATIONS if reference(s).panel is not None)
    assert client.post(API + f"/referens/{station}/use").status_code == 200
    opened = rita(client.get(R))
    redrawn = opened.drawing.model_copy(update={"model": broken_plan(opened.drawing.model)})
    shown = put(client, redrawn)
    assert shown.state == TklDrawingState.DRAFT
    said = [f.text for f in shown.findings if f.problem]
    assert any(" går genom " in p or " ligger på samma ruta " in p for p in said), said
    refused = client.post(R + "/use")
    assert refused.status_code == 422
    assert refused.json()["detail"]["problems"] == said


def test_a_new_model_leaves_no_draft_behind(client: TestClient) -> None:
    put(client, broken())
    assert client.post(API + f"/referens/{STATIONS[0]}/use").status_code == 200
    assert rita(client.get(R)).state == TklDrawingState.IN_USE


def test_rita_needs_the_pin(tmp_path: Path) -> None:
    made = tkl(tmp_path)
    set_up(made)
    made.post(API + "/lock")
    assert made.get(R).status_code == 401
    assert made.put(R, content=drawing().model_dump_json()).status_code == 401
    assert made.post(R + "/use").status_code == 401
    assert made.delete(R).status_code == 401


def test_a_drawing_that_is_not_one_is_refused(client: TestClient) -> None:
    answer = client.put(R, content='{"model": {"format": "något"}}')
    assert answer.status_code == 422
    assert answer.json()["detail"]["message"] == "Ritningen gick inte att läsa."
