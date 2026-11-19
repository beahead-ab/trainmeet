"""Studio, Inställningar, Fjärrstyrning (#36 del b, TKL46, FR10, FR16, FR24, FR31, FR40): the
remote catalogue and the overview from the model, for every reference station, valid against the
outside's own checks; the owner's choice kept with the model and versioned with it; and level 0
with none. The stations are found from the model files; nothing here names one (RS13)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.station_model import StationModel, to_json
from contracts.station_outside import AutomatKind, RouteDirection, StationOutside
from contracts.tkl import TklAutomatSpec, TklFjarrChoice, TklFjarrStudio
from tkl.stallverk import Interlocking, plant_of
from tkl.stallverk.plant import MAINS
from tkl.standard import RouteKind, outside_of
from tkl.standard.outside import Remote
from tkl.studio import fjarr
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import model as made_up

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
F = API + "/studio/fjarrstyrning"


def reference(station: str) -> StationModel:
    return StationModel.model_validate_json((MODELS / f"{station}.tkl.json").read_text("utf-8"))


@pytest.mark.parametrize("station", STATIONS)
def test_the_catalogue_and_the_overview_of_every_reference_station(station: str) -> None:
    """Every candidate is a train route in or out, laid by the interlocking from a clean state
    to its track; the whole catalogue gives an outside that passes the outside's own checks,
    with an overview whose routes lay only its pieces and links (FR10, FR31)."""
    model = reference(station)
    plant = plant_of(model)
    found = fjarr.candidates(plant)
    assert found, "a station with signals or line exits has routes in and out"
    assert len({c.id for c in found}) == len(found)
    trains = {(w.start, w.end) for w in plant.preferred() if w.kind == RouteKind.TRAIN}
    pieces_of = {t.id: set(t.pieces) for t in model.station_tracks}
    for candidate in found:
        assert all(way.kind == RouteKind.TRAIN for way in candidate.chain)
        assert all((way.start, way.end) in trains for way in candidate.chain)
        laid = Interlocking(plant).lay_route(candidate.start, candidate.end, RouteKind.TRAIN)
        assert laid.accepted, (candidate.id, laid.message)
        pieces = {p for way in candidate.chain for p in way.pieces}
        if candidate.direction == RouteDirection.IN:
            assert pieces & pieces_of[candidate.track], candidate.id
            assert candidate.chain[0].enters == candidate.exit
        else:
            assert candidate.chain[-1].leaves == candidate.exit
    remote = fjarr.remote_of(plant, TklFjarrChoice(routes=[c.id for c in found]))
    outside = outside_of(model, model.station_id, model.name, remote=remote)
    checked = StationOutside.model_validate(outside.model_dump(mode="json"))
    overview = checked.overview
    assert overview is not None and len(checked.remote_routes) == len(found)
    assert set(overview.routes) == {r.id for r in checked.remote_routes}
    assert all(overview.routes[r.id] for r in checked.remote_routes), "each route lays something"
    mains = {s.name for s in model.signals if s.type in MAINS}
    assert {s.name for s in overview.signals} <= mains, "main signals only, never dwarfs (FR36)"
    assert {e.exit for e in overview.exits} == {r.exit for r in checked.remote_routes}
    numbers = {s.number for s in model.switches}
    shown = {t.id for t in overview.tracks} | {link.id for link in overview.links}
    assert not shown & numbers, "no switch numbers in the overview (FR36)"
    assert overview.rows <= 40 and overview.columns <= 400


def test_level_0_has_no_catalogue() -> None:
    """FR16: no interlocking that locks routes, no catalogue, automats or overview."""
    assert fjarr.remote_of(None, TklFjarrChoice(routes=["In-12"])) == Remote()
    found = fjarr.problems(None, TklFjarrChoice(routes=["In-12"]), 0)
    assert found and "nivå 0" in found[0]


def test_before_the_owner_chooses_the_outside_is_as_before() -> None:
    model = reference(STATIONS[0])
    plant = plant_of(model)
    before = outside_of(model, model.station_id, model.name)
    assert fjarr.remote_of(plant, None) == Remote()
    assert before.remote_routes == [] and before.overview is None and before.automats == []


def test_the_checks_say_no_to_shunting_routes_unknown_routes_and_two_a3() -> None:
    plant = plant_of(made_up())
    trains = {(w.start, w.end) for w in plant.preferred() if w.kind == RouteKind.TRAIN}
    shunting = next(
        w
        for w in plant.preferred()
        if w.kind == RouteKind.SHUNTING and (w.start, w.end) not in trains
    )
    settings = TklFjarrChoice(
        routes=[f"{shunting.start}-{shunting.end}", "X-Y", "In-12"],
        automats=[
            TklAutomatSpec(code="A3", kind=AutomatKind.A3, default=True),
            TklAutomatSpec(code="A3b", kind=AutomatKind.A3, default=True),
            TklAutomatSpec(code="AN", kind=AutomatKind.AN),
        ],
    )
    found = fjarr.problems(plant, settings, 2)
    assert any("växlingsväg" in p and "FR10" in p for p in found)
    assert any("X-Y finns inte" in p for p in found)
    assert any("bara en A3" in p for p in found)
    assert any("Bara en automat kan vara förvald" in p for p in found)
    assert any("välj infartssignalen" in p for p in found)
    assert fjarr.problems(plant, TklFjarrChoice(routes=["In-12"]), 2) == []


def test_the_suggestion_has_a3_as_the_default_and_the_local_release_codes() -> None:
    """FR29, FR39: A3, A2 and A1, the default A3, and one code per local release function, as
    the panel function has it in 95 or 85, else L1."""
    for station in STATIONS:
        model = reference(station)
        suggested = fjarr.suggested(model)
        assert [(a.code, a.default) for a in suggested[:3]] == [
            ("A3", True),
            ("A2", False),
            ("A1", False),
        ]
        locals_ = [a for a in suggested if a.kind == AutomatKind.LOCAL_RELEASE]
        assert [a.function for a in locals_] == fjarr.local_releases(model)
        for local in locals_:
            function = next(f for f in model.functions if f.name == local.function)
            assert local.code == (function.codes.get("95") or function.codes.get("85") or "L1")


# --- Studio's API and the store ------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    return made


def page(client: TestClient) -> TklFjarrStudio:
    answer = client.get(F)
    assert answer.status_code == 200, answer.text
    return TklFjarrStudio.model_validate(answer.json())


def test_studio_at_level_0_says_there_is_no_catalogue(client: TestClient) -> None:
    found = page(client)
    assert found.level == 0 and found.candidates == [] and found.note is not None
    assert "FR16" in found.note
    assert client.put(F, json={"routes": ["In-12"]}).status_code == 404


def test_studio_keeps_the_choice_with_the_model_and_versions_it(client: TestClient) -> None:
    assert client.put(API + "/studio/model", content=to_json(made_up())).status_code == 200
    found = page(client)
    assert not found.kept and found.level == 2
    assert {c.id for c in found.candidates} >= {"In-12", "In-22", "12-Ut2"}
    assert found.outside is not None and found.outside.remote_routes == []
    refused = client.put(F, json={"routes": ["In-12", "D-22"]})
    assert refused.status_code == 422
    assert any("växlingsväg" in p for p in refused.json()["detail"]["problems"])
    chosen = {"routes": ["In-12", "12-Ut2"], "automats": [{"code": "A3", "kind": "a3"}]}
    saved = client.put(F, json=chosen)
    assert saved.status_code == 200, saved.text
    kept = TklFjarrStudio.model_validate(saved.json())
    assert kept.kept and [c.id for c in kept.candidates if c.chosen] == ["In-12", "12-Ut2"]
    studio = client.get(API + "/studio").json()
    assert studio["changed"] is True
    draft = StationOutside.model_validate(studio["draft"])
    assert [r.id for r in draft.remote_routes] == ["In-12", "12-Ut2"]
    assert [a.code for a in draft.automats] == ["A3"] and draft.overview is not None
    version = client.post(API + "/studio/version").json()
    assert version["changed"] is False
    store = client.app.state.store  # type: ignore[attr-defined]
    slot = "lokal"
    assert store.fjarr_of_version(slot, version["versions"][0]["number"]).routes == [
        "In-12",
        "12-Ut2",
    ]
    assert client.delete(API + "/studio/model").status_code == 200
    assert store.fjarr(slot) is None, "the choice goes with the model"
