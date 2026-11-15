"""An empty Catalog: its version, the trial login and the web app's pages (#48)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from catalog import migrate
from catalog.app import CONTENT_SECURITY_POLICY, create_app
from catalog.login import COOKIE, TRIAL_ACCOUNTS
from catalog.settings import Settings, from_env
from contracts.catalog import CatalogVersion, LoginKind, Session

API = "/api/catalog/1"


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>TrainMeet Catalog</title>")
    (web / "assets" / "index-abc123.js").write_text("console.log('catalog')")
    (web / "manifest.webmanifest").write_text('{"name": "TrainMeet Catalog"}')
    return web


def settings_for(url: str, web_dir: Path, *, trial: bool = True) -> Settings:
    return Settings(
        database_url=url,
        migrate="auto",
        trial_login=trial,
        web_dir=web_dir,
        build=CatalogVersion(version="0.1.0", commit="abc1234", pr=101, title="Grunden"),
    )


@pytest.fixture
def client(database_url: str, web_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(settings_for(database_url, web_dir))) as test_client:
        yield test_client


def test_an_empty_catalog_shows_its_version(client: TestClient) -> None:
    answer = client.get("/api/version")
    assert answer.status_code == 200
    version = CatalogVersion.model_validate(answer.json())
    assert version.product == "TrainMeet Catalog"
    assert (version.version, version.commit, version.pr) == ("0.1.0", "abc1234", 101)
    assert client.get("/healthz").text == "ok"


def test_nobody_is_logged_in_at_first(client: TestClient) -> None:
    session = Session.model_validate(client.get(API + "/session").json())
    assert session.account is None
    assert session.login is LoginKind.TRIAL


def test_the_trial_login_has_fixed_accounts_and_logs_in_and_out(client: TestClient) -> None:
    accounts = client.get(API + "/trial/accounts").json()
    assert [a["name"] for a in accounts] == [f"Provkonto {c}" for c in "ABCD"]
    chosen = TRIAL_ACCOUNTS[1]

    answer = client.post(API + "/trial/login", json={"account": str(chosen.id)})
    assert answer.status_code == 200
    cookie = answer.headers["set-cookie"]
    assert cookie.startswith(COOKIE + "=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    session = Session.model_validate(client.get(API + "/session").json())
    assert session.account == chosen

    assert client.delete(API + "/session").json()["account"] is None
    assert client.get(API + "/session").json()["account"] is None


def test_the_same_account_comes_back_to_the_same_owner(client: TestClient) -> None:
    account = TRIAL_ACCOUNTS[0]
    for _ in range(2):
        client.post(API + "/trial/login", json={"account": str(account.id)})
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.transaction() as conn:
        rows = conn.execute("SELECT id, name FROM owner").fetchall()
    assert rows == [{"id": account.id, "name": "Provkonto A"}]


def test_only_the_trial_accounts_can_log_in(client: TestClient) -> None:
    answer = client.post(API + "/trial/login", json={"account": str(TRIAL_ACCOUNTS[0].id)[:-1]})
    assert answer.status_code == 422
    other = "00000000-0000-4000-8000-000000000000"
    assert client.post(API + "/trial/login", json={"account": other}).status_code == 422


def test_the_login_needs_a_json_body(client: TestClient) -> None:
    answer = client.post(
        API + "/trial/login",
        content=f"account={TRIAL_ACCOUNTS[0].id}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert answer.status_code == 422
    assert COOKIE not in answer.headers.get("set-cookie", "")


def test_a_made_up_session_key_logs_no_one_in(client: TestClient) -> None:
    client.cookies.set(COOKIE, "pahittad")
    assert client.get(API + "/session").json()["account"] is None
    client.cookies.set(COOKIE, "x" * 500)
    assert client.get(API + "/session").json()["account"] is None


def test_without_the_trial_login_there_is_no_way_in(database_url: str, web_dir: Path) -> None:
    app = create_app(settings_for(database_url, web_dir, trial=False))
    with TestClient(app) as client:
        assert client.get(API + "/session").json() == {
            "account": None,
            "login": "id",
            "simulated_tags": False,
            "share_url": None,
            "help_url": None,
            "apps": None,
            "logout_url": None,
        }
        assert client.get(API + "/trial/accounts").status_code == 404
        answer = client.post(API + "/trial/login", json={"account": str(TRIAL_ACCOUNTS[0].id)})
        assert answer.status_code == 404


def test_every_page_address_gets_the_web_app(client: TestClient) -> None:
    for path in ("/", "/fordon", "/traffar", "/forebilder", "/blippa", "/logga-in"):
        answer = client.get(path)
        assert answer.status_code == 200, path
        assert "TrainMeet Catalog" in answer.text
        assert answer.headers["cache-control"] == "no-cache"
    asset = client.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.head("/fordon").status_code == 200


def test_files_outside_the_web_app_are_never_served(client: TestClient) -> None:
    assert client.get("/assets/saknas.js").status_code == 404
    assert client.get("/..%2F..%2Fetc%2Fpasswd").status_code in (200, 404)
    assert "root:" not in client.get("/..%2F..%2Fetc%2Fpasswd").text
    assert client.get("/api/catalog/1/saknas").status_code == 404


def test_answers_carry_the_security_headers(client: TestClient) -> None:
    page = client.get("/fordon")
    assert page.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert page.headers["x-frame-options"] == "DENY"
    api = client.get(API + "/session")
    assert api.headers["cache-control"] == "private, no-store"


def test_a_missing_web_app_says_so(database_url: str, tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(database_url, tmp_path / "saknas"))) as client:
        assert "Webbappen är inte byggd" in client.get("/fordon").text


def test_check_mode_refuses_a_database_that_is_behind(database_url: str, web_dir: Path) -> None:
    settings = settings_for(database_url, web_dir)
    checking = Settings(**{**settings.__dict__, "migrate": "check"})
    with (
        pytest.raises(migrate.MigrationError, match="saknar migrationer"),
        TestClient(create_app(checking)),
    ):
        pass
    migrate.migrate(database_url)
    with TestClient(create_app(checking)) as client:
        assert client.get("/healthz").text == "ok"


def test_the_settings_come_from_the_environment() -> None:
    settings = from_env(
        {
            "CATALOG_DATABASE_URL": "postgresql://catalog:hemligt@db/catalog",
            "CATALOG_TRIAL_LOGIN": "on",
            "TRAINMEET_COMMIT": "ABCDEF1",
            "TRAINMEET_PR": "48",
            "TRAINMEET_BUILT": "2026-11-15T12:00:00Z",
        }
    )
    assert settings.trial_login is True
    assert settings.migrate == "check"
    assert (settings.build.commit, settings.build.pr) == ("abcdef1", 48)
    assert "hemligt" not in repr(settings)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "CATALOG_DATABASE_URL saknas"),
        ({"CATALOG_DATABASE_URL": "x", "CATALOG_MIGRATE": "ibland"}, "CATALOG_MIGRATE"),
        ({"CATALOG_DATABASE_URL": "x", "CATALOG_TRIAL_LOGIN": "ja"}, "CATALOG_TRIAL_LOGIN"),
    ],
)
def test_wrong_settings_stop_the_start(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        from_env(env)


def test_the_published_contract_lists_exactly_the_apps_api(
    database_url: str, web_dir: Path
) -> None:
    """contracts/catalog.openapi.json and the app agree on every address and method (CAT-36)."""
    from contracts.generate import CATALOG_OPENAPI

    def addresses(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
        return {
            (method.upper(), path)
            for path, methods in paths.items()
            if path.startswith("/api/") and "{rest" not in path
            for method in methods
        }

    published = json.loads(CATALOG_OPENAPI.read_text(encoding="utf-8"))["paths"]
    served = create_app(settings_for(database_url, web_dir)).openapi()["paths"]
    assert addresses(served) == addresses(published)
