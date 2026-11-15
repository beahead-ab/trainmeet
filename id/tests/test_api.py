"""ID's API (#67): clubs, shared fleets, invitations and what the apps ask (KONTO-34).

A pretend Keycloak signs the tokens with a key made for the test, and a pretend mail server
keeps the invitations. The database is a fresh PostgreSQL per test, as Catalog's tests.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from psycopg import conninfo

from id.app import create_app
from id.login import COOKIE, safe_next
from id.mail import invitation_text
from id.roles import hidden
from id.settings import Settings, from_env

API = "/api/id/1"
ISSUER = "https://id.example.test/realms/trainmeet"
INTERNAL = "http://id:8080/realms/trainmeet"
PUBLIC = "https://id.example.test"
SECRET = "klienthemlighet-for-provet"


@pytest.fixture
def database_url() -> Iterator[str]:
    admin = (
        os.environ.get("ID_TEST_DATABASE_URL", "").strip()
        or os.environ.get("CATALOG_TEST_DATABASE_URL", "").strip()
    )
    if not admin:
        if os.environ.get("CI"):
            pytest.fail("ID_TEST_DATABASE_URL saknas i CI: databastesterna för ID måste köras.")
        pytest.skip("ID_TEST_DATABASE_URL saknas: inga databastester för ID.")
    name = f"id_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(admin, dbname=name)
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@dataclass
class PretendKeycloak:
    key: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    claims: dict[str, Any] = field(default_factory=dict)
    nonce: str = ""

    def sign(self, claims: dict[str, Any]) -> str:
        now = int(time.time())
        body = {"iss": ISSUER, "iat": now, "exp": now + 300, **claims}
        return jwt.encode(body, self.key, algorithm="RS256", headers={"kid": "k1"})

    def app_token(self, app: str = "catalog") -> str:
        return self.sign({"sub": str(uuid.uuid4()), "azp": app, "aud": "account"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/certs"):
            public = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return httpx.Response(200, json={"keys": [{**public, "kid": "k1", "alg": "RS256"}]})
        if request.url.path.endswith("/token"):
            claims = {"aud": "id", "azp": "id", "nonce": self.nonce, **self.claims}
            return httpx.Response(200, json={"id_token": self.sign(claims)})
        return httpx.Response(404)


@dataclass
class PretendMail:
    sent: list[tuple[str, str, str, str]] = field(default_factory=list)
    help_sent: list[tuple[str, str, str, str]] = field(default_factory=list)

    def invitation(self, to: str, title: str, sender: str, link: str) -> None:
        self.sent.append((to, title, sender, link))

    def help(self, to: str, reply_to: str, subject: str, body: str) -> None:
        self.help_sent.append((to, reply_to, subject, body))


@dataclass
class World:
    url: str
    keycloak: PretendKeycloak
    mail: PretendMail
    app: Any

    def browser(self) -> TestClient:
        return TestClient(self.app, base_url=PUBLIC, follow_redirects=False)


@pytest.fixture
def world(database_url: str, tmp_path: Path) -> Iterator[World]:
    keycloak, mail = PretendKeycloak(), PretendMail()
    settings = Settings(
        database_url=database_url,
        issuer=ISSUER,
        internal=INTERNAL,
        client="id",
        secret=SECRET,
        public_url=PUBLIC,
        apps=("catalog",),
        web_dir=tmp_path,
        support="support@example.test",
    )
    http = httpx.Client(transport=httpx.MockTransport(keycloak.handle))
    app = create_app(settings, http=http, mailer=mail)
    with TestClient(app):  # runs the migrations once
        yield World(database_url, keycloak, mail, app)


@dataclass
class Who:
    id: str
    name: str
    email: str
    client: TestClient


def log_in(world: World, name: str, email: str, subject: str | None = None) -> Who:
    client = world.browser()
    client.__enter__()
    # The same address is the same account in Keycloak, as in a real login.
    subject = subject or str(uuid.uuid5(uuid.NAMESPACE_URL, "konto:" + email.lower()))
    to_keycloak = client.get(f"{API}/login", params={"next": "/klubbar"})
    query = {k: v[0] for k, v in parse_qs(urlparse(to_keycloak.headers["location"]).query).items()}
    world.keycloak.nonce = query["nonce"]
    world.keycloak.claims = {
        "sub": subject,
        "name": name,
        "email": email,
        "email_verified": True,
    }
    back = client.get(f"{API}/login/callback", params={"code": "c", "state": query["state"]})
    assert back.status_code == 303 and back.headers["location"] == "/klubbar", back.headers
    assert COOKIE in back.cookies
    return Who(subject, name, email, client)


def apps(world: World, path: str, token: str | None = None, **params: str) -> httpx.Response:
    client = world.browser()
    headers = {"Authorization": f"Bearer {token or world.keycloak.app_token()}"}
    answer: httpx.Response = client.get(f"{API}/apps/{path}", params=params, headers=headers)
    return answer


def test_logging_in_keeps_the_person_and_their_verified_address(world: World) -> None:
    kim = log_in(world, "Kim Ek", "Kim@Example.com")
    session = kim.client.get(f"{API}/session").json()
    assert session["account"]["name"] == "Kim Ek"
    assert session["account"]["email"] == "kim@example.com"
    out = kim.client.delete(f"{API}/session").json()
    assert out["account"] is None and out["logout_url"].startswith(ISSUER)
    assert kim.client.get(f"{API}/clubs").status_code == 401


def test_an_unverified_address_logs_no_one_in(world: World) -> None:
    client = world.browser()
    to_keycloak = client.get(f"{API}/login")
    query = {k: v[0] for k, v in parse_qs(urlparse(to_keycloak.headers["location"]).query).items()}
    world.keycloak.nonce = query["nonce"]
    world.keycloak.claims = {"sub": str(uuid.uuid4()), "name": "X", "email": "x@example.com"}
    back = client.get(f"{API}/login/callback", params={"code": "c", "state": query["state"]})
    assert back.headers["location"] == "/?inloggning=fel"
    assert COOKIE not in back.cookies


def test_a_club_is_made_invited_to_and_joined(world: World) -> None:
    kim = log_in(world, "Kim Ek", "kim@example.com")
    club = kim.client.post(f"{API}/clubs", json={"name": "Västby MJK"})
    assert club.status_code == 201
    assert club.json()["role"] == "admin"  # the creator is admin (KONTO-35)
    club_id = club.json()["id"]

    invited = kim.client.post(
        f"{API}/clubs/{club_id}/invitations", json={"email": "Sara@example.com"}
    )
    assert invited.status_code == 201, invited.text
    assert world.mail.sent == [
        ("sara@example.com", "Västby MJK", "Kim Ek", PUBLIC + "/inbjudningar")
    ]
    again = kim.client.post(
        f"{API}/clubs/{club_id}/invitations", json={"email": "sara@example.com"}
    )
    assert again.status_code == 409
    page = kim.client.get(f"{API}/clubs/{club_id}").json()
    assert [i["sent_to"] for i in page["invitations"]] == ["s***@example.com"]

    # Someone else's address cannot answer, and does not even see the invitation.
    olle = log_in(world, "Olle Berg", "olle@example.com")
    assert olle.client.get(f"{API}/invitations").json() == []
    invitation = invited.json()["id"]
    answer = olle.client.post(f"{API}/invitations/{invitation}/answer", json={"accept": True})
    assert answer.status_code == 404
    assert olle.client.get(f"{API}/clubs/{club_id}").status_code == 404  # KONTO-17

    sara = log_in(world, "Sara Holm", "sara@example.com")
    waiting = sara.client.get(f"{API}/invitations").json()
    assert [(w["title"], w["sent_to"], w["sent_by"]["name"]) for w in waiting] == [
        ("Västby MJK", "sara@example.com", "Kim Ek")
    ]
    accepted = sara.client.post(f"{API}/invitations/{invitation}/answer", json={"accept": True})
    assert accepted.json()["state"] == "accepted"
    assert [c["role"] for c in sara.client.get(f"{API}/clubs").json()] == ["member"]
    members = sara.client.get(f"{API}/clubs/{club_id}").json()
    assert [(m["person"]["name"], m["role"]) for m in members["members"]] == [
        ("Kim Ek", "admin"),
        ("Sara Holm", "member"),
    ]
    assert members["invitations"] == []  # only the admin sees them
    assert "email" not in str(members["members"])  # never the members' addresses

    # A member may not invite (KONTO-35).
    refused = sara.client.post(
        f"{API}/clubs/{club_id}/invitations", json={"email": "a@example.com"}
    )
    assert refused.status_code == 403
    assert (
        sara.client.post(
            f"{API}/invitations/{invitation}/answer", json={"accept": True}
        ).status_code
        == 409
    )


def test_members_leave_and_are_removed_but_a_club_keeps_an_admin(world: World) -> None:
    kim = log_in(world, "Kim Ek", "kim@example.com")
    club_id = kim.client.post(f"{API}/clubs", json={"name": "Västby MJK"}).json()["id"]
    for name, email in (("Sara Holm", "sara@example.com"), ("Olle Berg", "olle@example.com")):
        invitation = kim.client.post(
            f"{API}/clubs/{club_id}/invitations", json={"email": email}
        ).json()
        person = log_in(world, name, email)
        person.client.post(f"{API}/invitations/{invitation['id']}/answer", json={"accept": True})
    sara = log_in(world, "Sara Holm", "sara@example.com")
    olle = log_in(world, "Olle Berg", "olle@example.com")
    olle_id = olle.client.get(f"{API}/session").json()["account"]["id"]
    kim_id = kim.client.get(f"{API}/session").json()["account"]["id"]

    assert sara.client.delete(f"{API}/clubs/{club_id}/members/{olle_id}").status_code == 403
    left = kim.client.delete(f"{API}/clubs/{club_id}/members/{olle_id}")
    assert [m["person"]["name"] for m in left.json()["members"]] == ["Kim Ek", "Sara Holm"]
    sara_id = sara.client.get(f"{API}/session").json()["account"]["id"]
    assert sara.client.delete(f"{API}/clubs/{club_id}/members/{sara_id}").status_code == 204
    assert sara.client.get(f"{API}/clubs").json() == []
    last = kim.client.delete(f"{API}/clubs/{club_id}/members/{kim_id}")
    assert last.status_code == 409


def test_a_fleet_is_shared_after_a_yes_and_unshared_at_once(world: World) -> None:
    """CAT-44, CAT-45, CAT-48 and KONTO-34: what Catalog will ask."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    kim_id = kim.client.get(f"{API}/session").json()["account"]["id"]
    invited = kim.client.post(
        f"{API}/fleets/{kim_id}/invitations", json={"email": "sara@example.com", "role": "editor"}
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["title"] == "Vagnparken · Kim Ek"
    assert world.mail.sent[-1][0] == "sara@example.com"
    own = kim.client.post(
        f"{API}/fleets/{kim_id}/invitations", json={"email": "kim@example.com", "role": "viewer"}
    )
    assert own.status_code == 422

    sara = log_in(world, "Sara Holm", "sara@example.com")
    sara_id = sara.client.get(f"{API}/session").json()["account"]["id"]
    resource = f"fleet:{kim_id}"
    # No access before the yes (CAT-45).
    assert apps(world, "access", person=sara_id, resource=resource).json()["roles"] == []
    sara.client.post(f"{API}/invitations/{invited.json()['id']}/answer", json={"accept": True})
    assert apps(world, "access", person=sara_id, resource=resource).json()["roles"] == ["editor"]
    assert apps(world, "fleets", person=sara_id).json() == [
        {
            "owner": {"kind": "fleet", "id": kim_id},
            "title": "Vagnparken · Kim Ek",
            "role": "editor",
        }
    ]
    # Only the owner sees and changes the sharing (KONTO-36).
    assert sara.client.get(f"{API}/fleets/{kim_id}").status_code == 404
    page = kim.client.get(f"{API}/fleets/{kim_id}").json()
    assert [(g["person"]["name"], g["role"]) for g in page["grants"]] == [("Sara Holm", "editor")]
    # Nobody else stops someone's sharing.
    grant = page["grants"][0]["id"]
    olle = log_in(world, "Olle Berg", "olle@example.com")
    assert olle.client.delete(f"{API}/grants/{grant}").status_code == 404
    # Stopping the sharing applies at once (CAT-48).
    assert kim.client.delete(f"{API}/grants/{grant}").status_code == 200
    assert apps(world, "access", person=sara_id, resource=resource).json()["roles"] == []
    assert apps(world, "fleets", person=sara_id).json() == []


def test_a_declined_or_withdrawn_invitation_gives_nothing(world: World) -> None:
    kim = log_in(world, "Kim Ek", "kim@example.com")
    kim_id = kim.client.get(f"{API}/session").json()["account"]["id"]
    first = kim.client.post(
        f"{API}/fleets/{kim_id}/invitations", json={"email": "sara@example.com", "role": "viewer"}
    ).json()
    sara = log_in(world, "Sara Holm", "sara@example.com")
    sara_id = sara.client.get(f"{API}/session").json()["account"]["id"]
    declined = sara.client.post(f"{API}/invitations/{first['id']}/answer", json={"accept": False})
    assert declined.json()["state"] == "declined"
    assert apps(world, "access", person=sara_id, resource=f"fleet:{kim_id}").json()["roles"] == []

    second = kim.client.post(
        f"{API}/fleets/{kim_id}/invitations", json={"email": "sara@example.com", "role": "viewer"}
    ).json()
    assert sara.client.delete(f"{API}/invitations/{second['id']}").status_code == 404
    assert kim.client.delete(f"{API}/invitations/{second['id']}").status_code == 200
    assert sara.client.get(f"{API}/invitations").json() == []


def test_only_the_apps_may_ask_and_only_with_their_own_token(world: World) -> None:
    person = str(uuid.uuid4())
    client = world.browser()
    assert client.get(f"{API}/apps/fleets", params={"person": person}).status_code == 401
    other_app = world.keycloak.app_token("an-other-app")
    assert apps(world, "fleets", token=other_app, person=person).status_code == 401
    web_app = world.keycloak.app_token("id")  # the web app's own client is not an app
    assert apps(world, "fleets", token=web_app, person=person).status_code == 401
    forged = PretendKeycloak().app_token()
    assert apps(world, "fleets", token=forged, person=person).status_code == 401
    assert apps(world, "fleets", person=person).json() == []
    wrong = apps(world, "access", person=person, resource="vagn:1")
    assert wrong.status_code == 422


def test_the_published_contract_lists_exactly_the_apis_addresses(world: World) -> None:
    import json

    from contracts.generate import ID_OPENAPI

    def addresses(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
        return {
            (method.upper(), path)
            for path, methods in paths.items()
            if path.startswith("/api/") and "{rest" not in path
            for method in methods
        }

    published = json.loads(ID_OPENAPI.read_text(encoding="utf-8"))["paths"]
    assert addresses(world.app.openapi()["paths"]) == addresses(published)


@pytest.mark.parametrize(
    ("asked", "safe"),
    [
        ("/klubbar", "/klubbar"),
        ("//elak.example", "/"),
        ("/api/id/1/session", "/"),
        ("/realms/trainmeet/account", "/"),
        ("https://elak.example", "/"),
        (None, "/"),
    ],
)
def test_the_page_to_come_back_to_is_always_ids_own(asked: str | None, safe: str) -> None:
    assert safe_next(asked) == safe


def test_others_see_an_address_partly_hidden() -> None:
    assert hidden("sara.holm@example.com") == "s***@example.com"


def test_the_invitation_mail_says_who_and_what_and_that_it_gives_nothing_yet() -> None:
    subject, body = invitation_text("Västby MJK", "Kim Ek", PUBLIC + "/inbjudningar")
    assert subject == "Kim Ek bjuder in dig: Västby MJK"
    assert PUBLIC + "/inbjudningar" in body
    assert "ger ingenting förrän du har svarat ja" in body


def test_the_settings_come_from_the_environment_without_showing_secrets() -> None:
    settings = from_env(
        {
            "ID_API_DATABASE_URL": "postgresql://id:hemligt@id-db/idapi",
            "ID_API_ISSUER": ISSUER,
            "ID_API_INTERNAL": INTERNAL,
            "ID_API_SECRET": SECRET,
            "ID_API_PUBLIC_URL": PUBLIC,
            "ID_API_APPS": "catalog, cad",
            "ID_SMTP_HOST": "smtp.example.test",
        }
    )
    assert settings.apps == ("catalog", "cad")
    assert settings.redirect_uri == PUBLIC + "/api/id/1/login/callback"
    assert settings.smtp is not None and settings.smtp.port == 465
    assert "hemligt" not in repr(settings) and SECRET not in repr(settings)
    with pytest.raises(ValueError, match="ID_API_SECRET"):
        from_env({"ID_API_DATABASE_URL": "x", "ID_API_ISSUER": ISSUER})


def test_the_one_a_fleet_is_shared_with_can_leave_it(world: World) -> None:
    kim = log_in(world, "Kim Ek", "kim@example.com")
    kim_id = kim.client.get(f"{API}/session").json()["account"]["id"]
    invitation = kim.client.post(
        f"{API}/fleets/{kim_id}/invitations", json={"email": "sara@example.com", "role": "viewer"}
    ).json()
    sara = log_in(world, "Sara Holm", "sara@example.com")
    sara.client.post(f"{API}/invitations/{invitation['id']}/answer", json={"accept": True})
    grant = kim.client.get(f"{API}/fleets/{kim_id}").json()["grants"][0]["id"]
    assert sara.client.delete(f"{API}/grants/{grant}").status_code == 200
    assert kim.client.get(f"{API}/fleets/{kim_id}").json()["grants"] == []


def test_a_clubs_fleet_follows_the_clubs_roles(world: World) -> None:
    """CAT-51, C36, C39: the admins have the owner's right, the members look, and the admin can
    give someone the right to edit. Leaving the club takes it away at once."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    club = kim.client.post(f"{API}/clubs", json={"name": "Västby MJK"}).json()["id"]
    invitation = kim.client.post(
        f"{API}/clubs/{club}/invitations", json={"email": "sara@example.com"}
    ).json()
    sara = log_in(world, "Sara Holm", "sara@example.com")
    sara.client.post(f"{API}/invitations/{invitation['id']}/answer", json={"accept": True})
    olle = log_in(world, "Olle Berg", "olle@example.com")
    ids = {
        who.name: who.client.get(f"{API}/session").json()["account"]["id"]
        for who in (kim, sara, olle)
    }
    resource = f"fleet:{club}"

    def roles(name: str) -> list[str]:
        roles_now: list[str] = apps(world, "access", person=ids[name], resource=resource).json()[
            "roles"
        ]
        return roles_now

    assert (roles("Kim Ek"), roles("Sara Holm"), roles("Olle Berg")) == (["admin"], ["viewer"], [])
    title = "Vagnparken · Västby MJK"
    assert apps(world, "fleets", person=ids["Kim Ek"]).json() == [
        {"owner": {"kind": "fleet", "id": club}, "title": title, "role": "owner"}
    ]
    assert apps(world, "fleets", person=ids["Sara Holm"]).json()[0]["role"] == "viewer"

    # The admin gives a member the right to edit, through the club fleet's sharing.
    shared = kim.client.post(
        f"{API}/fleets/{club}/invitations", json={"email": "sara@example.com", "role": "editor"}
    )
    assert shared.status_code == 201, shared.text
    assert shared.json()["title"] == title
    sara.client.post(f"{API}/invitations/{shared.json()['id']}/answer", json={"accept": True})
    assert roles("Sara Holm") == ["editor", "viewer"]
    assert apps(world, "fleets", person=ids["Sara Holm"]).json()[0]["role"] == "editor"
    # A member may not share the club's fleet.
    assert sara.client.get(f"{API}/fleets/{club}").status_code == 403

    # Out of the club: the club's right goes at once; the given right stays until taken.
    kim.client.delete(f"{API}/clubs/{club}/members/{ids['Sara Holm']}")
    assert roles("Sara Holm") == ["editor"]


def club_with(world: World, *people: tuple[str, str]) -> tuple[Who, str, dict[str, Who]]:
    """Kim's club, with the people as members who have said yes."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    club = kim.client.post(f"{API}/clubs", json={"name": "Västby MJK"}).json()["id"]
    joined: dict[str, Who] = {}
    for name, email in people:
        invitation = kim.client.post(f"{API}/clubs/{club}/invitations", json={"email": email})
        who = log_in(world, name, email)
        answer = f"{API}/invitations/{invitation.json()['id']}/answer"
        who.client.post(answer, json={"accept": True})
        who.id = who.client.get(f"{API}/session").json()["account"]["id"]
        joined[name] = who
    kim.id = kim.client.get(f"{API}/session").json()["account"]["id"]
    return kim, club, joined


AUTUMN = {"name": "Höstträffen", "starts_on": "2026-11-13", "ends_on": "2026-11-15"}


def test_a_meet_is_made_under_the_club_by_its_admin_who_arranges_it(world: World) -> None:
    """ID10: the meet is a reference with name, dates and club, made with Ny träff."""
    kim, club, people = club_with(world, ("Sara Holm", "sara@example.com"))
    sara = people["Sara Holm"]
    assert sara.client.post(f"{API}/clubs/{club}/meets", json=AUTUMN).status_code == 403
    made = kim.client.post(f"{API}/clubs/{club}/meets", json=AUTUMN)
    assert made.status_code == 201, made.text
    meet = made.json()
    assert (meet["name"], meet["club_name"], meet["roles"]) == (
        "Höstträffen",
        "Västby MJK",
        ["organizer"],
    )
    backwards = {**AUTUMN, "ends_on": "2026-11-12"}
    assert kim.client.post(f"{API}/clubs/{club}/meets", json=backwards).status_code == 422

    # The club's members see the club's meets, on the club and under Träffar.
    assert [m["name"] for m in sara.client.get(f"{API}/clubs/{club}").json()["meets"]] == [
        "Höstträffen"
    ]
    assert sara.client.get(f"{API}/meets").json()[0]["roles"] == []
    page = sara.client.get(f"{API}/meets/{meet['id']}").json()
    assert (page["may_give"], page["may_change"], page["may_remove"], page["members"]) == (
        [],
        False,
        False,
        [],
    )
    assert [(g["person"]["name"], g["role"]) for g in page["grants"]] == [("Kim Ek", "organizer")]

    # Clubs are kept apart (KONTO-17): someone outside sees nothing.
    olle = log_in(world, "Olle Berg", "olle@example.com")
    assert olle.client.get(f"{API}/meets/{meet['id']}").status_code == 404
    assert olle.client.get(f"{API}/meets").json() == []


def test_the_organizer_hands_out_dispatcher_and_loco_lead_and_the_admin_every_role(
    world: World,
) -> None:
    """KONTO-36: the club's admin hands out every role at the meet, the organizer Trafikledare
    and Lokledare. The roles go to the club's members, and what the apps ask follows."""
    kim, club, people = club_with(
        world, ("Sara Holm", "sara@example.com"), ("Jon Eriksson", "jon@example.com")
    )
    sara, jon = people["Sara Holm"], people["Jon Eriksson"]
    meet = kim.client.post(f"{API}/clubs/{club}/meets", json=AUTUMN).json()["id"]
    grants = f"{API}/meets/{meet}/grants"

    given = kim.client.post(grants, json={"person": sara.id, "role": "organizer"})
    assert given.status_code == 200, given.text
    page = sara.client.get(f"{API}/meets/{meet}").json()
    assert page["may_give"] == ["dispatcher", "loco_lead"]
    assert (page["may_change"], page["may_remove"]) == (True, False)
    assert {p["name"] for p in page["members"]} == {"Kim Ek", "Sara Holm", "Jon Eriksson"}

    assert sara.client.post(grants, json={"person": jon.id, "role": "loco_lead"}).status_code == 200
    refused = sara.client.post(grants, json={"person": jon.id, "role": "remote_clearer"})
    assert refused.status_code == 403
    assert jon.client.post(grants, json={"person": jon.id, "role": "dispatcher"}).status_code == 403
    olle = log_in(world, "Olle Berg", "olle@example.com")
    olle_id = olle.client.get(f"{API}/session").json()["account"]["id"]
    outside = kim.client.post(grants, json={"person": olle_id, "role": "dispatcher"})
    assert outside.status_code == 422  # not a member of the club

    resource = f"meet:{meet}"
    assert apps(world, "access", person=jon.id, resource=resource).json()["roles"] == ["loco_lead"]
    assert apps(world, "access", person=kim.id, resource=resource).json()["roles"] == [
        "admin",
        "organizer",
    ]
    assert apps(world, "access", person=olle_id, resource=resource).json()["roles"] == []

    # The organizer changes the meet; only the admin removes it.
    changed = sara.client.put(f"{API}/meets/{meet}", json={**AUTUMN, "name": "Höstträffen 2026"})
    assert changed.json()["meet"]["name"] == "Höstträffen 2026"
    assert jon.client.put(f"{API}/meets/{meet}", json=AUTUMN).status_code == 403
    assert sara.client.delete(f"{API}/meets/{meet}").status_code == 403

    # A role is taken back by whoever may hand it out, or dropped by its holder.
    roles_now = kim.client.get(f"{API}/meets/{meet}").json()["grants"]
    lead = next(g["id"] for g in roles_now if g["role"] == "loco_lead")
    organizer = next(g["id"] for g in roles_now if g["person"]["id"] == sara.id)
    assert jon.client.delete(f"{API}/grants/{organizer}").status_code == 403
    assert sara.client.delete(f"{API}/grants/{lead}").status_code == 200
    assert apps(world, "access", person=jon.id, resource=resource).json()["roles"] == []

    # Leaving the club takes the roles at its meets with it (KONTO-17).
    kim.client.delete(f"{API}/clubs/{club}/members/{sara.id}")
    assert apps(world, "access", person=sara.id, resource=resource).json()["roles"] == []
    assert sara.client.get(f"{API}/meets/{meet}").status_code == 404

    assert kim.client.delete(f"{API}/meets/{meet}").status_code == 200
    assert kim.client.get(f"{API}/clubs/{club}").json()["meets"] == []
    assert apps(world, "access", person=kim.id, resource=resource).json()["roles"] == []


def test_help_and_faults_go_to_support_with_the_app_page_and_version(world: World) -> None:
    """KONTO-06, ID9, ID12: a mail to the support address, which the person can be answered at.
    The person's text never goes in a header, and a few an hour is the most."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    report = {
        "kind": "fault",
        "text": "Kortet visar fel plats.\nSubject: injicerad",
        "app": "catalog",
        "page": "/fordon/1",
        "version": "0.1.0 · abc1234",
    }
    sent = kim.client.post(f"{API}/help", json=report)
    assert sent.status_code == 200, sent.text
    to, reply_to, subject, body = world.mail.help_sent[0]
    assert (to, reply_to) == ("support@example.test", "kim@example.com")
    assert subject == "[TrainMeet Catalog] Fel från Kim Ek"
    for line in ("Appen: TrainMeet Catalog", "Sidan: /fordon/1", "Versionen: 0.1.0 · abc1234"):
        assert line in body
    assert "Subject: injicerad" in body

    assert world.browser().post(f"{API}/help", json=report).status_code == 401
    assert kim.client.post(f"{API}/help", json={**report, "app": "okand"}).status_code == 422
    for _ in range(4):
        assert kim.client.post(f"{API}/help", json=report).status_code == 200
    too_many = kim.client.post(f"{API}/help", json=report)
    assert (too_many.status_code, too_many.json()["code"]) == (429, "too_many")


def test_without_a_support_address_help_says_it_cannot_send() -> None:
    from contracts.id import Account, HelpRequest
    from id.help import HelpDesk
    from id.roles import Refused

    desk = HelpDesk(PretendMail(), None)
    account = Account(id=uuid.uuid4(), name="Kim Ek", initials="KE", email="kim@example.com")
    request = HelpRequest(kind="help", text="Hur delar jag?", app="id")  # type: ignore[arg-type]
    with pytest.raises(Refused) as refused:
        desk.send(account, request)
    assert refused.value.status == 503


def test_the_app_switcher_shows_the_apps_the_person_has_something_in(world: World) -> None:
    """KONTO-38, ID11: Catalog and ID for everyone; the Hub with a meet or as a club's admin,
    Lokföraren as Lokledare."""
    kim, club, people = club_with(world, ("Jon Eriksson", "jon@example.com"))
    jon = people["Jon Eriksson"]
    session = jon.client.get(f"{API}/session").json()
    assert session["apps"] == ["catalog", "id"]
    assert kim.client.get(f"{API}/session").json()["apps"] == ["hub", "catalog", "id"]
    meet = kim.client.post(f"{API}/clubs/{club}/meets", json=AUTUMN).json()["id"]
    kim.client.post(f"{API}/meets/{meet}/grants", json={"person": jon.id, "role": "loco_lead"})
    assert apps(world, "switcher", person=jon.id).json() == {
        "apps": ["hub", "catalog", "driver", "id"]
    }
    assert world.browser().get(f"{API}/session").json()["apps"] == []
