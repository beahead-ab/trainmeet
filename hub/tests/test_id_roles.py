"""Rollerna från TrainMeet ID i Hubben (#78, ID10, PLAN-19, ID3).

The hub's meet is made from a meet in ID and linked to it; the roles there decide what someone
logged in with ID may do, asked of ID's API at every call (C35). A pretend ID answers the login
(hub/tests/test_id_login.py) and the API, with roles each test sets.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import hub as contract
from contracts import planning
from hub import id_login
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_id_login import INTERNAL, ISSUER, PIN, PUBLIC, SECRET, PretendId, back, to_id

API = "/api/planering/1"
ID_API = "http://id-api:8080"
AUTUMN = uuid.uuid4()
OTHER = uuid.uuid4()


@dataclass
class PretendIdApi(PretendId):
    """ID's login, and its API for the apps: the roles per person and meet, as a test sets
    them. The club's admin is counted as in ID: admin at every meet of the club."""

    roles: dict[str, list[str]] = field(default_factory=dict)
    club_admin: bool = False
    answering: bool = True
    asked: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/realms/trainmeet/protocol/openid-connect/token":
            form = request.content.decode()
            if "grant_type=client_credentials" in form:
                return httpx.Response(200, json={"access_token": "app-token", "expires_in": 300})
        if request.url.host == "id-api":
            if not self.answering:
                return httpx.Response(502)
            assert request.headers["authorization"] == "Bearer app-token"
            self.asked.append(request.url.path)
            person = request.url.params["person"]
            assert person == self.subject
            if request.url.path == "/api/id/1/apps/access":
                meet = request.url.params["resource"].removeprefix("meet:")
                held = list(self.roles.get(meet, []))
                if self.club_admin:
                    held.append("admin")
                return httpx.Response(200, json={"person": person, "resource": {}, "roles": held})
            if request.url.path == "/api/id/1/apps/meets":
                return httpx.Response(200, json=[self.meet(m) for m in (AUTUMN, OTHER)])
            return httpx.Response(404)
        return super().handle(request)

    def meet(self, meet: uuid.UUID) -> dict[str, Any]:
        name = "Höstträffen" if meet == AUTUMN else "Vårträffen"
        return {
            "id": str(meet),
            "club": str(uuid.UUID(int=1)),
            "club_name": "Västby MJK",
            "name": name,
            "starts_on": "2026-11-20",
            "ends_on": "2026-11-22",
            "roles": [r for r in self.roles.get(str(meet), []) if r != "admin"],
            "club_admin": self.club_admin,
        }


SETTINGS = id_login.IdSettings(
    issuer=ISSUER, secret=SECRET, public_url=PUBLIC, internal=INTERNAL, client="hub", api=ID_API
)


@pytest.fixture
def pretend() -> PretendIdApi:
    return PretendIdApi()


@pytest.fixture
def made(tmp_path: Path, pretend: PretendIdApi) -> Any:
    return create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )


@pytest.fixture
def owner(made: Any) -> TestClient:
    client = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert client.post("/api/hub/setup", json={"name": "Molnet", "pin": PIN}).status_code == 201
    return client


@pytest.fixture
def person(made: Any, owner: TestClient, pretend: PretendIdApi) -> TestClient:
    client = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert back(client, to_id(client, pretend)).status_code == 303
    return client


def make_meet(client: TestClient, id_meet: uuid.UUID | None = AUTUMN, name: str = "Höst") -> Any:
    body: dict[str, Any] = {"name": name}
    if id_meet is not None:
        body["id_meet"] = str(id_meet)
    return client.post(f"{API}/meets", json=body)


