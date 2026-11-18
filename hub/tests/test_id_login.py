"""Logga in med TrainMeet ID i Hubben (#78, KONTO-27, KONTO-10).

A pretend ID answers the hub's token exchange and signing keys, with tokens signed by a key made
for each test, as in Catalog's test. The whole login is also tried against a real Keycloak in the
check "ID:s bild" (id/prov_inloggning.py --hub).
"""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from contracts import hub as contract
from hub import id_login
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.hubben import COOKIE

ISSUER = "https://id.example.test/realms/trainmeet"
INTERNAL = "http://id:8080/realms/trainmeet"
PUBLIC = "https://hub.example.test"
SECRET = "klienthemlighet-for-provet"
PIN = "482915"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class PretendId:
    """Just enough of TrainMeet ID: the signing keys and the token endpoint."""

    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = "nyckel-1"
    claims: dict[str, Any] = field(default_factory=dict)
    exchanges: list[dict[str, Any]] = field(default_factory=list)
    nonce: str = ""
    subject: str = field(default_factory=lambda: str(uuid.uuid4()))

    def jwks(self) -> dict[str, Any]:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def token(self) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "hub",
            "azp": "hub",
            "sub": self.subject,
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "email": "prov@example.com",
            "email_verified": True,
            "name": "Provare  Ett ",
            **self.claims,
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/realms/trainmeet/protocol/openid-connect/certs":
            return httpx.Response(200, json=self.jwks())
        if request.url.path == "/realms/trainmeet/protocol/openid-connect/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.exchanges.append({"form": form, "auth": request.headers.get("authorization")})
            return httpx.Response(200, json={"id_token": self.token()})
        return httpx.Response(404)


SETTINGS = id_login.IdSettings(
    issuer=ISSUER, secret=SECRET, public_url=PUBLIC, internal=INTERNAL, client="hub"
)


@pytest.fixture
def pretend() -> PretendId:
    return PretendId()


@pytest.fixture
def hub(tmp_path: Path, pretend: PretendId) -> TestClient:
    made = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    client = TestClient(made, base_url=PUBLIC, follow_redirects=False)
    assert client.post("/api/hub/setup", json={"name": "Molnet", "pin": PIN}).status_code == 201
    client.cookies.clear()
    return client


def to_id(hub: TestClient, pretend: PretendId, next_path: str = "/drift") -> dict[str, str]:
    """Logga in med ID: the hub sends the browser to ID, which the pretend ID answers."""
    started = hub.get("/api/hub/id/login", params={"next": next_path, "lang": "sv"})
    assert started.status_code == 303
    address = urlparse(started.headers["location"])
    assert f"{address.scheme}://{address.netloc}{address.path}" == (
        ISSUER + "/protocol/openid-connect/auth"
    )
    query = {k: v[0] for k, v in parse_qs(address.query).items()}
    pretend.nonce = query["nonce"]
    return query


def back(hub: TestClient, query: dict[str, str], code: str = "kod-1") -> httpx.Response:
    answer: httpx.Response = hub.get(
        "/api/hub/id/callback", params={"code": code, "state": query["state"]}
    )
    return answer


def info(hub: TestClient) -> contract.HubInfo:
    return contract.HubInfo.model_validate(hub.get("/api/hub").json())


def test_the_hub_logs_in_with_id_with_pkce_and_keeps_only_the_name(
    hub: TestClient, pretend: PretendId, tmp_path: Path
) -> None:
    assert info(hub).id_login is True and info(hub).logged_in is False
    query = to_id(hub, pretend)
    assert query["client_id"] == "hub"
    assert query["redirect_uri"] == PUBLIC + "/api/hub/id/callback"
    assert query["code_challenge_method"] == "S256" and query["ui_locales"] == "sv"
    done = back(hub, query)
    assert done.status_code == 303 and done.headers["location"] == "/drift"
    # The code went to ID's own address, with the verifier the challenge was made from.
    form = pretend.exchanges[0]["form"]
    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == query["code_challenge"]
    assert pretend.exchanges[0]["auth"].startswith("Basic ")
    seen = info(hub)
    assert (seen.logged_in, seen.admin, seen.meet_role) == (True, False, None)
    assert seen.person == "Provare Ett"
    # Logged in with ID is not the hub's own administrator (H18).
    assert hub.post("/api/hub/name", json={"name": "Min"}).status_code == 401
    assert hub.post("/api/drift/1/start", json={"version": 1}).status_code == 401
    # Nothing about the address is kept.
    assert b"prov@example.com" not in (tmp_path / "hubben.sqlite3").read_bytes()


