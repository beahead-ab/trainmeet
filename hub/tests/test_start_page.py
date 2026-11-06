"""The empty hub: what Casper sees on test.hub.trainmeet.app after step 1."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

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


def test_start_page_shows_an_empty_hub_with_its_version() -> None:
    response = client(DEPLOYED).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Tom hubb" in html
    assert "<dd>0.1.0</dd>" in html
    assert '<span class="sida">Testhubben</span>' in html


def test_start_page_shows_the_change_that_runs() -> None:
    html = client(DEPLOYED).get("/").text
    assert 'href="https://github.com/beahead-ab/trainmeet/pull/3"' in html
    assert "#3 Grundstommen" in html
    assert ">29b7bb2</a>" in html
    assert "2026-11-06 07:12 UTC" in html


def test_a_local_build_says_so() -> None:
    html = client(BuildInfo(version="0.1.0")).get("/").text
    assert "Lokalt bygge" in html
    assert '<span class="sida">Hubben</span>' in html


def test_the_pull_request_title_cannot_inject_html() -> None:
    info = BuildInfo(version="0.1.0", pr=4, title="<script>alert(1)</script>")
    html = client(info).get("/").text
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_header_has_the_sign_the_dots_and_the_page_name() -> None:
    html = client(DEPLOYED).get("/").text
    sign = html.index('src="/static/skylt.svg"')
    dots = html.index('aria-label="Hub"')
    line = html.index('class="streck"')
    name = html.index('class="sida"')
    assert sign < dots < line < name


def test_the_page_fetches_nothing_from_other_sites() -> None:
    html = client(DEPLOYED).get("/").text
    for tag in ("<script", "<link"):
        for part in html.split(tag)[1:]:
            assert "https://" not in part.split(">")[0]
    assert "url(http" not in html


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
        "built": "2026-11-06T07:12:00+00:00",
    }


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