def test_the_organizer_makes_the_hubs_meet_from_the_meet_in_id_and_plans_it(
    owner: TestClient, person: TestClient, pretend: PretendIdApi
) -> None:
    pretend.roles = {str(AUTUMN): ["organizer"], str(OTHER): ["dispatcher"]}
    choices = [
        planning.IdMeetChoice.model_validate(c) for c in person.get(f"{API}/id-meets").json()
    ]
    assert [(c.name, c.hub_meet) for c in choices] == [("Höstträffen", None)], "only what they plan"

    made = make_meet(person)
    assert made.status_code == 201, made.text
    meet = planning.Draft.model_validate(made.json()).meet
    assert meet.id_meet == AUTUMN
    assert make_meet(person).status_code == 409, "a meet in ID gives one meet in the hub"
    assert person.get(f"{API}/id-meets").json()[0]["hub_meet"] == meet.id
    assert make_meet(person, None).status_code == 422, "someone with ID makes it from ID"

    # The PIN's own meet is not theirs; their own is.
    assert make_meet(owner, None, "Hubbens egen").status_code == 201
    listed = {s["meet"]["name"]: s["may_plan"] for s in person.get(f"{API}/meets").json()}
    assert listed == {"Höst": True, "Hubbens egen": False}
    assert all(s["may_plan"] for s in owner.get(f"{API}/meets").json())
    assert person.post(f"{API}/meets/hubbens-egen/versions").status_code == 403
    # Publishing is a choice per meet (PLAN-19, PLAN-24): the organizer without it plans, but
    # does not publish.
    refused = person.post(f"{API}/meets/{meet.id}/versions")
    assert (refused.status_code, refused.json()["detail"]) == (
        403,
        "Du får inte publicera den här träffen. Klubbens administratör ger rätten i TrainMeet ID.",
    )


def test_the_organizer_publishes_with_the_right_to_and_only_the_admin_withdraws(
    owner: TestClient, person: TestClient, pretend: PretendIdApi
) -> None:
    """PLAN-24, as in the old Cloud: Får publicera per meet, and only Administratör takes a
    publication away, since it may be the one a meet runs."""
    pretend.roles = {str(AUTUMN): ["organizer"]}
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id
    summary = planning.MeetSummary.model_validate(person.get(f"{API}/meets").json()[0])
    assert (summary.may_plan, summary.may_publish, summary.may_withdraw) == (True, False, False)

    pretend.roles = {str(AUTUMN): ["organizer", "publisher"]}
    summary = planning.MeetSummary.model_validate(person.get(f"{API}/meets").json()[0])
    assert (summary.may_plan, summary.may_publish, summary.may_withdraw) == (True, True, False)
    published = person.post(f"{API}/meets/{meet}/versions")
    assert published.status_code not in (401, 403), published.text
    refused = person.post(f"{API}/meets/{meet}/versions/1/withdraw")
    assert (refused.status_code, refused.json()["detail"]) == (
        403,
        "Bara klubbens administratör drar tillbaka en version.",
    )

    # Får publicera alone plans nothing.
    pretend.roles = {str(AUTUMN): ["publisher"]}
    assert person.post(f"{API}/meets/{meet}/versions").status_code == 403

    pretend.roles, pretend.club_admin = {}, True
    summary = planning.MeetSummary.model_validate(person.get(f"{API}/meets").json()[0])
    assert (summary.may_plan, summary.may_publish, summary.may_withdraw) == (True, True, True)
    assert person.post(f"{API}/meets/{meet}/versions/1/withdraw").status_code not in (401, 403)
    assert all(s["may_withdraw"] for s in owner.get(f"{API}/meets").json()), "the hub's PIN"


def test_a_reader_sees_the_plan_but_no_buttons(person: TestClient, pretend: PretendIdApi) -> None:
    """Läsare (H16): looks at the plan and changes nothing. Looking is open to everyone in
    Planering (S1, PLAN-37); the role gives no buttons."""
    pretend.roles = {str(AUTUMN): ["organizer"]}
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id
    pretend.roles = {str(AUTUMN): ["reader"]}
    assert person.get(f"{API}/id-meets").json() == [], "a reader makes no meet"
    summary = planning.MeetSummary.model_validate(person.get(f"{API}/meets").json()[0])
    assert (summary.may_plan, summary.may_publish, summary.may_withdraw) == (False, False, False)
    assert person.get(f"{API}/meets/{meet}").status_code == 200
    assert person.get(f"{API}/meets/{meet}/check").status_code == 200
    for refused in (
        person.post(f"{API}/meets/{meet}/versions"),
        person.post(f"{API}/meets/{meet}/versions/1/withdraw"),
        person.post(f"{API}/meets/{meet}/sources/okänd/apply", json={}),
    ):
        assert (refused.status_code, refused.json()["detail"]) == (
            403,
            "Din roll på träffen i TrainMeet ID ger inte rätt att ändra planen.",
        )


