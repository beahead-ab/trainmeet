"""A fleet shared with someone (#49): Catalog asks ID at every call (KONTO-34, CAT-48), and the
right decides what is seen and done, in one place (CAT-46, CAT-47, CAT-49, CAT-50).

A pretend ID answers Keycloak's client credentials and ID's API. The people log in with the
trial login, so their ids are fixed: Provkonto A owns the fleet and Provkonto B gets it shared.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.login import TRIAL_ACCOUNTS
from catalog.settings import IdSettings, Settings
from contracts.catalog import CatalogVersion

API = "/api/catalog/1"
BASE = "https://test.catalog.trainmeet.app/t/"
A, B = (str(TRIAL_ACCOUNTS[i].id) for i in (0, 1))
HBIS = {"status": "ready", "kind": "freight_wagon", "litt": "Hbis", "number": "21 74 245 2 253-0"}


@dataclass
class PretendId:
    """Who has which role to whose fleet, as ID says now."""

    roles: dict[tuple[str, str], str] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)
    apps: dict[str, list[str]] = field(default_factory=dict)
    down: bool = False
    tokens: int = 0
    asked: int = 0
    expire_next: bool = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("nere", request=request)
        if request.url.path.endswith("/token"):
            assert b"grant_type=client_credentials" in request.content
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"t{self.tokens}", "expires_in": 300})
        if self.expire_next:
            self.expire_next = False
            return httpx.Response(401, json={"code": "login", "message": "Gammal token."})
        assert request.headers["authorization"] == f"Bearer t{self.tokens}"
        self.asked += 1
        person = request.url.params["person"]
        if request.url.path.endswith("/apps/access"):
            owner = request.url.params["resource"].removeprefix("fleet:")
            role = self.roles.get((person, owner))
            return httpx.Response(200, json={"roles": [role] if role else []})
        if request.url.path.endswith("/apps/switcher"):
            return httpx.Response(200, json={"apps": self.apps.get(person, ["catalog", "id"])})
        if request.url.path.endswith("/apps/fleets"):
            shared = [
                {
                    "owner": {"kind": "fleet", "id": o},
                    "title": self.titles.get(o, "Vagnparken · Provkonto A"),
                    "role": "owner" if r == "admin" else r,
                }
                for (p, o), r in self.roles.items()
                if p == person
            ]
            return httpx.Response(200, json=shared)
        return httpx.Response(404)


@dataclass
class World:
    id: PretendId
    a: TestClient
    b: TestClient


@pytest.fixture
def world(database_url: str, tmp_path: Path) -> Iterator[World]:
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
        yield World(pretend, a, b)


def vehicle(client: TestClient, **fields: Any) -> dict[str, Any]:
    answer = client.post(f"{API}/vehicles", json={**HBIS, **fields})
    assert answer.status_code == 201, answer.text
    body: dict[str, Any] = answer.json()
    return body


def in_a(path: str) -> str:
    return f"{API}{path}{'&' if '?' in path else '?'}fleet={A}"


def test_without_a_sharing_someone_elses_fleet_is_not_there(world: World) -> None:
    car = vehicle(world.a)
    assert world.b.get(in_a("/vehicles")).status_code == 404
    assert world.b.get(in_a(f"/vehicles/{car['id']}")).status_code == 404
    assert world.b.get(f"{API}/vehicles/{car['id']}").status_code == 404  # not in B's own
    # The owner works as before, also with their own id given.
    assert world.a.get(in_a("/vehicles")).json()["total"] == 1


def test_to_look_shows_the_fleet_but_never_the_tag_or_the_messages(world: World) -> None:
    car = vehicle(world.a)
    tag = world.a.post(f"{API}/tags/simulated").json()["uid"]
    linked = world.a.post(f"{API}/tags/{tag}/link", json={"vehicle": car["id"], "confirm": True})
    assert linked.status_code == 200, linked.text
    world.id.roles[(B, A)] = "viewer"

    listed = world.b.get(in_a("/vehicles")).json()
    seen = listed["vehicles"][0]
    assert (seen["litt"], seen["tagged"], seen["tags"], seen["notices"]) == ("Hbis", True, [], [])
    assert tag not in str(listed)  # CAT-47
    assert world.a.get(f"{API}/vehicles/{car['id']}").json()["tags"] != []
    assert world.b.get(in_a("/places")).status_code == 200

    # Only to look: no changes, nothing that is the owner's (CAT-46, CAT-77).
    change = {**HBIS, "number": "1", "version": car["version"]}
    for answer in (
        world.b.put(in_a(f"/vehicles/{car['id']}"), json=change),
        world.b.post(in_a("/vehicles"), json=HBIS),
        world.b.get(in_a(f"/vehicles/{car['id']}/events")),
        world.b.post(in_a(f"/vehicles/{car['id']}/lend"), json={"to": "Kim", "version": 1}),
        world.b.post(in_a("/places"), json={"name": "Lådan"}),
    ):
        assert answer.status_code == 403, answer.text
        assert answer.json()["code"] == "forbidden"


def test_to_edit_changes_the_core_fields_and_adds_but_the_rest_stays_the_owners(
    world: World,
) -> None:
    box = world.a.post(f"{API}/places", json={"name": "Lådan"}).json()
    car = vehicle(world.a, place=box["id"])
    world.id.roles[(B, A)] = "editor"

    change = {**HBIS, "operator": "SJ", "place": None, "version": car["version"]}
    changed = world.b.put(in_a(f"/vehicles/{car['id']}"), json=change)
    assert changed.status_code == 200, changed.text
    assert changed.json()["operator"] == "SJ"
    assert changed.json()["place"] == box["id"]  # the places are the owner's (CAT-71)

    added = world.b.post(in_a("/vehicles"), json={**HBIS, "place": box["id"]})
    assert added.status_code == 201
    assert added.json()["place"] is None
    assert world.a.get(f"{API}/vehicles").json()["total"] == 2  # in A's fleet (CAT-50)
    assert world.b.get(f"{API}/vehicles").json()["total"] == 0

    for answer in (
        world.b.delete(in_a(f"/vehicles/{car['id']}?version=2")),
        world.b.post(in_a("/vehicles/move"), json={"vehicles": [car["id"]], "place": None}),
        world.b.delete(in_a(f"/places/{box['id']}")),
    ):
        assert answer.status_code == 403, answer.text


def test_stopping_the_sharing_applies_at_once(world: World) -> None:
    """CAT-48: ID is asked at every call, and the answer is never kept."""
    vehicle(world.a)
    world.id.roles[(B, A)] = "editor"
    assert world.b.get(in_a("/vehicles")).status_code == 200
    del world.id.roles[(B, A)]
    assert world.b.get(in_a("/vehicles")).status_code == 404


def test_without_id_nothing_shared_is_shown_but_the_own_fleet_works(world: World) -> None:
    vehicle(world.a)
    world.id.roles[(B, A)] = "viewer"
    world.id.down = True
    refused = world.b.get(in_a("/vehicles"))
    assert refused.status_code == 503 and refused.json()["code"] == "unavailable"
    assert world.a.get(f"{API}/vehicles").status_code == 200
    assert world.b.get(f"{API}/vehicles").status_code == 200


def test_the_person_chooses_among_their_own_and_the_shared_fleets(world: World) -> None:
    world.id.roles[(B, A)] = "viewer"
    fleets = world.b.get(f"{API}/fleets").json()
    assert [(f["owner"], f["right"]) for f in fleets] == [(B, "owner"), (A, "view")]
    assert fleets[0]["title"] == "Vagnparken · Provkonto B"
    session = world.a.get(f"{API}/session").json()
    assert session["share_url"] == f"https://id.example.test/vagnparker/{A}"


def test_a_tag_in_a_shared_fleet_opens_the_card_with_the_right(world: World) -> None:
    car = vehicle(world.a)
    tag = world.a.post(f"{API}/tags/simulated").json()["uid"]
    world.a.post(f"{API}/tags/{tag}/link", json={"vehicle": car["id"], "confirm": True})
    world.id.roles[(B, A)] = "editor"
    found = world.b.get(f"{API}/tags/{tag}").json()
    assert found == {"outcome": "fleet", "vehicle_id": car["id"], "right": "edit", "owner": A}
    # The card opens in the owner's fleet, which the answer names (#49).
    assert world.b.get(f"{API}/vehicles/{car['id']}", params={"fleet": A}).status_code == 200


def test_the_token_is_kept_and_renewed_once_when_id_says_it_is_old(world: World) -> None:
    world.id.roles[(B, A)] = "viewer"
    for _ in range(3):
        world.b.get(in_a("/vehicles"))
    assert world.id.tokens == 1 and world.id.asked == 3
    world.id.expire_next = True
    assert world.b.get(in_a("/vehicles")).status_code == 200
    assert world.id.tokens == 2


def test_the_owner_never_asks_id(world: World) -> None:
    vehicle(world.a)
    world.a.get(f"{API}/vehicles")
    world.a.get(in_a("/vehicles"))
    assert world.id.asked == 0
    assert UUID(A)


def test_the_share_button_goes_to_ids_web_app_where_it_is() -> None:
    from catalog.settings import from_env

    base = {
        "CATALOG_DATABASE_URL": "postgresql://db/catalog",
        "CATALOG_ID_ISSUER": "https://test.id.trainmeet.app/realms/trainmeet",
        "CATALOG_ID_SECRET": "x",
        "CATALOG_PUBLIC_URL": "https://test.catalog.trainmeet.app",
    }
    same = from_env(base).id
    assert same is not None and same.id_public == "https://test.id.trainmeet.app"
    apart = from_env({**base, "CATALOG_ID_WEB": "http://localhost:8002"}).id
    assert apart is not None and apart.id_public == "http://localhost:8002"


CLUB = "0f0e0d0c-3333-4444-8555-966677778888"


def test_a_clubs_administrators_have_the_owners_right_to_the_clubs_fleet(world: World) -> None:
    """CAT-51, C36, C39: the club's fleet gets an owner in Catalog when it is first listed, the
    administrators do the owner's things in it, and the members only look."""
    world.id.roles[(B, CLUB)] = "admin"
    world.id.roles[(A, CLUB)] = "viewer"
    world.id.titles[CLUB] = "Vagnparken · Västby MJK"
    fleets = world.b.get(f"{API}/fleets").json()
    club = next(f for f in fleets if f["owner"] == CLUB)
    assert (club["right"], club["title"]) == ("owner", "Vagnparken · Västby MJK")
    assert club["share_url"] == f"https://id.example.test/vagnparker/{CLUB}"

    in_club = f"fleet={CLUB}"
    box = world.b.post(f"{API}/places?{in_club}", json={"name": "Klubblådan"})
    assert box.status_code == 201, box.text
    car = world.b.post(f"{API}/vehicles?{in_club}", json={**HBIS, "place": box.json()["id"]})
    assert car.status_code == 201 and car.json()["place"] == box.json()["id"]
    tag = world.b.post(f"{API}/tags/simulated?{in_club}").json()["uid"]
    linked = world.b.post(
        f"{API}/tags/{tag}/link?{in_club}", json={"vehicle": car.json()["id"], "confirm": True}
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["tags"] != []  # the administrators see the tag
    assert world.b.get(f"{API}/vehicles").json()["total"] == 0  # not in B's own fleet

    # A member looks: the vehicle, but not the tag, and no tag work (CAT-46, CAT-47).
    seen = world.a.get(f"{API}/vehicles?{in_club}").json()["vehicles"][0]
    assert (seen["tagged"], seen["tags"]) == (True, [])
    unlink = world.a.post(
        f"{API}/vehicles/{car.json()['id']}/tags/unlink?{in_club}",
        json={"assignment": "00000000-0000-4000-8000-000000000000", "confirm": True},
    )
    assert unlink.status_code == 403
    assert world.a.post(f"{API}/vehicles?{in_club}", json=HBIS).status_code == 403

    # Tapped, the tag opens the card in the club's fleet (#49), with each one's right.
    found = world.b.get(f"{API}/tags/{tag}").json()
    assert (found["outcome"], found["owner"], found["right"]) == ("fleet", CLUB, "edit")
    assert world.a.get(f"{API}/tags/{tag}").json()["right"] == "view"
    # A tag is waited for in the club's fleet, where the next tap finds it (CAT-89, C39).
    waiting = world.b.post(
        f"{API}/tags/pending?{in_club}", json={"vehicle": car.json()["id"], "replace": None}
    )
    assert waiting.status_code == 200, waiting.text
    assert world.b.get(f"{API}/tags/pending?{in_club}").json()["pending"] is not None
    assert world.b.get(f"{API}/tags/pending").json()["pending"] is None


def test_the_session_has_the_apps_from_id_and_the_way_to_help(world: World) -> None:
    """ID11: the app switcher shows what ID says the person has something in. KONTO-06: Hjälp
    och fel is ID's page. Without an answer from ID the switcher shows every app."""
    world.id.apps[A] = ["hub", "catalog", "driver", "id", "something-new"]
    session = world.a.get(f"{API}/session").json()
    assert session["apps"] == ["hub", "catalog", "driver", "id"]
    assert session["help_url"] == "https://id.example.test/hjalp"
    world.id.down = True
    assert world.a.get(f"{API}/session").json()["apps"] is None
