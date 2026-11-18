"""The trip to the meet (#55, CAT-174–CAT-183): the meets, the pack list and the three steps.

Provkonto A owns the fleet and goes to the meets. Provkonto B is someone else: B's taps of A's
tags are never kept (CAT-110), and in the sharing tests B gets A's fleet shared through a
pretend ID.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.login import TRIAL_ACCOUNTS
from catalog.settings import IdSettings, Settings
from catalog.tests.test_sharing import PretendId
from catalog.tests.test_tags import BASE, make_client
from catalog.tests.test_tags import log_in as trial_log_in
from contracts.catalog import CatalogVersion

API = "/api/catalog/1"
A, B = (str(TRIAL_ACCOUNTS[i].id) for i in (0, 1))
HBIS = {"status": "ready", "kind": "freight_wagon", "litt": "Hbis", "number": "2253"}
GBS = {"status": "ready", "kind": "freight_wagon", "litt": "Gbs", "number": "3087"}
RC6 = {"status": "ready", "kind": "locomotive", "litt": "Rc6", "number": "1340"}
# Far enough from today that Swedish time and the test machine's time agree on the day.
PAST = (date.today() - timedelta(days=2)).isoformat()
SOON = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def owner(database_url: str, tmp_path: Path) -> Iterator[TestClient]:
    with make_client(database_url, tmp_path) as client:
        trial_log_in(client, "A")
        yield client


@pytest.fixture
def other(database_url: str, tmp_path: Path, owner: TestClient) -> Iterator[TestClient]:
    with make_client(database_url, tmp_path) as client:
        trial_log_in(client, "B")
        yield client


def vehicle(client: TestClient, fields: dict[str, Any], **extra: Any) -> dict[str, Any]:
    answer = client.post(f"{API}/vehicles", json={**fields, **extra})
    assert answer.status_code == 201, answer.text
    body: dict[str, Any] = answer.json()
    return body


def place(client: TestClient, name: str) -> str:
    answer = client.post(f"{API}/places", json={"name": name})
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


def tagged(client: TestClient, car: dict[str, Any]) -> str:
    """A simulated tag on the vehicle: what a tap reads (CAT-96)."""
    uid = str(client.post(f"{API}/tags/simulated").json()["uid"])
    linked = client.post(f"{API}/tags/{uid}/link", json={"vehicle": car["id"], "confirm": True})
    assert linked.status_code == 200, linked.text
    return uid


def new_meet(client: TestClient, day: str = PAST, **extra: Any) -> dict[str, Any]:
    answer = client.post(f"{API}/meets", json={"name": "Höstträffen", "date": day, **extra})
    assert answer.status_code == 201, answer.text
    body: dict[str, Any] = answer.json()
    return body


def pack_list(client: TestClient, meet: dict[str, Any], *cars: dict[str, Any]) -> dict[str, Any]:
    answer = client.post(
        f"{API}/meets/{meet['id']}/vehicles", json={"vehicles": [c["id"] for c in cars]}
    )
    assert answer.status_code == 200, answer.text
    body: dict[str, Any] = answer.json()
    return body


def press(
    client: TestClient, meet: dict[str, Any], car: dict[str, Any], step: str, ticked: bool = True
) -> Any:
    return client.post(
        f"{API}/meets/{meet['id']}/ticks",
        json={"vehicle": car["id"], "step": step, "ticked": ticked},
    )


def tap(
    client: TestClient, meet: dict[str, Any], uid: str, step: str | None = None, add: bool = False
) -> Any:
    return client.post(f"{API}/meets/{meet['id']}/tap", json={"uid": uid, "step": step, "add": add})


def row(trip: dict[str, Any], car: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = next(r for r in trip["rows"] if r["vehicle"]["id"] == car["id"])
    return found


def state(client: TestClient, car: dict[str, Any]) -> tuple[str, str | None]:
    seen = client.get(f"{API}/vehicles/{car['id']}").json()
    return seen["state"], seen["place_name"]


def history(client: TestClient, car: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    events = client.get(f"{API}/vehicles/{car['id']}/events").json()
    return [(e["state"], e["place_name"], e["meet_name"]) for e in events]


def problem(answer: Any) -> tuple[int, str]:
    return answer.status_code, answer.json()["code"]


# --- The meet and the pack list (CAT-174, CAT-175) --------------------------------------------


def test_a_meet_is_the_owners_own_list_with_a_name_and_a_date(owner: TestClient) -> None:
    meet = new_meet(owner, SOON)
    assert (meet["name"], meet["date"], meet["archived_at"]) == ("Höstträffen", SOON, None)
    assert (meet["vehicles"], meet["rows"], meet["step"]) == (0, [], "pack")
    assert meet["done"] == {"pack": 0, "arrive": 0, "home": 0}
    assert [m["id"] for m in owner.get(f"{API}/meets").json()] == [meet["id"]]
    assert owner.get(f"{API}/meets/{meet['id']}").json() == meet
    assert owner.post(f"{API}/meets", json={"name": " ", "date": SOON}).status_code == 422


def test_the_owner_chooses_the_vehicles_that_go(owner: TestClient) -> None:
    box = place(owner, "Låda 3")
    hbis, gbs, rc6 = vehicle(owner, HBIS, place=box), vehicle(owner, GBS), vehicle(owner, RC6)
    meet = new_meet(owner)
    trip = pack_list(owner, meet, hbis, gbs, gbs)
    assert trip["vehicles"] == 2
    assert [r["vehicle"]["litt"] for r in trip["rows"]] == ["Gbs", "Hbis"]
    assert row(trip, hbis)["vehicle"]["place_name"] == "Låda 3"
    trip = pack_list(owner, meet, hbis, rc6)
    assert sorted(r["vehicle"]["litt"] for r in trip["rows"]) == ["Hbis", "Rc6"]
    # Nothing on it moved: the list only points the vehicles out.
    assert state(owner, gbs) == ("home", None)


# --- The three steps (CAT-176–CAT-180, CAT-182) ------------------------------------------------


def test_the_whole_trip_with_one_vehicle_missing_at_home(
    owner: TestClient, other: TestClient
) -> None:
    box = place(owner, "Låda 3")
    hbis, gbs = vehicle(owner, HBIS, place=box), vehicle(owner, GBS, place=box)
    hbis_tag, gbs_tag = tagged(owner, hbis), tagged(owner, gbs)
    meet = new_meet(owner)
    pack_list(owner, meet, hbis, gbs)

    # Packa: one tapped, one pressed (CAT-176), and both are packed (CAT-177).
    packed = tap(owner, meet, hbis_tag)
    assert packed.status_code == 200, packed.text
    assert (packed.json()["outcome"], packed.json()["title"]) == ("ticked", "Hbis 2253")
    assert press(owner, meet, gbs, "pack").status_code == 200
    trip = owner.get(f"{API}/meets/{meet['id']}").json()
    assert (trip["done"], trip["step"]) == ({"pack": 2, "arrive": 0, "home": 0}, "arrive")
    assert [t["by"] for t in row(trip, hbis)["ticks"]] == ["tap"]
    assert [t["by"] for t in row(trip, gbs)["ticks"]] == ["press"]
    assert state(owner, hbis) == ("packed", "Låda 3")

    # På plats: a tap without a step ticks in the step the trip is at.
    for uid in (hbis_tag, gbs_tag):
        assert tap(owner, meet, uid).json()["outcome"] == "ticked"
    trip = owner.get(f"{API}/meets/{meet['id']}").json()
    assert (trip["done"]["arrive"], trip["step"]) == (2, "home")
    assert state(owner, gbs) == ("at_meet", "Låda 3")

    # Someone finds Gbs and says where it stands (CAT-113, CAT-180).
    told = other.post(f"{API}/tags/{gbs_tag}/notice", json={"text": "Står på Gårdsjö, spår 3."})
    assert told.status_code == 200, told.text

    # Hem: Hbis comes home, Gbs is missing and stands first with its last tick (CAT-179).
    home = tap(owner, meet, hbis_tag, "home").json()["trip"]
    assert (home["done"], home["step"], home["archived_at"]) == (
        {"pack": 2, "arrive": 2, "home": 1},
        "home",
        None,
    )
    first, second = home["rows"]
    assert (first["vehicle"]["id"], first["missing"]) == (gbs["id"], True)
    assert (first["last"]["step"], first["last"]["by"]) == ("arrive", "tap")
    assert first["last"] == first["ticks"][-1]
    assert [n["text"] for n in first["vehicle"]["notices"]] == ["Står på Gårdsjö, spår 3."]
    assert (second["vehicle"]["id"], second["missing"]) == (hbis["id"], False)
    assert second["last"]["step"] == "home"
    assert state(owner, hbis) == ("home", "Låda 3")
    assert state(owner, gbs) == ("at_meet", "Låda 3")


def test_a_double_tap_ticks_once(owner: TestClient) -> None:
    hbis = vehicle(owner, HBIS)
    uid = tagged(owner, hbis)
    meet = new_meet(owner)
    pack_list(owner, meet, hbis)
    first = tap(owner, meet, uid, "pack").json()["trip"]
    again = tap(owner, meet, uid, "pack").json()["trip"]
    assert row(again, hbis)["ticks"] == row(first, hbis)["ticks"]  # the first one stands
    assert press(owner, meet, hbis, "pack").status_code == 200
    assert len(owner.get(f"{API}/meets/{meet['id']}").json()["rows"][0]["ticks"]) == 1
    assert [s for s, _, _ in history(owner, hbis)] == ["packed", "home"]


def test_two_taps_at_the_same_time_give_one_tick(owner: TestClient) -> None:
    hbis = vehicle(owner, HBIS)
    uid = tagged(owner, hbis)
    meet = new_meet(owner)
    pack_list(owner, meet, hbis)
    answers: list[int] = []

    def tap_now() -> None:
        answers.append(tap(owner, meet, uid, "pack").status_code)

    threads = [threading.Thread(target=tap_now) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert answers == [200, 200, 200]
    assert owner.get(f"{API}/meets/{meet['id']}").json()["done"]["pack"] == 1
    assert [s for s, _, _ in history(owner, hbis)] == ["packed", "home"]


def test_a_vehicle_tapped_without_being_on_the_list_can_be_added(owner: TestClient) -> None:
    hbis, rc6 = vehicle(owner, HBIS), vehicle(owner, RC6)
    uid = tagged(owner, rc6)
    meet = new_meet(owner)
    pack_list(owner, meet, hbis)

    asked = tap(owner, meet, uid, "pack").json()
    assert (asked["outcome"], asked["vehicle_id"], asked["title"]) == (
        "not_on_list",
        rc6["id"],
        "Rc6 1340",
    )
    assert asked["trip"]["vehicles"] == 1
    assert state(owner, rc6) == ("home", None)  # nothing happened before the yes

    added = tap(owner, meet, uid, "pack", add=True).json()
    assert added["outcome"] == "ticked"
    assert added["trip"]["vehicles"] == 2
    assert [t["step"] for t in row(added["trip"], rc6)["ticks"]] == ["pack"]
    assert state(owner, rc6) == ("packed", None)


def test_someone_elses_tag_says_nothing_and_leaves_nothing(
    owner: TestClient, other: TestClient
) -> None:
    """CAT-110: a tap in the trip finds only the owner's own vehicles, and the lookup for
    others is the same as before."""
    hbis = vehicle(owner, HBIS)
    uid = tagged(owner, hbis)
    before = other.get(f"{API}/tags/{uid}").json()
    assert before["outcome"] == "private"
    assert set(before["card"]) == {"litt", "number", "kind", "operator", "scale", "thumbnail"}

    theirs = new_meet(other)
    answer = tap(other, theirs, uid)
    assert answer.status_code == 200
    assert (answer.json()["outcome"], answer.json()["vehicle_id"], answer.json()["title"]) == (
        "unknown",
        None,
        None,
    )
    assert answer.json()["trip"]["vehicles"] == 0
    unlinked = other.post(f"{API}/tags/simulated").json()["uid"]
    assert tap(other, theirs, unlinked).json()["outcome"] == "unknown"
    assert problem(tap(other, theirs, "inte en tagg")) == (422, "bad_tag")
    assert other.get(f"{API}/tags/{uid}").json() == before
    assert state(owner, hbis) == ("home", None)
    assert history(owner, hbis) == [("home", None, None)]


def test_home_puts_the_vehicle_back_at_its_place_and_the_history_has_the_trip(
    owner: TestClient,
) -> None:
    shelf = place(owner, "Hyllan")
    rc6 = vehicle(owner, RC6, place=shelf)
    meet = new_meet(owner, SOON)
    pack_list(owner, meet, rc6)

    assert press(owner, meet, rc6, "pack").status_code == 200
    assert state(owner, rc6) == ("packed", "Hyllan")  # the place stays its home place
    assert owner.get(f"{API}/places").json()[0]["vehicles_home"] == 0
    assert press(owner, meet, rc6, "arrive").status_code == 200
    assert press(owner, meet, rc6, "home").status_code == 200
    assert state(owner, rc6) == ("home", "Hyllan")
    assert owner.get(f"{API}/places").json()[0]["vehicles_home"] == 1
    assert history(owner, rc6) == [
        ("home", "Hyllan", "Höstträffen"),
        ("at_meet", "Hyllan", "Höstträffen"),
        ("packed", "Hyllan", "Höstträffen"),
        ("home", "Hyllan", None),
    ]

    # Taking a tick away moves the vehicle back, also as an event of its own.
    assert press(owner, meet, rc6, "home", ticked=False).status_code == 200
    assert state(owner, rc6) == ("at_meet", "Hyllan")
    assert history(owner, rc6)[0] == ("at_meet", "Hyllan", "Höstträffen")
    # Taken off the list while it is away on the trip, it comes home.
    assert pack_list(owner, meet)["vehicles"] == 0
    assert state(owner, rc6) == ("home", "Hyllan")


def test_a_vehicle_is_away_on_one_trip_at_a_time(owner: TestClient) -> None:
    hbis = vehicle(owner, HBIS)
    first = new_meet(owner)
    second = owner.post(f"{API}/meets", json={"name": "Vårträffen", "date": SOON}).json()
    pack_list(owner, first, hbis)
    pack_list(owner, second, hbis)
    assert press(owner, first, hbis, "pack").status_code == 200
    refused = press(owner, second, hbis, "pack")
    assert problem(refused) == (409, "on_another_trip")
    assert "Höstträffen" in refused.json()["message"]
    assert press(owner, first, hbis, "home").status_code == 200
    assert press(owner, second, hbis, "pack").status_code == 200
    assert state(owner, hbis) == ("packed", None)


def test_a_lent_vehicle_cannot_be_packed(owner: TestClient) -> None:
    hbis = vehicle(owner, HBIS)
    uid = tagged(owner, hbis)
    meet = new_meet(owner)
    pack_list(owner, meet, hbis)
    version = owner.get(f"{API}/vehicles/{hbis['id']}").json()["version"]
    lent = owner.post(f"{API}/vehicles/{hbis['id']}/lend", json={"version": version, "to": "Olle"})
    assert lent.status_code == 200, lent.text

    refused = press(owner, meet, hbis, "pack")
    assert problem(refused) == (422, "lent")
    assert refused.json()["message"] == "Ett utlånat fordon kan inte packas. Ta tillbaka det först."
    assert problem(tap(owner, meet, uid, "pack")) == (422, "lent")
    assert problem(press(owner, meet, hbis, "home")) == (422, "lent")
    assert owner.get(f"{API}/meets/{meet['id']}").json()["done"]["pack"] == 0
    assert state(owner, hbis)[0] == "lent"


def test_only_vehicles_on_the_list_and_the_owners_meets(
    owner: TestClient, other: TestClient
) -> None:
    hbis, gbs = vehicle(owner, HBIS), vehicle(owner, GBS)
    meet = new_meet(owner)
    pack_list(owner, meet, hbis)
    assert problem(press(owner, meet, gbs, "pack")) == (404, "not_found")
    theirs = vehicle(other, RC6)
    assert problem(press(owner, meet, theirs, "pack")) == (404, "not_found")
    missing = owner.post(f"{API}/meets/{meet['id']}/vehicles", json={"vehicles": [theirs["id"]]})
    assert problem(missing) == (404, "not_found")
    # Someone else's meet is not there at all (CAT-49).
    assert other.get(f"{API}/meets/{meet['id']}").status_code == 404
    assert problem(press(other, meet, theirs, "pack")) == (404, "not_found")
    assert other.get(f"{API}/meets").json() == []
    assert owner.get(f"{API}/meets").status_code == 200


# --- Archiving and the template (CAT-183) -----------------------------------------------------


def test_the_last_vehicle_home_archives_the_meet_once_its_date_has_come(
    owner: TestClient,
) -> None:
    hbis, gbs = vehicle(owner, HBIS), vehicle(owner, GBS)
    meet = new_meet(owner, PAST)
    pack_list(owner, meet, hbis, gbs)
    for car in (hbis, gbs):
        assert press(owner, meet, car, "pack").status_code == 200
    assert press(owner, meet, hbis, "home").json()["archived_at"] is None
    done = press(owner, meet, gbs, "home").json()
    assert done["archived_at"] is not None
    # An archived meet does not change.
    assert problem(press(owner, meet, gbs, "home", ticked=False)) == (409, "archived")
    assert problem(owner.post(f"{API}/meets/{meet['id']}/vehicles", json={"vehicles": []})) == (
        409,
        "archived",
    )
    assert owner.post(f"{API}/meets/{meet['id']}/archive").json() == done  # again is the same


def test_before_its_date_the_meet_is_archived_by_hand_when_nothing_is_away(
    owner: TestClient,
) -> None:
    hbis, gbs = vehicle(owner, HBIS), vehicle(owner, GBS)
    meet = new_meet(owner, SOON)
    pack_list(owner, meet, hbis, gbs)
    assert press(owner, meet, hbis, "pack").status_code == 200
    refused = owner.post(f"{API}/meets/{meet['id']}/archive")
    assert problem(refused) == (422, "not_back")
    assert press(owner, meet, hbis, "home").json()["archived_at"] is None  # the date is ahead
    archived = owner.post(f"{API}/meets/{meet['id']}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None


def test_an_archived_pack_list_is_the_template_for_the_next_meet(owner: TestClient) -> None:
    hbis, gbs = vehicle(owner, HBIS), vehicle(owner, GBS)
    spring = owner.post(f"{API}/meets", json={"name": "Vårträffen", "date": PAST}).json()
    pack_list(owner, spring, hbis, gbs)
    for car in (hbis, gbs):
        assert press(owner, spring, car, "home").status_code == 200
    assert owner.get(f"{API}/meets/{spring['id']}").json()["archived_at"] is not None

    autumn = new_meet(owner, SOON, template=spring["id"])
    assert autumn["template_of"] == spring["id"]
    assert sorted(r["vehicle"]["litt"] for r in autumn["rows"]) == ["Gbs", "Hbis"]
    assert all(r["ticks"] == [] for r in autumn["rows"])
    assert (autumn["step"], autumn["archived_at"]) == ("pack", None)
    # The active meets come first, then the archived ones.
    assert [m["name"] for m in owner.get(f"{API}/meets").json()] == ["Höstträffen", "Vårträffen"]
    unknown = owner.post(
        f"{API}/meets",
        json={"name": "X", "date": SOON, "template": "00000000-0000-4000-8000-000000000000"},
    )
    assert problem(unknown) == (404, "not_found")


# --- The right: the owner's own (CAT-46, CAT-49, CAT-77, CAT-182) ------------------------------


@dataclass
class Shared:
    id: PretendId
    a: TestClient
    b: TestClient


@pytest.fixture
def shared(database_url: str, tmp_path: Path) -> Iterator[Shared]:
    pretend = PretendId()
    settings = Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=tmp_path,
        tag_base=BASE,
        simulated_tags=True,
        id=IdSettings(
            issuer="https://id.example.test/realms/trainmeet",
            client="catalog",
            secret="hemlighet",
            public_url="https://catalog.example.test",
            internal="http://id:8080/realms/trainmeet",
            api="http://id-api:8080",
        ),
        build=CatalogVersion(version="0.1.0"),
    )
    app = create_app(settings, id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)))
    with TestClient(app) as a, TestClient(app) as b:
        for client, who in ((a, A), (b, B)):
            assert client.post(f"{API}/trial/login", json={"account": who}).status_code == 200
        yield Shared(pretend, a, b)


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_someone_the_fleet_is_shared_with_has_no_trip(shared: Shared, role: str) -> None:
    hbis = vehicle(shared.a, HBIS)
    meet = new_meet(shared.a)
    pack_list(shared.a, meet, hbis)
    in_a = f"fleet={A}"

    # Without a sharing the meets are not there (404); with one they need the owner (403).
    assert shared.b.get(f"{API}/meets?{in_a}").status_code == 404
    shared.id.roles[(B, A)] = role
    for answer in (
        shared.b.get(f"{API}/meets?{in_a}"),
        shared.b.get(f"{API}/meets/{meet['id']}?{in_a}"),
        shared.b.post(f"{API}/meets?{in_a}", json={"name": "Min", "date": SOON}),
        shared.b.post(
            f"{API}/meets/{meet['id']}/ticks?{in_a}",
            json={"vehicle": hbis["id"], "step": "pack"},
        ),
        shared.b.post(f"{API}/meets/{meet['id']}/vehicles?{in_a}", json={"vehicles": []}),
        shared.b.post(f"{API}/meets/{meet['id']}/archive?{in_a}"),
    ):
        assert problem(answer) == (403, "forbidden"), answer.text
    assert shared.a.get(f"{API}/vehicles/{hbis['id']}").json()["state"] == "home"
    assert shared.b.get(f"{API}/meets").json() == []  # B's own meets are B's


def test_a_clubs_administrators_take_the_clubs_fleet_to_the_meet(shared: Shared) -> None:
    club = "0f0e0d0c-3333-4444-8555-966677778888"
    shared.id.roles[(B, club)] = "admin"
    shared.id.titles[club] = "Vagnparken · Västby MJK"
    assert shared.b.get(f"{API}/fleets").status_code == 200  # the club gets an owner (CAT-51)
    in_club = f"fleet={club}"
    car = shared.b.post(f"{API}/vehicles?{in_club}", json=HBIS).json()
    meet = shared.b.post(f"{API}/meets?{in_club}", json={"name": "Klubbdagen", "date": SOON})
    assert meet.status_code == 201, meet.text
    listed = shared.b.post(
        f"{API}/meets/{meet.json()['id']}/vehicles?{in_club}", json={"vehicles": [car["id"]]}
    )
    assert listed.status_code == 200, listed.text
    assert shared.b.get(f"{API}/meets").json() == []  # not in B's own fleet