def test_a_role_taken_back_in_id_ends_at_once(person: TestClient, pretend: PretendIdApi) -> None:
    pretend.roles = {str(AUTUMN): ["organizer", "publisher"]}
    meet = planning.Draft.model_validate(make_meet(person).json()).meet.id
    assert person.post(f"{API}/meets/{meet}/versions").status_code not in (401, 403)
    pretend.roles = {}
    refused = person.post(f"{API}/meets/{meet}/versions")
    assert (refused.status_code, refused.json()["detail"]) == (
        403,
        "Du har ingen roll på den här träffen i TrainMeet ID.",
    )
    assert person.get(f"{API}/meets").json()[0]["may_plan"] is False


def test_the_clubs_admin_plans_every_meet_of_the_club(
    person: TestClient, pretend: PretendIdApi
) -> None:
    pretend.club_admin = True
    assert {c["name"] for c in person.get(f"{API}/id-meets").json()} == {
        "Höstträffen",
        "Vårträffen",
    }
    assert make_meet(person, OTHER, "Vår").status_code == 201


def test_without_a_role_nothing_is_made(person: TestClient, pretend: PretendIdApi) -> None:
    pretend.roles = {str(AUTUMN): ["loco_lead"]}
    assert person.get(f"{API}/id-meets").json() == []
    refused = make_meet(person)
    assert refused.status_code == 403
    anonymous = TestClient(person.app, base_url=PUBLIC)
    assert anonymous.post(f"{API}/meets", json={"name": "X"}).status_code == 401


def test_the_dispatcher_in_id_runs_the_meet_that_runs(
    made: Any, owner: TestClient, person: TestClient, pretend: PretendIdApi
) -> None:
    """ID3: Trafikledare at the meet in ID runs it in Drift. Here the meet that runs is linked
    to ID's meet by hand; a published version carries the link."""
    assert owner.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    store = made.state.running.store
    store.package = store.package.model_copy(
        update={"meet": store.package.meet.model_copy(update={"id_meet": AUTUMN})}
    )
    seen = contract.HubInfo.model_validate(person.get("/api/hub").json())
    assert (seen.logged_in, seen.may_run, seen.admin) == (True, False, False)
    assert person.get("/api/drift/1/clients").status_code == 403

    pretend.roles = {str(AUTUMN): ["dispatcher"]}
    seen = contract.HubInfo.model_validate(person.get("/api/hub").json())
    assert seen.may_run is True and seen.meet_role is None
    assert person.get("/api/drift/1/clients").status_code == 200
    assert person.post("/api/drift/1/clock", json={"action": "start"}).status_code == 200
    # Trafikledare gives the one-time code too (H56), and never the hub's own settings.
    assert person.post("/api/drift/1/codes", json={}).status_code == 201
    assert person.get("/api/hub/ai").status_code == 401

    # ID does not answer: no roles from it, and the PIN works as before.
    pretend.answering = False
    assert person.get("/api/drift/1/clients").status_code == 503
    assert contract.HubInfo.model_validate(person.get("/api/hub").json()).may_run is False
    assert owner.get("/api/drift/1/clients").status_code == 200


def test_only_the_pin_starts_provbanan(person: TestClient, pretend: PretendIdApi) -> None:
    pretend.club_admin = True
    assert person.post("/api/drift/1/start", json={"version": 1}).status_code == 403
