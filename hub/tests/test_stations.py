"""Stationens utsida i Planering (#73, IMPORT-10, IMPORT-18, IMPORT-31, PLAN-05, PLAN-11): the
outside TKL Studio writes is a source; a station is coupled to a place in advance, the plan's
track names that differ become questions, and the next version carries the outside."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from contracts import planning
from contracts.meet import MeetPackage
from hub.tests.test_planering import API, MEET, hub, planned, upload

__all__ = ["hub", "planned"]

LEKBY = "p4"  # Lekby in Värnamo's plan: tracks 1, 2 and L


def outside(exits: int = 2) -> dict[str, Any]:
    """Lekby as its owner drew it in TKL: track L is called Lok there."""
    return {
        "format": "trainmeet.station-outside/1",
        "station_id": "lekby-tkl",
        "name": "Lekby",
        "tracks": [
            {"id": "1", "label": "Spår 1"},
            {"id": "2", "label": "Spår 2"},
            {"id": "lok", "label": "Lokspåret"},
        ],
        "exits": [
            {"id": f"u{n}", "side": "left" if n == 1 else "right", "tracks": ["1", "2"]}
            for n in range(1, exits + 1)
        ],
    }


def added(client: TestClient, given: dict[str, Any]) -> planning.Draft:
    shown = client.post(
        f"{API}/meets/{MEET}/sources",
        params={"name": "lekby.station.json"},
        content=json.dumps(given).encode(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert shown.status_code == 201, shown.text
    preview = planning.ImportPreview.model_validate(shown.json())
    assert preview.source.kind == planning.SourceKind.STATION_OUTSIDE
    laid = client.post(f"{API}/meets/{MEET}/sources/{preview.source.id}/apply")
    assert laid.status_code == 200, laid.text
    return planning.Draft.model_validate(laid.json())


def couple(client: TestClient, station: str | None) -> Any:
    draft = planning.Draft.model_validate(client.get(f"{API}/meets/{MEET}").json())
    return client.post(
        f"{API}/meets/{MEET}/changes",
        json={"revision": draft.revision, "changes": [{"place": LEKBY, "station": station}]},
    )


def test_a_station_is_coupled_and_the_version_carries_its_outside(planned: TestClient) -> None:
    draft = added(planned, outside())
    [kept] = draft.stations
    assert (kept.version, kept.outside.station_id) == (1, "lekby-tkl")
    coupled = couple(planned, "lekby-tkl")
    assert coupled.status_code == 200, coupled.text
    draft = planning.Draft.model_validate(coupled.json())
    assert draft.package is not None
    station = next(p for p in draft.package.places if p.id == LEKBY).station
    assert station is not None and station.track_map == {"1": "1", "2": "2"}
    # Track L is called Lok in the station: a question, answered like the others.
    [asked] = [q for q in draft.questions if q.cause == "station_track"]
    assert "planens spår L i Lekby" in asked.message
    assert [a.value for a in asked.alternatives] == ["1", "2", "lok"]
    answered = planned.post(
        f"{API}/meets/{MEET}/answers", json={"question": asked.id, "value": "lok"}
    )
    assert answered.status_code == 200, answered.text
    draft = planning.Draft.model_validate(answered.json())
    assert draft.package is not None
    station = next(p for p in draft.package.places if p.id == LEKBY).station
    assert station is not None and station.track_map["L"] == "lok"
    # The next version carries the outside, pinned (PLAN-11).
    assert planned.post(f"{API}/meets/{MEET}/versions").status_code == 201
    package = MeetPackage.model_validate(planned.get(f"{API}/meets/{MEET}/versions/1").json())
    pinned = next(p for p in package.places if p.id == LEKBY).station
    assert pinned is not None and pinned.version == 1 and pinned.outside.name == "Lekby"
    assert pinned.track_map == {"1": "1", "2": "2", "L": "lok"}


def test_the_same_outside_again_changes_nothing_and_a_new_one_is_the_next(
    planned: TestClient,
) -> None:
    """IMPORT-31: read again, the same outside changes nothing; a changed one is version 2, and
    the coupled place follows it."""
    added(planned, outside())
    assert couple(planned, "lekby-tkl").status_code == 200
    before = planning.Draft.model_validate(planned.get(f"{API}/meets/{MEET}").json())
    again = added(planned, outside())
    assert again.revision == before.revision and again.stations == before.stations
    newer = added(planned, outside(exits=3))
    assert [s.version for s in newer.stations] == [1 + 1]
    assert newer.package is not None
    station = next(p for p in newer.package.places if p.id == LEKBY).station
    assert station is not None and station.version == 2 and len(station.outside.exits) == 3
    assert len([s for s in newer.sources if s.kind == planning.SourceKind.STATION_OUTSIDE]) == 1
    # Koppla bort, and a station that is not among the sources.
    assert couple(planned, "finns-inte").status_code == 409
    gone = planning.Draft.model_validate(couple(planned, None).json())
    assert gone.package is not None
    assert next(p for p in gone.package.places if p.id == LEKBY).station is None


def test_the_plan_comes_before_the_station(hub: TestClient) -> None:
    assert hub.post(API + "/meets", json={"name": "Värnamo Moduldagar"}).status_code == 201
    refused = upload(hub, data=json.dumps(outside()).encode(), name="lekby.station.json")
    assert refused.status_code == 409 and "planeringsfilen" in refused.json()["detail"]
    broken = dict(outside(), tracks=[])
    response = upload(hub, data=json.dumps(broken).encode(), name="lekby.station.json")
    assert response.status_code == 422
