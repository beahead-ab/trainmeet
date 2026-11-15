"""The fleet (#50): vehicles with their core fields, search, places, lending and history."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.fleet import Fleet, Refused
from catalog.login import TRIAL_ACCOUNTS
from catalog.settings import Settings
from contracts.catalog import CatalogVersion, Vehicle, VehicleChange, VehicleList, VehicleState

API = "/api/catalog/1"
HBIS = {
    "status": "ready",
    "kind": "freight_wagon",
    "litt": "Hbis",
    "number": "21 74 245 2 253-0",
    "operator": "Green Cargo",
    "epoch": "V",
    "scale": "H0",
}


def make_client(database_url: str, tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path,
        build=CatalogVersion(version="0.1.0"),
    )
    return TestClient(create_app(settings))


def log_in(client: TestClient, letter: str = "A") -> None:
    account = TRIAL_ACCOUNTS["ABCD".index(letter)]
    answer = client.post(API + "/trial/login", json={"account": str(account.id)})
    assert answer.status_code == 200


@pytest.fixture
def client(database_url: str, tmp_path: Path) -> Iterator[TestClient]:
    with make_client(database_url, tmp_path) as test_client:
        log_in(test_client)
        yield test_client


def add(client: TestClient, **fields: Any) -> dict[str, Any]:
    answer = client.post(API + "/vehicles", json={**HBIS, **fields})
    assert answer.status_code == 201, answer.text
    body: dict[str, Any] = answer.json()
    return body


def change(client: TestClient, vehicle: dict[str, Any], **fields: Any) -> Any:
    keep = {k: vehicle[k] for k in VehicleChange.model_fields if k in vehicle}
    return client.put(f"{API}/vehicles/{vehicle['id']}", json={**keep, **fields})


def search(client: TestClient, **params: Any) -> VehicleList:
    return VehicleList.model_validate(client.get(API + "/vehicles", params=params).json())


def problem(answer: Any) -> tuple[int, str]:
    return answer.status_code, answer.json()["code"]


# --- The core fields -----------------------------------------------------------------------


def test_a_vehicle_gets_a_permanent_id_and_the_evn_is_derived(client: TestClient) -> None:
    vehicle = Vehicle.model_validate(add(client))
    assert vehicle.version == 1
    assert vehicle.state == "home"
    assert vehicle.number == "21 74 245 2 253-0"
    assert vehicle.evn is not None
    assert (vehicle.evn.text, vehicle.evn.country_letters, vehicle.evn.valid) == (
        "21 74 245 2 253-0",
        "S",
        True,
    )
    assert vehicle.field_sources["litt"] == "owner"
    assert "note" not in vehicle.field_sources
    again = client.get(f"{API}/vehicles/{vehicle.id}").json()
    assert again["id"] == str(vehicle.id)


def test_the_number_is_kept_as_painted_and_a_wrong_check_digit_is_reported(
    client: TestClient,
) -> None:
    vehicle = add(client, number="21 74 245 2 253-9")
    assert vehicle["number"] == "21 74 245 2 253-9"
    assert vehicle["evn"]["valid"] is False
    assert (vehicle["evn"]["check"], vehicle["evn"]["given"]) == (0, 9)
    locomotive = add(client, kind="locomotive", litt="Rc6", number="0340", operator="SJ")
    assert locomotive["number"] == "0340"
    assert locomotive["evn"] is None


def test_a_draft_needs_nothing_but_ready_needs_kind_and_litt_or_number(
    client: TestClient,
) -> None:
    draft = client.post(API + "/vehicles", json={"note": "en vagn i lådan"})
    assert draft.status_code == 201
    assert draft.json()["status"] == "draft"
    assert problem(client.post(API + "/vehicles", json={"status": "ready", "litt": "Hbis"})) == (
        422,
        "not_ready",
    )
    no_number = {"status": "ready", "kind": "other"}
    assert problem(client.post(API + "/vehicles", json=no_number)) == (422, "not_ready")
    ready = client.post(API + "/vehicles", json={"status": "ready", "kind": "other", "number": "7"})
    assert ready.status_code == 201


def test_dcc_address_and_functions_are_for_engines_only(client: TestClient) -> None:
    wagon = client.post(API + "/vehicles", json={**HBIS, "dcc_address": "3"})
    assert problem(wagon) == (422, "dcc_only_engines")
    engine = add(
        client,
        kind="locomotive",
        litt="Rc6",
        number="1340",
        dcc_address="1340",
        functions=[{"number": 0, "name": "Ljus"}, {"number": 2, "name": "Tyfon"}],
    )
    assert engine["dcc_address"] == "1340"
    assert [f["name"] for f in engine["functions"]] == ["Ljus", "Tyfon"]


def test_every_change_raises_the_version_and_an_old_version_is_refused(
    client: TestClient,
) -> None:
    vehicle = add(client)
    changed = change(client, vehicle, operator="SJ")
    assert changed.status_code == 200
    assert (changed.json()["version"], changed.json()["operator"]) == (2, "SJ")
    stale = change(client, vehicle, operator="Hector Rail")
    assert problem(stale) == (409, "changed")
    assert client.get(f"{API}/vehicles/{vehicle['id']}").json()["operator"] == "SJ"


def test_two_changes_built_on_the_same_version_give_exactly_one_winner(
    client: TestClient,
) -> None:
    vehicle = Vehicle.model_validate(add(client))
    fleet = Fleet(client.app.state.db)  # type: ignore[attr-defined]
    owner = TRIAL_ACCOUNTS[0].id
    results: list[str] = []

    def write(operator: str) -> None:
        body = VehicleChange.model_validate(
            {**vehicle.model_dump(include=set(VehicleChange.model_fields)), "operator": operator}
        )
        try:
            fleet.change(owner, vehicle.id, body)
            results.append("ok")
        except Refused as error:
            results.append(error.code.value)

    threads = [threading.Thread(target=write, args=(name,)) for name in ("SJ", "Hector Rail")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == ["changed", "ok"]
    assert fleet.get(owner, vehicle.id).version == 2


def test_a_change_from_the_owner_marks_the_field_as_the_owners(client: TestClient) -> None:
    vehicle = add(client)
    cleared = change(client, vehicle, operator="", note="kort koppel").json()
    assert "operator" not in cleared["field_sources"]
    assert cleared["field_sources"]["note"] == "owner"


def test_the_owner_removes_a_vehicle_with_the_version_seen(client: TestClient) -> None:
    vehicle = add(client)
    gone = client.delete(f"{API}/vehicles/{vehicle['id']}", params={"version": 5})
    assert problem(gone) == (409, "changed")
    removed = client.delete(f"{API}/vehicles/{vehicle['id']}", params={"version": 1})
    assert removed.json() == {"id": vehicle["id"]}
    assert problem(client.get(f"{API}/vehicles/{vehicle['id']}")) == (404, "not_found")


# --- Only the owner ----------------------------------------------------------------------


def test_another_owner_sees_nothing_and_changes_nothing(
    database_url: str, tmp_path: Path, client: TestClient
) -> None:
    vehicle = add(client)
    with make_client(database_url, tmp_path) as other:
        log_in(other, "B")
        assert problem(other.get(f"{API}/vehicles/{vehicle['id']}")) == (404, "not_found")
        assert problem(change(other, vehicle, note="mitt nu")) == (404, "not_found")
        assert search(other).total == 0
        assert other.get(API + "/places").json() == []


def test_nothing_without_a_login(database_url: str, tmp_path: Path) -> None:
    with make_client(database_url, tmp_path) as anonymous:
        assert problem(anonymous.get(API + "/vehicles")) == (401, "login")
        assert problem(anonymous.post(API + "/vehicles", json=HBIS)) == (401, "login")
        assert problem(anonymous.get(API + "/places")) == (401, "login")


# --- Search ------------------------------------------------------------------------------


def test_search_over_litt_number_operator_model_and_note(client: TestClient) -> None:
    add(client)
    add(client, litt="Gbs", number="21 74 151 3 087-1", maker="Roco", article_number="76612")
    add(client, kind="locomotive", litt="Rc6", number="1340", operator="SJ", note="nytt ljus")
    assert [v.litt for v in search(client, q="hbis").vehicles] == ["Hbis"]
    assert [v.litt for v in search(client, q="2452253").vehicles] == ["Hbis"]
    assert [v.litt for v in search(client, q="Rc6 1340").vehicles] == ["Rc6"]
    assert [v.litt for v in search(client, q="roco").vehicles] == ["Gbs"]
    assert [v.litt for v in search(client, q="76612").vehicles] == ["Gbs"]
    assert [v.litt for v in search(client, q="ljus").vehicles] == ["Rc6"]
    assert len(search(client, q="green").vehicles) == 2
    assert search(client, q="100%").vehicles == []


def test_filters_on_kind_scale_state_and_place(client: TestClient) -> None:
    box = client.post(API + "/places", json={"name": "Låda 1"}).json()
    add(client, place=box["id"])
    add(client, kind="locomotive", litt="Rc6", number="1340", scale="N")
    wagons = search(client, kind=["freight_wagon", "passenger_coach"])
    assert [v.litt for v in wagons.vehicles] == ["Hbis"]
    assert [v.litt for v in search(client, scale="N").vehicles] == ["Rc6"]
    assert [v.litt for v in search(client, place=box["id"]).vehicles] == ["Hbis"]
    assert [v.litt for v in search(client, place="none").vehicles] == ["Rc6"]
    everything = search(client)
    assert everything.total == 2
    assert everything.counts[VehicleState.HOME] == 2
    assert everything.counts[VehicleState.LENT] == 0


# --- Places, moving, lending and the history -------------------------------------------------


def test_places_are_named_by_the_owner_and_count_their_vehicles(client: TestClient) -> None:
    box = client.post(API + "/places", json={"name": "Låda 1"}).json()
    assert problem(client.post(API + "/places", json={"name": "Låda 1"})) == (
        422,
        "place_exists",
    )
    shelf = client.post(API + "/places", json={"name": "Hyllan"}).json()
    vehicle = add(client, place=box["id"])
    assert vehicle["place_name"] == "Låda 1"
    renamed = client.put(f"{API}/places/{box['id']}", json={"name": "Låda 3"}).json()
    assert (renamed["name"], renamed["vehicles_home"], renamed["vehicles"]) == ("Låda 3", 1, 1)
    assert [p["name"] for p in client.get(API + "/places").json()] == ["Hyllan", "Låda 3"]
    assert client.get(f"{API}/vehicles/{vehicle['id']}").json()["place_name"] == "Låda 3"
    assert shelf["vehicles"] == 0


def test_removing_a_place_leaves_its_vehicles_at_home_without_a_place(
    client: TestClient,
) -> None:
    box = client.post(API + "/places", json={"name": "Låda 1"}).json()
    vehicle = add(client, place=box["id"])
    assert client.delete(f"{API}/places/{box['id']}").json() == {"id": box["id"]}
    after = client.get(f"{API}/vehicles/{vehicle['id']}").json()
    assert (after["state"], after["place"], after["version"]) == ("home", None, 2)
    assert problem(client.delete(f"{API}/places/{box['id']}")) == (404, "not_found")


def test_several_vehicles_move_to_a_place_at_once(client: TestClient) -> None:
    box = client.post(API + "/places", json={"name": "Låda 2"}).json()
    one, two = add(client), add(client, litt="Gbs", number="3087")
    moved = client.post(
        API + "/vehicles/move", json={"vehicles": [one["id"], two["id"]], "place": box["id"]}
    ).json()
    assert {v["place_name"] for v in moved["vehicles"]} == {"Låda 2"}
    assert client.get(API + "/places").json()[0]["vehicles_home"] == 2
    unknown = {"vehicles": [one["id"], "00000000-0000-4000-8000-000000000000"]}
    assert problem(client.post(API + "/vehicles/move", json=unknown)) == (404, "not_found")
    other_place = {"vehicles": [one["id"]], "place": "00000000-0000-4000-8000-000000000000"}
    assert problem(client.post(API + "/vehicles/move", json=other_place)) == (422, "not_found")


def test_a_lent_vehicle_stays_in_the_fleet_and_comes_back_to_its_place(
    client: TestClient,
) -> None:
    box = client.post(API + "/places", json={"name": "Låda 3"}).json()
    vehicle = add(client, place=box["id"])
    lent = client.post(
        f"{API}/vehicles/{vehicle['id']}/lend",
        json={"version": 1, "to": "Provkonto B", "until": "2026-12-01"},
    ).json()
    assert lent["state"] == "lent"
    assert (lent["lending"]["to"], lent["lending"]["until"]) == ("Provkonto B", "2026-12-01")
    assert lent["place_name"] == "Låda 3"
    assert search(client, state="lent").total == 1
    assert len(search(client, state="lent").vehicles) == 1
    again = {"version": 2, "to": "Någon"}
    assert problem(client.post(f"{API}/vehicles/{vehicle['id']}/lend", json=again)) == (
        422,
        "not_home",
    )
    back = client.post(f"{API}/vehicles/{vehicle['id']}/return", json={"version": 2}).json()
    assert (back["state"], back["place_name"], back["lending"]) == ("home", "Låda 3", None)
    not_lent = client.post(f"{API}/vehicles/{vehicle['id']}/return", json={"version": 3})
    assert problem(not_lent) == (422, "not_lent")


def test_only_a_ready_vehicle_can_be_lent(client: TestClient) -> None:
    draft = client.post(API + "/vehicles", json={"note": "okänd"}).json()
    answer = client.post(f"{API}/vehicles/{draft['id']}/lend", json={"version": 1, "to": "Olle"})
    assert problem(answer) == (422, "not_ready")


def test_every_change_of_state_or_place_is_an_event_for_the_owner(client: TestClient) -> None:
    box = client.post(API + "/places", json={"name": "Låda 1"}).json()
    vehicle = add(client)
    client.post(API + "/vehicles/move", json={"vehicles": [vehicle["id"]], "place": box["id"]})
    client.post(f"{API}/vehicles/{vehicle['id']}/lend", json={"version": 2, "to": "Olle"})
    client.post(f"{API}/vehicles/{vehicle['id']}/return", json={"version": 3})
    events = client.get(f"{API}/vehicles/{vehicle['id']}/events").json()
    assert [(e["state"], e["place_name"], e["lent_to"]) for e in events] == [
        ("home", "Låda 1", None),
        ("lent", "Låda 1", "Olle"),
        ("home", "Låda 1", None),
        ("home", None, None),
    ]


def test_the_owner_history_starts_with_the_vehicle(client: TestClient) -> None:
    vehicle = add(client)
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT owner_id, until FROM vehicle_owner WHERE vehicle_id = %s", (vehicle["id"],)
        ).fetchall()
    assert rows == [{"owner_id": TRIAL_ACCOUNTS[0].id, "until": None}]
