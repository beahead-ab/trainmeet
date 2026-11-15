"""What runs on the hub: /api/version, the health check and the brand files. The start page
itself is apps/trafikledning (TRAFIK-21) and is tested there."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from contracts import hub as contract
from hub.app import create_app
from hub.build_info import BuildInfo

DEPLOYED = BuildInfo(
    version="0.1.0",
    hub_name="Testhubben",
    commit="29b7bb260a50b27c29f5147bcb43ccd469f41431",
    pr=3,
    title="Grundstommen",
    built=datetime(2026, 11, 6, 7, 12, tzinfo=UTC),
)


def client(info: BuildInfo) -> TestClient:
    return TestClient(create_app(info))


def test_healthz() -> None:
    response = client(DEPLOYED).get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_api_version() -> None:
    body = client(DEPLOYED).get("/api/version").json()
    assert body == {
        "product": "TrainMeet Hub",
        "version": "0.1.0",
        "hub_name": "Testhubben",
        "commit": "29b7bb260a50b27c29f5147bcb43ccd469f41431",
        "pr": 3,
        "title": "Grundstommen",
        "built": "2026-11-06T07:12:00Z",
        "pr_url": "https://github.com/beahead-ab/trainmeet/pull/3",
        "commit_url": "https://github.com/beahead-ab/trainmeet/commit/29b7bb260a50b27c29f5147bcb43ccd469f41431",
    }
    assert contract.Version.model_validate(body).pr == 3


def test_api_version_has_the_name_from_first_start(tmp_path: Path) -> None:
    hub = TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))
    local = hub.get("/api/version").json()
    assert (local["hub_name"], local["commit"], local["pr_url"]) == ("Hubben", None, None)
    hub.post("/api/hub/setup", json={"name": "Hubben Väst", "pin": "482915"})
    assert hub.get("/api/version").json()["hub_name"] == "Hubben Väst"


def test_the_brand_files_are_served() -> None:
    c = client(DEPLOYED)
    for path in (
        "/static/skylt.svg",
        "/static/favicon.svg",
        "/static/fonts/inter.woff2",
        "/static/fonts/jetbrains-mono.woff2",
    ):
        assert c.get(path).status_code == 200, path


def test_the_interactive_api_pages_are_off() -> None:
    c = client(DEPLOYED)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404, path
