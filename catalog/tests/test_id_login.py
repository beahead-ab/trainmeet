"""Logging in to Catalog with TrainMeet ID (#66, KONTO-27, KONTO-10, CAT-42).

A pretend ID answers Catalog's token exchange and signing keys, with tokens signed by a key
made for each test. The whole login is also tried against a real Keycloak in the check
"ID:s bild" (id/prov_inloggning.py), from ID's side.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from catalog.app import create_app
from catalog.id_login import COOKIE as ATTEMPT_COOKIE
from catalog.id_login import account_from, safe_next
from catalog.login import COOKIE
from catalog.settings import IdSettings, Settings, from_env
from contracts.catalog import CatalogVersion, LoginKind

API = "/api/catalog/1"
ISSUER = "https://id.example.test/realms/trainmeet"
INTERNAL = "http://id:8080/realms/trainmeet"
PUBLIC = "https://catalog.example.test"
SECRET = "klienthemlighet-for-provet"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class PretendId:
    """Just enough of TrainMeet ID: the signing keys and the token endpoint."""

    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = "nyckel-1"
    claims: dict[str, Any] = field(default_factory=dict)
    sign_with: rsa.RSAPrivateKey | None = None
    token_status: int = 200
    certs_read: int = 0
    exchanges: list[dict[str, Any]] = field(default_factory=list)
    issued: list[str] = field(default_factory=list)
    nonce: str = ""

    def jwks(self) -> dict[str, Any]:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def token(self, subject: str) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "catalog",
            "azp": "catalog",
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "email": "prov@example.com",
            "email_verified": True,
            "name": "Provare Ett",
            **self.claims,
        }
        signed = jwt.encode(
            claims, self.sign_with or self.key, algorithm="RS256", headers={"kid": self.kid}
        )
        self.issued.append(signed)
        return signed

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/realms/trainmeet/protocol/openid-connect/certs":
            self.certs_read += 1
            return httpx.Response(200, json=self.jwks())
        if request.url.path == "/realms/trainmeet/protocol/openid-connect/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.exchanges.append({"form": form, "auth": request.headers.get("authorization")})
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.token(form["code"])})
        return httpx.Response(404)


@pytest.fixture
def pretend_id() -> PretendId:
    return PretendId()


def id_settings() -> IdSettings:
    return IdSettings(
        issuer=ISSUER, client="catalog", secret=SECRET, public_url=PUBLIC, internal=INTERNAL
    )


def settings_for(url: str, web_dir: Path) -> Settings:
    return Settings(
        database_url=url,
        migrate="auto",
        web_dir=web_dir,
        id=id_settings(),
        build=CatalogVersion(version="0.1.0"),
    )


@pytest.fixture
def client(database_url: str, tmp_path: Path, pretend_id: PretendId) -> Iterator[TestClient]:
    (tmp_path / "index.html").write_text("<!doctype html><title>TrainMeet Catalog</title>")
    http = httpx.Client(transport=httpx.MockTransport(pretend_id.handle))
    app = create_app(settings_for(database_url, tmp_path), id_http=http)
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as test_client:
        yield test_client


def to_id(client: TestClient, next_path: str = "/fordon") -> dict[str, str]:
    answer = client.get(f"{API}/id/login", params={"next": next_path, "lang": "en"})
    assert answer.status_code == 303
    target = urlparse(answer.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == (
        ISSUER + "/protocol/openid-connect/auth"
    )
    return {k: v[0] for k, v in parse_qs(target.query).items()}


def back_from_id(
    client: TestClient, pretend_id: PretendId, query: dict[str, str], subject: str
) -> httpx.Response:
    pretend_id.nonce = query["nonce"]
    answer: httpx.Response = client.get(
        f"{API}/id/callback", params={"code": subject, "state": query["state"]}
    )
    return answer


def test_the_login_goes_to_id_with_pkce_and_comes_back_logged_in(
    client: TestClient, pretend_id: PretendId
) -> None:
    assert client.get(f"{API}/session").json()["login"] == LoginKind.ID
    query = to_id(client, "/fordon/nytt")
    assert query["client_id"] == "catalog"
    assert query["redirect_uri"] == PUBLIC + "/api/catalog/1/id/callback"
    assert query["response_type"] == "code"
    assert set(query["scope"].split()) == {"openid", "profile", "email"}
    assert query["code_challenge_method"] == "S256"
    assert query["ui_locales"] == "en"
    assert len(query["state"]) >= 20 and len(query["nonce"]) >= 20

    subject = str(uuid.uuid4())
    answer = back_from_id(client, pretend_id, query, subject)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/fordon/nytt"
    assert COOKIE in answer.cookies

    # Catalog proved it started the login: the verifier matches the challenge, with its secret.
    exchange = pretend_id.exchanges[0]
    verifier = exchange["form"]["code_verifier"]
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert digest.decode() == query["code_challenge"]
    assert exchange["form"]["redirect_uri"] == PUBLIC + "/api/catalog/1/id/callback"
    expected = base64.b64encode(f"catalog:{SECRET}".encode()).decode()
    assert exchange["auth"] == f"Basic {expected}"

    # The account is made the first time (CAT-42), with ID's subject as its id.
    session = client.get(f"{API}/session").json()
    assert session["account"] == {"id": subject, "name": "Provare Ett", "initials": "PE"}
    assert client.get(f"{API}/vehicles").status_code == 200


def test_the_same_person_comes_back_to_the_same_account_with_a_new_name(
    client: TestClient, pretend_id: PretendId
) -> None:
    subject = str(uuid.uuid4())
    back_from_id(client, pretend_id, to_id(client), subject)
    made = client.post(f"{API}/vehicles", json={"note": "en vagn i lådan"})
    assert made.status_code == 201, made.text
    client.delete(f"{API}/session")

    pretend_id.claims = {"name": "Provare Ettan"}
    back_from_id(client, pretend_id, to_id(client), subject)
    session = client.get(f"{API}/session").json()
    assert session["account"]["name"] == "Provare Ettan"
    assert len(client.get(f"{API}/vehicles").json()["vehicles"]) == 1


def test_logging_out_sends_the_browser_to_id_to_log_out_there_too(
    client: TestClient, pretend_id: PretendId
) -> None:
    back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4()))
    out = client.delete(f"{API}/session").json()
    assert out["account"] is None
    target = urlparse(out["logout_url"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == (
        ISSUER + "/protocol/openid-connect/logout"
    )
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert query["id_token_hint"] == pretend_id.issued[-1]
    assert query["post_logout_redirect_uri"] == PUBLIC + "/"
    assert query["client_id"] == "catalog"
    assert client.get(f"{API}/session").json()["account"] is None
    # Logging out again has nothing more to say, and the token is gone with the session.
    assert client.delete(f"{API}/session").json()["logout_url"] is None


def failed(answer: httpx.Response, next_path: str = "/fordon") -> bool:
    location = answer.headers.get("location", "")
    query = parse_qs(urlparse(location).query)
    return (
        answer.status_code == 303
        and location.startswith("/logga-in?")
        and query.get("inloggning") == ["fel"]
        and query.get("next", ["/"]) == [next_path]
        and COOKIE not in answer.cookies
    )


@pytest.mark.parametrize(
    ("claims", "why"),
    [
        ({"aud": "en-annan-app"}, "audience"),
        ({"iss": "https://id.example.test/realms/en-annan"}, "issuer"),
        ({"nonce": "fel"}, "nonce"),
        ({"email_verified": False}, "verified e-mail, KONTO-10"),
        ({"exp": int(time.time()) - 3600}, "expired"),
        ({"azp": "en-annan-app"}, "authorized party"),
        ({"sub": "inte-ett-uuid"}, "subject"),
    ],
)
def test_a_token_catalog_cannot_trust_logs_no_one_in(
    client: TestClient, pretend_id: PretendId, claims: dict[str, Any], why: str
) -> None:
    query = to_id(client)
    pretend_id.nonce = query["nonce"]
    pretend_id.claims = claims
    answer = client.get(
        f"{API}/id/callback", params={"code": str(uuid.uuid4()), "state": query["state"]}
    )
    assert failed(answer), why
    assert client.get(f"{API}/session").json()["account"] is None


def test_a_token_signed_with_another_key_logs_no_one_in(
    client: TestClient, pretend_id: PretendId
) -> None:
    pretend_id.sign_with = new_key()
    assert failed(back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4())))


def test_a_new_signing_key_is_read_from_id_but_not_on_every_login(
    client: TestClient, pretend_id: PretendId
) -> None:
    back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4()))
    assert pretend_id.certs_read == 1
    back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4()))
    assert pretend_id.certs_read == 1
    # A key Catalog has not seen is read from ID again, but at most once a minute.
    pretend_id.kid = "nyckel-2"
    assert failed(back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4())))
    assert pretend_id.certs_read == 1


def test_the_keys_are_read_the_first_time_even_just_after_the_machine_started(
    client: TestClient, pretend_id: PretendId, monkeypatch: pytest.MonkeyPatch
) -> None:
    # time.monotonic() counts from when the machine started, so it can be small (it was on
    # GitHub's fresh machines, 15 November).
    monkeypatch.setattr("catalog.id_login.time.monotonic", lambda: 5.0)
    answer = back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4()))
    assert answer.headers["location"] == "/fordon"
    assert pretend_id.certs_read == 1


def test_the_wrong_state_or_another_browser_logs_no_one_in(
    client: TestClient, pretend_id: PretendId
) -> None:
    query = to_id(client)
    pretend_id.nonce = query["nonce"]
    wrong = client.get(f"{API}/id/callback", params={"code": "x", "state": "fel"})
    assert failed(wrong)
    # The attempt is used up, so the right state does not help afterwards.
    again = client.get(f"{API}/id/callback", params={"code": "x", "state": query["state"]})
    assert failed(again, "/")
    # Another browser, without the cookie, cannot finish someone's login.
    query = to_id(client)
    client.cookies.delete(ATTEMPT_COOKIE, path="/api/catalog/1/id")
    stolen = back_from_id(client, pretend_id, query, str(uuid.uuid4()))
    assert failed(stolen, "/")
    assert pretend_id.exchanges == []


def test_an_attempt_works_once(client: TestClient, pretend_id: PretendId) -> None:
    query = to_id(client)
    attempt = client.cookies.get(ATTEMPT_COOKIE)
    assert attempt
    first = back_from_id(client, pretend_id, query, str(uuid.uuid4()))
    assert first.status_code == 303 and COOKIE in first.cookies
    assert first.headers["location"] == "/fordon"
    client.cookies.clear()
    client.cookies.set(ATTEMPT_COOKIE, attempt, path="/api/catalog/1/id")
    assert failed(back_from_id(client, pretend_id, query, str(uuid.uuid4())), "/")


def test_id_saying_no_or_failing_sends_the_browser_back_to_log_in(
    client: TestClient, pretend_id: PretendId, caplog: pytest.LogCaptureFixture
) -> None:
    query = to_id(client)
    refused = client.get(
        f"{API}/id/callback", params={"error": "access_denied", "state": query["state"]}
    )
    assert failed(refused)

    pretend_id.token_status = 400
    with caplog.at_level(logging.WARNING, logger="catalog"):
        answer = back_from_id(client, pretend_id, to_id(client), "hemlig-kod-123")
    assert failed(answer)
    assert "400" in caplog.text
    assert "hemlig-kod-123" not in caplog.text and SECRET not in caplog.text


def test_nothing_from_id_is_written_to_the_log(
    client: TestClient, pretend_id: PretendId, caplog: pytest.LogCaptureFixture
) -> None:
    pretend_id.claims = {"email_verified": False}
    with caplog.at_level(logging.DEBUG):
        back_from_id(client, pretend_id, to_id(client), str(uuid.uuid4()))
    assert "verifierad" in caplog.text
    for token in pretend_id.issued:
        assert token not in caplog.text
    assert "prov@example.com" not in caplog.text


@pytest.mark.parametrize(
    ("asked", "safe"),
    [
        ("/fordon/nytt", "/fordon/nytt"),
        ("/t/04A1B2C3D4E5F6?x=1", "/t/04A1B2C3D4E5F6?x=1"),
        ("//elak.example", "/"),
        ("https://elak.example/", "/"),
        ("/\\elak.example", "/"),
        ("/api/catalog/1/session", "/"),
        ("/fordon\r\nSet-Cookie: x", "/"),
        ("", "/"),
        (None, "/"),
        ("/" + "a" * 600, "/"),
    ],
)
def test_the_page_to_come_back_to_is_always_catalogs_own(asked: str | None, safe: str) -> None:
    assert safe_next(asked) == safe


def test_the_name_comes_from_id_or_says_there_is_none() -> None:
    subject = str(uuid.uuid4())
    assert account_from({"sub": subject, "name": "  Kim   Berg "}).name == "Kim Berg"
    assert account_from({"sub": subject, "given_name": "Kim"}).name == "Kim"
    nameless = account_from({"sub": subject})
    assert (nameless.name, nameless.initials) == ("Utan namn", "UN")
    assert len(account_from({"sub": subject, "name": "x" * 200}).name) == 80


def test_without_id_there_is_no_login_with_id(database_url: str, tmp_path: Path) -> None:
    plain = Settings(database_url=database_url, migrate="auto", web_dir=tmp_path)
    with TestClient(create_app(plain)) as client:
        assert client.get(f"{API}/id/login", follow_redirects=False).status_code == 404
        assert client.get(f"{API}/id/callback", follow_redirects=False).status_code == 404


def test_the_id_settings_come_from_the_environment() -> None:
    base = {"CATALOG_DATABASE_URL": "postgresql://db/catalog"}
    assert from_env(base).id is None
    settings = from_env(
        {
            **base,
            "CATALOG_ID_ISSUER": ISSUER + "/",
            "CATALOG_ID_INTERNAL": INTERNAL,
            "CATALOG_ID_SECRET": SECRET,
            "CATALOG_PUBLIC_URL": PUBLIC,
        }
    )
    assert settings.id == id_settings()
    assert settings.id.redirect_uri == PUBLIC + "/api/catalog/1/id/callback"
    assert SECRET not in repr(settings) and SECRET not in repr(settings.id)
    local = from_env(
        {
            **base,
            "CATALOG_ID_ISSUER": "http://localhost:8180/realms/trainmeet",
            "CATALOG_ID_SECRET": SECRET,
            "CATALOG_PUBLIC_URL": "http://127.0.0.1:8001",
        }
    )
    assert local.id is not None and local.id.internal == local.id.issuer


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"CATALOG_ID_ISSUER": ISSUER, "CATALOG_PUBLIC_URL": PUBLIC}, "CATALOG_ID_SECRET"),
        ({"CATALOG_ID_ISSUER": ISSUER, "CATALOG_ID_SECRET": SECRET}, "CATALOG_PUBLIC_URL"),
        (
            {
                "CATALOG_ID_ISSUER": "http://id.example.test/realms/trainmeet",
                "CATALOG_ID_SECRET": SECRET,
                "CATALOG_PUBLIC_URL": PUBLIC,
            },
            "CATALOG_ID_ISSUER",
        ),
    ],
)
def test_wrong_id_settings_stop_the_start(extra: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message) as raised:
        from_env({"CATALOG_DATABASE_URL": "postgresql://db/catalog", **extra})
    assert SECRET not in str(raised.value)
