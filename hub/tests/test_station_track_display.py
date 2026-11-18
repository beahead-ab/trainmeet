"""Spår-vyn over the station protocol (BOXIOS-16, H65): two phones at the same place share the
station's choice; a stale revision never overwrites; a reset counts on; and the choice is only
presentation, never a drift event. Ported from the old Server's TrackDisplayHTTPTests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_tmbox_web import started

API = "/api/station/1"


@pytest.fixture
def hub(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))


def phone(hub: TestClient, code: str, place: str = "asn") -> dict[str, str]:
    body = {"kind": "tmbox_app", "name": "Telefonen", "software": "TMBox 3.0.0", "code": code}
    client_id = hub.post(API + "/connect", json=body).json()["client_id"]
    hub.post("/api/provbanan/clients/approve", json={"client_id": client_id, "places": [place]})
    key = hub.get(f"{API}/connect/{client_id}").json()["key"]
    return {"Authorization": "Bearer " + key}


def tracks(seen: dict[str, Any]) -> list[tuple[str, bool]]:
    return [(t["track"], t["visible"]) for t in seen["track_display"]["tracks"]]


def save(hub: TestClient, headers: dict[str, str], revision: int, *shown: tuple[str, bool]) -> Any:
    body: dict[str, Any] = {"revision": revision}
    if shown:
        body["tracks"] = [{"track": t, "visible": v} for t, v in shown]
    return hub.put(f"{API}/places/asn/track-display", json=body, headers=headers)


def test_two_phones_share_the_places_choice(hub: TestClient) -> None:
    code = started(hub)
    one, two = phone(hub, code), phone(hub, code)
    seen = hub.get(f"{API}/places/asn", headers=one).json()
    assert tracks(seen) == [("1", True), ("2", True), ("3", True)]
    assert seen["track_display"] == {
        "revision": 0,
        "customized": False,
        "tracks": seen["track_display"]["tracks"],
    }
    saved = save(hub, one, 0, ("3", True), ("1", True), ("2", False))
    assert saved.status_code == 200, saved.text
    assert tracks(saved.json()) == [("3", True), ("1", True), ("2", False)]
    other = hub.get(f"{API}/places/asn", headers=two).json()["track_display"]
    assert (other["revision"], other["customized"]) == (1, True)
    after = hub.get(f"{API}/places/asn", headers=two).json()
    assert after["place_revision"] == seen["place_revision"], "only presentation: no drift event"
    # The second phone read revision 0: it may not overwrite the first one's choice.
    stale = save(hub, two, 0, ("1", True), ("2", True), ("3", True))
    assert (stale.status_code, stale.json()["detail"]) == (
        409,
        "Någon annan har ändrat spårvisningen sedan du läste den. Läs om.",
    )
    missing = save(hub, two, 1, ("1", True), ("2", True))
    assert (missing.status_code, missing.json()["detail"]) == (
        409,
        "Stationens spår har ändrats. Läs om.",
    )
    # Återställ: the meet's order again, and the revision counts on.
    reset = save(hub, two, 1)
    assert reset.status_code == 200
    assert reset.json()["track_display"]["revision"] == 2
    assert reset.json()["track_display"]["customized"] is False
    assert tracks(reset.json()) == [("1", True), ("2", True), ("3", True)]


def test_only_where_the_key_is_approved(hub: TestClient) -> None:
    code = started(hub)
    norrby = phone(hub, code, "nby")
    refused = save(hub, norrby, 0, ("1", True))
    assert refused.status_code == 403
    assert hub.put(f"{API}/places/asn/track-display", json={"revision": 0}).status_code == 401