def test_logging_out_logs_out_of_id_too(hub: TestClient, pretend: PretendId) -> None:
    back(hub, to_id(hub, pretend))
    answer = hub.post("/api/hub/logout")
    assert answer.status_code == 200
    address = urlparse(contract.LoggedOut.model_validate(answer.json()).logout_url or "")
    assert address.path == "/realms/trainmeet/protocol/openid-connect/logout"
    query = {k: v[0] for k, v in parse_qs(address.query).items()}
    assert query["post_logout_redirect_uri"] == PUBLIC + "/" and query["client_id"] == "hub"
    assert info(hub).logged_in is False
    # The PIN's login has no ID to log out of.
    assert hub.post("/api/hub/login", json={"pin": PIN}).status_code == 200
    assert hub.post("/api/hub/logout").json() == {"logout_url": None}


@pytest.mark.parametrize(
    ("claims", "why"),
    [
        ({"email_verified": False}, "E-posten är inte verifierad i ID."),
        ({"aud": "catalog", "azp": "catalog"}, "ID:s token godtas inte: InvalidAudienceError."),
        ({"iss": "https://annan.example.test/realms/x"}, "ID:s token godtas inte"),
        ({"sub": "inte-ett-id"}, "ID:s token har inget giltigt sub."),
    ],
)
def test_a_token_the_hub_cannot_trust_logs_no_one_in(
    hub: TestClient, pretend: PretendId, claims: dict[str, Any], why: str, caplog: Any
) -> None:
    pretend.claims = claims
    done = back(hub, to_id(hub, pretend))
    assert done.headers["location"] == "/?inloggning=fel&next=%2Fdrift"
    assert info(hub).logged_in is False
    assert why in caplog.text


def test_the_login_is_this_browsers_once_and_with_its_own_state(
    hub: TestClient, pretend: PretendId
) -> None:
    query = to_id(hub, pretend)
    wrong = hub.get("/api/hub/id/callback", params={"code": "k", "state": "fel"})
    assert wrong.headers["location"] == "/?inloggning=fel&next=%2Fdrift"
    # The attempt was used up by the wrong answer: the right state is too late.
    assert back(hub, query).headers["location"] == "/?inloggning=fel"
    other = TestClient(hub.app, base_url=PUBLIC, follow_redirects=False)
    query = to_id(hub, pretend)
    assert back(other, query).headers["location"] == "/?inloggning=fel"
    assert info(other).logged_in is False


@pytest.mark.parametrize(
    "asked", ["https://annan.example.test/", "//annan.example.test", "/api/hub", "/a\\b", ""]
)
def test_the_way_back_is_one_of_the_hubs_own_pages(asked: str) -> None:
    assert id_login.safe_next(asked) == "/"
    assert id_login.safe_next("/planering/varnamo") == "/planering/varnamo"


def test_without_settings_there_is_no_login_with_id(tmp_path: Path) -> None:
    plain = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    assert plain.get("/api/hub").json()["id_login"] is False
    assert plain.get("/api/hub/id/login").status_code == 404
    env = {"TRAINMEET_ID_ISSUER": ISSUER}
    assert id_login.settings_from(env) is None, "half a setting starts no login"
    env |= {"TRAINMEET_ID_SECRET": SECRET, "TRAINMEET_PUBLIC_URL": PUBLIC + "/"}
    found = id_login.settings_from(env)
    assert found is not None
    assert (found.internal, found.client, found.redirect_uri) == (
        ISSUER,
        "hub",
        PUBLIC + "/api/hub/id/callback",
    )
    assert SECRET not in repr(found)


def test_the_session_cookie_is_the_hubs_own(hub: TestClient, pretend: PretendId) -> None:
    done = back(hub, to_id(hub, pretend))
    cookies = done.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(COOKIE + "="))
    assert "HttpOnly" in session and "SameSite=strict" in session and "Secure" in session
    assert any(c.startswith(id_login.COOKIE + '=""') for c in cookies), "the attempt is gone"
