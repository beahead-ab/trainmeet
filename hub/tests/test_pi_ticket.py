"""Biljetten för inloggning på träffens Pi utan internet (KONTO-11, KONTO-37, F18, #78).

Two hubs in one process, as in hub/tests/test_synk.py: the Pi follows the cloud, and its calls
go to the cloud's app. A pretend ID answers the cloud's login and ID's API, and signs tickets
with an ES256 key of its own, as ID does (id/tickets.py).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from contracts import hub as contract
from contracts import sync
from hub import id_login
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.hubben import TICKET_COOKIE
from hub.tests.test_id_login import INTERNAL, ISSUER, PUBLIC, SECRET
from hub.tests.test_id_roles import AUTUMN, PretendIdApi
from hub.tests.test_planering import API, DRIFT, MEET, upload
from hub.tests.test_synk import SYNC, follow, link, set_up, wire

ID_API = "http://id-api:8080"
ID_PUBLIC = "https://id.example.test"
PI = "http://pi.local"


@dataclass
class PretendIdTickets(PretendIdApi):
    """ID's tickets too: signed with a key of ID's own, the roles as the test sets them."""

    ticket_key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    tickets: list[dict[str, Any]] = field(default_factory=list)
    lifetime: int = 30 * 86400

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "id-api" and request.url.path == "/api/id/1/keys":
            public = jwt.algorithms.ECAlgorithm.to_jwk(self.ticket_key.public_key(), as_dict=True)
            return httpx.Response(
                200, json={"keys": [{**public, "kid": "b1", "use": "sig", "alg": "ES256"}]}
            )
        if request.url.host == "id-api" and request.url.path == "/api/id/1/apps/tickets":
            assert request.headers["authorization"] == "Bearer app-token"
            asked: dict[str, Any] = json.loads(request.content)
            self.tickets.append(asked)
            return httpx.Response(200, json={"ticket": self.sign(asked), "expires": "2026-12-18"})
        return super().handle(request)

    def sign(self, asked: dict[str, Any], **change: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ID_PUBLIC,
            "aud": "trainmeet-hub:" + asked["hub"],
            "sub": asked["person"],
            "name": "Provare Ett",
            "roles": {m: list(self.roles.get(m, [])) for m in asked["meets"]},
            "iat": now,
            "exp": now + self.lifetime,
            "typ": "trainmeet-pi-ticket",
            **change,
        }
        return jwt.encode(claims, self.ticket_key, algorithm="ES256", headers={"kid": "b1"})


SETTINGS = id_login.IdSettings(
    issuer=ISSUER, secret=SECRET, public_url=PUBLIC, internal=INTERNAL, client="hub", api=ID_API
)


@pytest.fixture
def pretend() -> PretendIdTickets:
    return PretendIdTickets()


@pytest.fixture
def cloud(tmp_path: Path, pretend: PretendIdTickets) -> TestClient:
    """The cloud hub, ID's client, with the meet linked to the meet in ID and published."""
    made = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "moln" / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    client = set_up(TestClient(made, base_url=PUBLIC, follow_redirects=False), "Molnet")
    meet = {"name": "Värnamo Moduldagar", "first_date": "2026-10-30", "id_meet": str(AUTUMN)}
    assert client.post(API + "/meets", json=meet).status_code == 201
    source = upload(client).json()["source"]["id"]
    assert client.post(f"{API}/meets/{MEET}/sources/{source}/apply").status_code == 200
    assert client.post(f"{API}/meets/{MEET}/versions").status_code == 201
    return client


@pytest.fixture
def pi(cloud: TestClient, tmp_path: Path) -> TestClient:
    """The meet's Pi, linked to the cloud, with the version and the meet started."""
    made = create_app(
        BuildInfo(version="0.1.0"), preview_db=tmp_path / "pi" / "p.db", sync_call=wire(cloud)
    )
    owner = set_up(TestClient(made, base_url=PI, follow_redirects=False), "Pi:n")
    assert link(owner, cloud).status_code == 200
    follow(owner)
    started = owner.post(f"{DRIFT}/start", json={"meet": MEET, "version": 1})
    assert started.status_code == 201, started.text
    return owner


def browser(client: TestClient, base: str) -> TestClient:
    return TestClient(client.app, base_url=base, follow_redirects=False)


def log_in_on_the_pi(pi: TestClient, cloud: TestClient, pretend: PretendIdTickets) -> TestClient:
    """The whole way: the Pi's login, the cloud and ID, and back to the Pi with the ticket."""
    on_pi = browser(pi, PI)
    assert contract.HubInfo.model_validate(on_pi.get("/api/hub").json()).id_login is True
    sent = on_pi.get("/api/hub/id/login")
    assert sent.status_code == 303, sent.text
    to_cloud = urlparse(sent.headers["location"])
    assert f"{to_cloud.scheme}://{to_cloud.netloc}" == PUBLIC
    in_cloud = browser(cloud, PUBLIC)
    at_id = in_cloud.get(to_cloud.path + "?" + to_cloud.query)
    assert at_id.status_code == 303
    query = {k: v[0] for k, v in parse_qs(urlparse(at_id.headers["location"]).query).items()}
    pretend.nonce = query["nonce"]
    back = in_cloud.get("/api/hub/id/callback", params={"code": "k", "state": query["state"]})
    assert back.status_code == 303, back.text
    to_pi = urlparse(back.headers["location"])
    assert (f"{to_pi.scheme}://{to_pi.netloc}", to_pi.path) == (PI, "/api/hub/id/back")
    assert contract.HubInfo.model_validate(in_cloud.get("/api/hub").json()).logged_in is False
    home = on_pi.get(to_pi.path + "?" + to_pi.query)
    assert (home.status_code, home.headers["location"]) == (303, "/")
    return on_pi


