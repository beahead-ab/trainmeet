"""The tags and the lookup (#54). TrainCatalog's tests for the tags are the model
(catalog/test_tag_contracts.py and catalog/test_taggprov.py), ported with the behaviour."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.fleet import Refused
from catalog.login import TRIAL_ACCOUNTS
from catalog.settings import Settings
from catalog.tags import Tags, normalize
from contracts.catalog import CatalogVersion, TagLink

API = "/api/catalog/1"
BASE = "https://test.catalog.trainmeet.app/t/"
UID = "04a1b2c3d4e5f6"  # An NTAG213 has a 7 byte serial number.
HBIS = {"status": "ready", "kind": "freight_wagon", "litt": "Hbis", "number": "21 74 245 2 253-0"}


def make_client(database_url: str, tmp_path: Path, *, simulated: bool = True) -> TestClient:
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path,
        tag_base=BASE,
        simulated_tags=simulated,
        build=CatalogVersion(version="0.1.0"),
    )
    return TestClient(create_app(settings))


def log_in(client: TestClient, letter: str) -> None:
    account = TRIAL_ACCOUNTS["ABCD".index(letter)]
    assert client.post(API + "/trial/login", json={"account": str(account.id)}).status_code == 200


@pytest.fixture
def owner(database_url: str, tmp_path: Path) -> Iterator[TestClient]:
    with make_client(database_url, tmp_path) as client:
        log_in(client, "A")
        yield client


@pytest.fixture
def reader(database_url: str, tmp_path: Path, owner: TestClient) -> Iterator[TestClient]:
    with make_client(database_url, tmp_path) as client:
        log_in(client, "B")
        yield client


@pytest.fixture
def visitor(database_url: str, tmp_path: Path, owner: TestClient) -> Iterator[TestClient]:
    with make_client(database_url, tmp_path) as client:
        yield client


def vehicle(client: TestClient, **fields: Any) -> dict[str, Any]:
    answer = client.post(API + "/vehicles", json={**HBIS, **fields})
    assert answer.status_code == 201, answer.text
    body: dict[str, Any] = answer.json()
    return body


def link(client: TestClient, uid: str, vehicle_id: str, **extra: Any) -> Any:
    return client.post(
        f"{API}/tags/{uid}/link", json={"vehicle": vehicle_id, "confirm": True, **extra}
    )


def lookup(client: TestClient, uid: str) -> Any:
    return client.get(f"{API}/tags/{uid}")


def problem(answer: Any) -> tuple[int, str]:
    return answer.status_code, answer.json()["code"]


def set_show_name(client: TestClient, letter: str, on: bool) -> None:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.transaction() as conn:
        conn.execute(
            "UPDATE owner SET show_name = %s WHERE id = %s",
            (on, TRIAL_ACCOUNTS["ABCD".index(letter)].id),
        )


# --- The address ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written",
    ["04A1B2C3D4E5F6", "04a1b2c3d4e5f6", "04:A1:B2:C3:D4:E5:F6", "04-a1-b2-c3-d4-e5-f6", UID + "/"],
)
def test_the_serial_number_is_the_same_whatever_way_it_is_written(written: str) -> None:
    found = normalize(written)
    assert (found.namespace, found.value) == ("iso14443a_uid", UID)


def test_simulated_tags_and_qr_labels_have_their_own_namespaces() -> None:
    sim = normalize("6F1D2C1E-6A43-4B8E-9C5A-0C3A7D4F9B21")
    assert (sim.namespace, sim.value) == ("sim", "6f1d2c1e-6a43-4b8e-9c5a-0c3a7d4f9b21")
    assert normalize("QABCDEFGHJK2").namespace == "qr"


@pytest.mark.parametrize("bad", ["", "04a1", "x" * 40, "04a1b2c3d4e5f6zz", "../etc"])
def test_anything_else_is_not_a_tag(bad: str) -> None:
    with pytest.raises(Refused) as refused:
        normalize(bad)
    assert refused.value.code == "bad_tag"


def test_the_address_fits_an_ntag213_with_room_to_spare() -> None:
    """One URL record in an NDEF TLV, as a tag writer stores it (CAT-116)."""
    url = "https://trainmeet.app/t/" + UID
    payload = bytes([0x04]) + url.removeprefix("https://").encode()
    tlv = bytes([0x03, 4 + len(payload)]) + bytes([0xD1, 1, len(payload)]) + b"U" + payload
    assert len(tlv) + 1 <= 40 < 144


# --- The lookup: exactly these fields per outcome (CAT-98–CAT-107, CAT-209) -----------------------


def test_mine_opens_the_card(owner: TestClient) -> None:
    car = vehicle(owner)
    assert link(owner, UID, car["id"]).status_code == 200
    assert lookup(owner, UID).json() == {"outcome": "mine", "vehicle_id": car["id"]}


def test_someone_else_without_the_name_gets_exactly_the_mini_card(
    owner: TestClient, reader: TestClient
) -> None:
    car = vehicle(owner, operator="Green Cargo", scale="H0", note="Privat", maker="Roco")
    link(owner, UID, car["id"])
    assert lookup(reader, UID).json() == {
        "outcome": "private",
        "card": {
            "litt": "Hbis",
            "number": "21 74 245 2 253-0",
            "kind": "freight_wagon",
            "operator": "Green Cargo",
            "scale": "H0",
            "thumbnail": None,
        },
    }


def test_the_owners_name_only_when_shown_and_only_to_those_logged_in(
    owner: TestClient, reader: TestClient, visitor: TestClient
) -> None:
    link(owner, UID, vehicle(owner)["id"])
    set_show_name(owner, "A", True)
    shared = lookup(reader, UID).json()
    assert set(shared) == {"outcome", "owner_name", "card"}
    assert (shared["outcome"], shared["owner_name"]) == ("shared", "Provkonto A")
    assert set(shared["card"]) == {"litt", "number", "kind", "operator", "scale", "thumbnail"}
    assert lookup(visitor, UID).json()["outcome"] == "private"
    set_show_name(owner, "A", False)
    assert lookup(reader, UID).json()["outcome"] == "private"


def test_an_unknown_tag_says_its_uid_only_to_those_logged_in(
    owner: TestClient, visitor: TestClient
) -> None:
    assert lookup(owner, "04:AA:BB:CC:DD").json() == {"outcome": "unknown", "tag_uid": "04aabbccdd"}
    assert lookup(visitor, "04aabbccdd").json() == {"outcome": "unknown"}


def test_a_shared_fleet_gets_the_card_with_the_sharings_right(
    owner: TestClient, reader: TestClient
) -> None:
    """The fifth outcome (C35). Sharing comes with ID; here it is given by hand."""
    tags = Tags(owner.app.state.db, base=BASE, simulated=False, shared_with=lambda a, o: "view")  # type: ignore[attr-defined]
    car = vehicle(owner)
    link(owner, UID, car["id"])
    found = tags.lookup(TRIAL_ACCOUNTS[1].id, UID, "")
    assert found.model_dump(mode="json") == {
        "outcome": "fleet",
        "vehicle_id": car["id"],
        "right": "view",
    }


def test_the_answer_is_private_to_the_browser_and_nobodys_taps_are_kept(
    owner: TestClient, reader: TestClient
) -> None:
    link(owner, UID, vehicle(owner)["id"])
    answer = lookup(reader, UID)
    assert answer.headers["cache-control"] == "private, no-store"
    db = owner.app.state.db  # type: ignore[attr-defined]
    with db.transaction() as conn:
        counters = conn.execute("SELECT * FROM tag_lookup_counter").fetchall()
    assert [set(c) for c in counters] == [{"owner_id", "window_start", "count"}]


def test_thirty_lookups_a_minute_then_429(owner: TestClient, visitor: TestClient) -> None:
    for _ in range(30):
        assert lookup(owner, UID).status_code == 200
    stopped = lookup(owner, UID)
    assert problem(stopped) == (429, "too_many")
    assert stopped.headers["retry-after"] == "60"
    for _ in range(30):
        assert lookup(visitor, UID).status_code == 200
    assert lookup(visitor, UID).status_code == 429


def test_a_bad_address_says_so(owner: TestClient) -> None:
    assert problem(lookup(owner, "inte-en-tagg")) == (422, "bad_tag")


# --- Linking ----------------------------------------------------------------------------------


def test_linking_needs_a_yes_and_a_ready_vehicle(owner: TestClient) -> None:
    car = vehicle(owner)
    no = owner.post(f"{API}/tags/{UID}/link", json={"vehicle": car["id"], "confirm": False})
    assert no.status_code == 422
    draft = owner.post(API + "/vehicles", json={"note": "okänd"}).json()
    assert problem(link(owner, UID, draft["id"])) == (422, "not_ready")


def test_web_nfcs_serial_number_and_the_programmed_address_find_the_same_tag(
    owner: TestClient,
) -> None:
    car = vehicle(owner)
    linked = link(owner, "04:a1:b2:c3:d4:e5:f6", car["id"]).json()
    assert [(t["uid"], t["kind"], t["address"]) for t in linked["tags"]] == [
        (UID, "nfc", BASE + UID)
    ]
    for written in ("04A1B2C3D4E5F6", UID, "04-a1-b2-c3-d4-e5-f6"):
        assert lookup(owner, written).json()["outcome"] == "mine"


def test_the_same_link_twice_gives_the_same_result(owner: TestClient) -> None:
    car = vehicle(owner)
    first = link(owner, UID, car["id"]).json()
    again = link(owner, UID, car["id"]).json()
    assert first["tags"] == again["tags"]


def test_someone_elses_linked_tag_cannot_be_taken(owner: TestClient, reader: TestClient) -> None:
    link(owner, UID, vehicle(owner)["id"])
    theirs = vehicle(reader)
    assert problem(link(reader, UID, theirs["id"])) == (409, "tag_taken")


def test_a_tag_on_another_of_my_vehicles_moves_after_a_yes(owner: TestClient) -> None:
    first, second = vehicle(owner), vehicle(owner, litt="Gbs", number="3087")
    on_first = link(owner, UID, first["id"]).json()["tags"][0]
    assert problem(link(owner, UID, second["id"])) == (409, "tag_on_other_vehicle")
    moved = link(owner, UID, second["id"], move_from=on_first["assignment"]).json()
    assert moved["tags"][0]["uid"] == UID
    assert owner.get(f"{API}/vehicles/{first['id']}").json()["tags"] == []
    assert lookup(owner, UID).json() == {"outcome": "mine", "vehicle_id": second["id"]}


def test_replacing_ends_the_old_link_and_starts_the_new_in_one_go(owner: TestClient) -> None:
    car = vehicle(owner)
    old = link(owner, UID, car["id"]).json()["tags"][0]
    new_uid = "04aabbccddeeff"
    assert problem(link(owner, new_uid, car["id"])) == (409, "tag_changed")
    wrong = link(owner, new_uid, car["id"], replace="00000000-0000-4000-8000-000000000000")
    assert problem(wrong) == (409, "tag_changed")
    replaced = link(owner, new_uid, car["id"], replace=old["assignment"]).json()
    assert [t["uid"] for t in replaced["tags"]] == [new_uid]
    assert lookup(owner, UID).json() == {"outcome": "unknown", "tag_uid": UID}
    events = owner.get(f"{API}/tags/{UID}/events").json()
    assert [e["event"] for e in events] == ["linked", "unlinked"]


def test_a_vehicle_has_one_nfc_tag_and_one_qr_label_at_most(owner: TestClient) -> None:
    car = vehicle(owner)
    link(owner, UID, car["id"])
    labelled = owner.post(f"{API}/vehicles/{car['id']}/tags/qr", json={}).json()
    assert sorted(t["kind"] for t in labelled["tags"]) == ["nfc", "qr"]
    label = next(t for t in labelled["tags"] if t["kind"] == "qr")
    assert label["uid"].startswith("q") and len(label["uid"]) == 12
    assert label["address"] == BASE + label["uid"]
    again = owner.post(f"{API}/vehicles/{car['id']}/tags/qr", json={})
    assert problem(again) == (409, "tag_changed")
    new = owner.post(f"{API}/vehicles/{car['id']}/tags/qr", json={"replace": label["assignment"]})
    assert new.status_code == 200
    assert lookup(owner, label["uid"]).json()["outcome"] == "unknown"


def test_only_the_owner_gets_the_qr_code(owner: TestClient, reader: TestClient) -> None:
    car = vehicle(owner)
    label = owner.post(f"{API}/vehicles/{car['id']}/tags/qr", json={}).json()["tags"][0]
    svg = owner.get(f"{API}/tags/{label['uid']}/qr.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert problem(reader.get(f"{API}/tags/{label['uid']}/qr.svg")) == (404, "not_found")


def test_unlinking_ends_the_link_keeps_the_history_and_again_is_the_same(
    owner: TestClient,
) -> None:
    car = vehicle(owner)
    tag = link(owner, UID, car["id"]).json()["tags"][0]
    body = {"assignment": tag["assignment"], "confirm": True}
    assert owner.post(f"{API}/vehicles/{car['id']}/tags/unlink", json=body).json()["tags"] == []
    assert owner.post(f"{API}/vehicles/{car['id']}/tags/unlink", json=body).status_code == 200
    other = {"assignment": "00000000-0000-4000-8000-000000000000", "confirm": True}
    unknown = owner.post(f"{API}/vehicles/{car['id']}/tags/unlink", json=other)
    assert problem(unknown) == (409, "tag_changed")
    assert [e["event"] for e in owner.get(f"{API}/tags/{UID}/events").json()] == [
        "linked",
        "unlinked",
    ]


def test_an_unlinked_physical_tag_gets_a_new_owner_and_the_history_stays_private(
    owner: TestClient, reader: TestClient
) -> None:
    car = vehicle(owner)
    tag = link(owner, UID, car["id"]).json()["tags"][0]
    owner.post(
        f"{API}/vehicles/{car['id']}/tags/unlink",
        json={"assignment": tag["assignment"], "confirm": True},
    )
    theirs = vehicle(reader)
    assert link(reader, UID, theirs["id"]).status_code == 200
    assert lookup(reader, UID).json() == {"outcome": "mine", "vehicle_id": theirs["id"]}
    events = reader.get(f"{API}/tags/{UID}/events").json()
    assert [(e["event"], e["vehicle_id"]) for e in events] == [("linked", theirs["id"])]


def test_removing_a_vehicle_frees_its_tag(owner: TestClient) -> None:
    car = vehicle(owner)
    link(owner, UID, car["id"])
    owner.delete(f"{API}/vehicles/{car['id']}", params={"version": 1})
    assert lookup(owner, UID).json()["outcome"] == "unknown"
    assert [e["event"] for e in owner.get(f"{API}/tags/{UID}/events").json()] == [
        "linked",
        "unlinked",
    ]


def test_a_vehicle_with_a_tag_cannot_become_a_draft(owner: TestClient) -> None:
    car = vehicle(owner)
    link(owner, UID, car["id"])
    answer = owner.put(f"{API}/vehicles/{car['id']}", json={**HBIS, "kind": None, "version": 1})
    assert problem(answer) == (422, "not_ready")


# --- Simulated tags (CAT-96) ----------------------------------------------------------------


def test_a_simulated_tag_can_be_made_linked_and_tapped(owner: TestClient) -> None:
    sim = owner.post(API + "/tags/simulated").json()
    assert (sim["kind"], sim["name"]) == ("sim", "SIM-001")
    assert sim["address"] == BASE + sim["uid"]
    car = vehicle(owner)
    assert lookup(owner, sim["uid"]).json() == {"outcome": "unknown", "tag_uid": sim["uid"]}
    link(owner, sim["uid"], car["id"])
    assert lookup(owner, sim["uid"]).json()["outcome"] == "mine"
    assert owner.post(API + "/tags/simulated").json()["name"] == "SIM-002"


def test_a_simulated_tag_that_does_not_exist_cannot_be_linked(owner: TestClient) -> None:
    car = vehicle(owner)
    made_up = "6f1d2c1e-6a43-4b8e-9c5a-0c3a7d4f9b21"
    assert problem(link(owner, made_up, car["id"])) == (404, "not_found")


def test_no_simulated_tags_outside_the_test_environment(database_url: str, tmp_path: Path) -> None:
    with make_client(database_url, tmp_path, simulated=False) as client:
        log_in(client, "A")
        assert problem(client.post(API + "/tags/simulated")) == (403, "not_here")


def test_nothing_about_tags_without_a_login(visitor: TestClient) -> None:
    assert problem(visitor.post(API + "/tags/simulated")) == (401, "login")
    assert problem(link(visitor, UID, "00000000-0000-4000-8000-000000000000")) == (401, "login")


# --- Two owners, one new tag (CAT-85, CAT-210) ---------------------------------------------------


def test_two_owners_claiming_the_same_new_tag_at_once_give_one_winner(
    owner: TestClient, reader: TestClient
) -> None:
    db = owner.app.state.db  # type: ignore[attr-defined]
    tags = Tags(db, base=BASE, simulated=False)
    cars = [vehicle(owner), vehicle(reader)]
    start = threading.Barrier(2)
    results: list[str] = []

    def claim(index: int) -> None:
        account = TRIAL_ACCOUNTS[index].id
        start.wait(timeout=10)
        try:
            tags.link(account, "04aabbccdd4499", TagLink(vehicle=cars[index]["id"], confirm=True))
            results.append("ok")
        except Refused as refused:
            results.append(refused.code.value)

    threads = [threading.Thread(target=claim, args=(i,)) for i in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results) == ["ok", "tag_taken"]
    with db.transaction() as conn:
        active = conn.execute("SELECT count(*) AS n FROM tag_assignment WHERE ended_at IS NULL")
        identifiers = conn.execute(
            "SELECT count(*) AS n FROM tag_identifier WHERE value = '04aabbccdd4499'"
        )
        assert (active.fetchone(), identifiers.fetchone()) == ({"n": 1}, {"n": 1})


# --- Koppla tagg: the vehicle waits for the next tag (CAT-94) ------------------------------------


def test_a_vehicle_waits_ten_minutes_for_a_tag(owner: TestClient) -> None:
    car = vehicle(owner)
    assert owner.get(API + "/tags/pending").json() == {"pending": None}
    waiting = owner.post(API + "/tags/pending", json={"vehicle": car["id"]}).json()["pending"]
    assert (waiting["vehicle_id"], waiting["title"], waiting["replace"]) == (
        car["id"],
        "Hbis 21 74 245 2 253-0",
        None,
    )
    link(owner, UID, car["id"])
    assert owner.get(API + "/tags/pending").json() == {"pending": None}


def test_the_waiting_ends_after_ten_minutes_or_when_cancelled(owner: TestClient) -> None:
    car = vehicle(owner)
    owner.post(API + "/tags/pending", json={"vehicle": car["id"]})
    assert owner.delete(API + "/tags/pending").json() == {"pending": None}
    owner.post(API + "/tags/pending", json={"vehicle": car["id"]})
    db = owner.app.state.db  # type: ignore[attr-defined]
    with db.transaction() as conn:
        conn.execute("UPDATE pending_link SET expires_at = now() - interval '1 second'")
    assert owner.get(API + "/tags/pending").json() == {"pending": None}


def test_only_a_ready_vehicle_of_ones_own_can_wait(owner: TestClient, reader: TestClient) -> None:
    draft = owner.post(API + "/vehicles", json={"note": "okänd"}).json()
    assert problem(owner.post(API + "/tags/pending", json={"vehicle": draft["id"]})) == (
        422,
        "not_ready",
    )
    theirs = vehicle(reader)
    assert problem(owner.post(API + "/tags/pending", json={"vehicle": theirs["id"]})) == (
        404,
        "not_found",
    )
