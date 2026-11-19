"""CAD's web program: the health check, the version, the session and the logins, the web app's
pages, and what CAD says when it says no."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from cad.app import CONTENT_SECURITY_POLICY, create_app
from cad.id_login import COOKIE as ATTEMPT_COOKIE
from cad.id_login import account_from, safe_next
from cad.login import COOKIE
from cad.settings import Settings, SettingsError, from_env
from cad.tests.conftest import (
    API,
    CLUB,
    ISSUER,
    PUBLIC,
    SECRET,
    A,
    PretendId,
    World,
    settings_for,
    straight,
)
from contracts.cad import CadVersion, LoginKind


def test_health_version_and_the_web_apps_pages(world: World) -> None:
    client = world.browser()
    assert client.get("/healthz").text == "ok"
    version = client.get("/api/version").json()
    assert version["product"] == "TrainMeet CAD" and version["commit"] == "abcdef1234"
    page = client.get("/moduler/ny")
    assert page.status_code == 200 and "<title>TrainMeet CAD</title>" in page.text
    assert page.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert client.get("/finns-inte.js").status_code == 404
    assert client.get(f"{API}/finns-inte").status_code == 404


def test_without_a_session_the_library_asks_for_a_login(world: World) -> None:
    client = world.browser()
    session = client.get(f"{API}/session").json()
    assert session["account"] is None and session["login"] == "trial"
    refused = client.get(f"{API}/modules")
    assert refused.status_code == 401 and refused.json()["code"] == "login"
    assert refused.headers["cache-control"] == "private, no-store"
    assert client.post(f"{API}/modules", json=straight()).status_code == 401


def test_the_trial_login_and_the_session_with_clubs_apps_and_tokens(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "admin")
    accounts = world.browser().get(f"{API}/trial/accounts").json()
    assert [a["name"] for a in accounts] == [f"Provkonto {x}" for x in "ABCD"]
    client = world.as_(A.id)
    session = client.get(f"{API}/session").json()
    assert session["account"]["name"] == "Provkonto A"
    assert session["clubs"] == [{"id": str(CLUB), "name": "Västby MJK", "admin": True}]
    assert session["apps"] == ["cad", "catalog", "id"]
    assert session["tokens"] == 86
    assert session["tokens_url"] == "https://id.example.test/tokens"
    assert session["help_url"] == "https://id.example.test/hjalp"
    out = client.delete(f"{API}/session").json()
    assert out["account"] is None
    assert client.get(f"{API}/session").json()["account"] is None


def test_the_trial_login_is_off_unless_it_is_turned_on(
    database_url: str, tmp_path: Path, pretend_id: PretendId
) -> None:
    http = httpx.Client(transport=httpx.MockTransport(pretend_id.handle))
    app = create_app(settings_for(database_url, tmp_path, trial=False), id_http=http)
    with TestClient(app, base_url=PUBLIC) as client:
        assert client.get(f"{API}/session").json()["login"] == LoginKind.ID
        assert client.get(f"{API}/trial/accounts").status_code == 404
        assert client.post(f"{API}/trial/login", json={"account": str(A.id)}).status_code == 404


def test_the_login_with_id_is_the_code_flow_with_pkce_and_the_clients_secret(
    database_url: str, tmp_path: Path, pretend_id: PretendId
) -> None:
    http = httpx.Client(transport=httpx.MockTransport(pretend_id.handle))
    app = create_app(settings_for(database_url, tmp_path, trial=False), id_http=http)
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as client:
        to_id = client.get(f"{API}/id/login", params={"next": "/moduler/ny", "lang": "sv"})
        assert to_id.status_code == 303
        target = urlparse(to_id.headers["location"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == (
            ISSUER + "/protocol/openid-connect/auth"
        )
        query = {k: v[0] for k, v in parse_qs(target.query).items()}
        assert query["client_id"] == "cad" and query["code_challenge_method"] == "S256"
        assert query["redirect_uri"] == PUBLIC + "/api/cad/1/id/callback"
        assert ATTEMPT_COOKIE in client.cookies
        pretend_id.nonce = query["nonce"]
        subject = "7b2c3d4e-5f60-4718-8293-a4b5c6d7e8f9"
        back = client.get(f"{API}/id/callback", params={"code": subject, "state": query["state"]})
        assert back.status_code == 303 and back.headers["location"] == "/moduler/ny"
        assert COOKIE in client.cookies
        session = client.get(f"{API}/session").json()
        assert session["account"] == {"id": subject, "name": "Provare Ett", "initials": "PE"}
        out = client.delete(f"{API}/session").json()
        assert out["logout_url"].startswith(ISSUER + "/protocol/openid-connect/logout?")
        # The same state twice is refused: the attempt is used once.
        again = client.get(f"{API}/id/callback", params={"code": subject, "state": query["state"]})
        assert again.headers["location"].startswith("/logga-in?inloggning=fel")


def test_the_login_comes_back_only_to_cads_own_pages() -> None:
    assert safe_next("/moduler") == "/moduler"
    for elsewhere in ("//elak.example", "https://elak.example", "/api/cad/1/session", "x", None):
        assert safe_next(elsewhere) == "/"
    named = account_from({"sub": "7b2c3d4e-5f60-4718-8293-a4b5c6d7e8f9", "given_name": "Kim"})
    assert named.name == "Kim" and named.initials == "K"


def test_the_settings_name_what_is_missing_never_the_value() -> None:
    with pytest.raises(SettingsError, match="CAD_DATABASE_URL"):
        from_env({})
    with pytest.raises(SettingsError, match="CAD_ID_SECRET"):
        from_env({"CAD_DATABASE_URL": "postgresql:///cad", "CAD_ID_ISSUER": ISSUER})
    with pytest.raises(SettingsError, match="https"):
        from_env({"CAD_DATABASE_URL": "postgresql:///cad", "CAD_ID_ISSUER": "http://id.example"})
    made = from_env(
        {
            "CAD_DATABASE_URL": "postgresql://cad:hemligt@cad-db/cad",
            "CAD_ID_ISSUER": ISSUER,
            "CAD_ID_SECRET": SECRET,
            "CAD_PUBLIC_URL": PUBLIC,
            "CAD_ID_INTERNAL": "http://id:8080/realms/trainmeet",
            "CAD_ID_API": "http://id-api:8080",
            "CAD_TRIAL_LOGIN": "on",
            "TRAINMEET_COMMIT": "ABCDEF1234",
            "TRAINMEET_PR": "301",
        }
    )
    assert isinstance(made, Settings) and made.trial_login and made.id is not None
    assert made.id.client == "cad" and made.id.api == "http://id-api:8080"
    assert made.build == CadVersion(version=made.build.version, commit="abcdef1234", pr=301)
    assert "hemligt" not in repr(made) and SECRET not in repr(made)