def test_logged_in_on_the_pi_through_the_cloud_with_the_roles_from_id(
    pi: TestClient, cloud: TestClient, pretend: PretendIdTickets
) -> None:
    pretend.roles = {str(AUTUMN): ["dispatcher"]}
    on_pi = log_in_on_the_pi(pi, cloud, pretend)
    seen = contract.HubInfo.model_validate(on_pi.get("/api/hub").json())
    assert (seen.person, seen.logged_in, seen.admin, seen.may_run) == (
        "Provare Ett",
        True,
        False,
        True,
    )
    assert pretend.tickets[-1]["meets"] == [str(AUTUMN)]
    assert pretend.tickets[-1]["hub"] == pi.app.state.follower.links.hub_id()  # type: ignore[attr-defined]
    # Trafikledare from the ticket runs the meet on the Pi, but not the Pi's own settings.
    assert on_pi.get(f"{DRIFT}/clients").status_code == 200
    assert on_pi.get("/api/hub/ai").status_code == 401
    ticket = on_pi.cookies.get(TICKET_COOKIE)
    assert ticket and "Provare" not in ticket.split(".")[0]


def test_without_internet_the_ticket_lets_the_person_in_again(
    pi: TestClient, cloud: TestClient, pretend: PretendIdTickets
) -> None:
    pretend.roles = {str(AUTUMN): ["dispatcher"]}
    ticket = log_in_on_the_pi(pi, cloud, pretend).cookies.get(TICKET_COOKIE)
    # No internet now: ID does not answer, and the Pi checks the ticket with the keys it has,
    # calling no one. The browser has only its ticket.
    pretend.answering = False
    asked = len(pretend.asked)
    later = browser(pi, PI)
    later.cookies.set(TICKET_COOKIE, str(ticket), path="/api/hub")
    seen = contract.HubInfo.model_validate(later.get("/api/hub").json())
    assert (seen.logged_in, seen.ticket_name) == (False, "Provare Ett")
    again = later.post("/api/hub/id/again")
    assert again.status_code == 200, again.text
    assert later.get(f"{DRIFT}/clients").status_code == 200, "the ticket's role (KONTO-37)"
    assert len(pretend.asked) == asked, "nothing asked of ID"
    # Logga ut forgets the ticket in this browser.
    out = later.post("/api/hub/logout")
    assert any(c.startswith(TICKET_COOKIE + '=""') for c in out.headers.get_list("set-cookie"))


def test_a_ticket_that_does_not_hold_lets_no_one_in(
    pi: TestClient, cloud: TestClient, pretend: PretendIdTickets
) -> None:
    log_in_on_the_pi(pi, cloud, pretend)
    hub_id = pi.app.state.follower.links.hub_id()  # type: ignore[attr-defined]
    asked = {"person": pretend.subject, "hub": hub_id, "meets": [str(AUTUMN)]}
    stranger = ec.generate_private_key(ec.SECP256R1())
    bad = {
        "run out": pretend.sign(asked, exp=int(time.time()) - 3600),
        "another Pi": pretend.sign({**asked, "hub": "en-annan-pi"}),
        "not a ticket": pretend.sign(asked, typ="något annat"),
        "not ID's key": jwt.encode(
            {"sub": pretend.subject, "aud": "trainmeet-hub:" + hub_id, "iss": ID_PUBLIC},
            stranger,
            algorithm="ES256",
            headers={"kid": "b1"},
        ),
    }
    for why, ticket in bad.items():
        someone = browser(pi, PI)
        someone.cookies.set(TICKET_COOKIE, ticket, path="/api/hub")
        assert someone.post("/api/hub/id/again").status_code == 401, why
        assert someone.get("/api/hub").json()["ticket_name"] is None, why


def test_only_the_pi_that_asked_gets_the_ticket_once(
    pi: TestClient, cloud: TestClient, pretend: PretendIdTickets
) -> None:
    key = pi.app.state.follower.links.reaches()[0].key  # type: ignore[attr-defined]
    as_pi = {"Authorization": f"Bearer {key}", "TrainMeet-Sync": "trainmeet.sync/1"}
    start = f"{SYNC}/meets/{MEET}/id-login"
    assert cloud.post(start, json={"back": PI + "/api/hub/id/back"}).status_code == 401
    for wrong in ("https://elak.example.test/stjal", PI + "/api/hub/id/back?x=1", "ftp://pi"):
        assert cloud.post(start, json={"back": wrong}, headers=as_pi).status_code == 422, wrong
    started = sync.PiLoginStarted.model_validate(
        cloud.post(start, json={"back": PI + "/api/hub/id/back"}, headers=as_pi).json()
    )
    # Not ready before the person logged in, and never for someone without the Pi's key.
    assert cloud.get(f"{start}/{started.attempt}", headers=as_pi).status_code == 404
    assert cloud.get(f"{start}/{started.attempt}").status_code == 401
    # A browser that did not start the login on the Pi cannot finish it there.
    other = browser(pi, PI)
    assert (
        other.get("/api/hub/id/back", params={"attempt": started.attempt}).headers["location"]
        == "/?inloggning=fel"
    )
    gone = browser(cloud, PUBLIC).get("/api/hub/id/login", params={"pi": "inte-ett-försök"})
    assert gone.status_code == 410


def test_a_hub_without_a_cloud_has_no_login_with_id(tmp_path: Path) -> None:
    alone = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    set_up(alone, "Ensam")
    assert alone.get("/api/hub").json()["id_login"] is False
    assert alone.get("/api/hub/id/login", follow_redirects=False).status_code == 404
    assert alone.post("/api/hub/id/again").status_code == 401
