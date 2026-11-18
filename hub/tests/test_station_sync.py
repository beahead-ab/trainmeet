"""Stationspaketen through the cloud hub (SYNK-06, SYNK-18, SYNK-30): refused until TrainMeet ID
says who owns them (#78); with an owner, linear versions as they came."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.app import create_app
from hub.build_info import BuildInfo
from synk.tests.test_stations import outside, package

ROUTE = "/api/sync/1/stations"


@pytest.fixture
def cloud(tmp_path: Path) -> TestClient:
    return TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db"))


def as_owner(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """What TrainMeet ID says (hub/tests/test_id_owners.py): the Bearer token names the owner."""
    owners = client.app.state.owners  # type: ignore[attr-defined]
    monkeypatch.setattr(
        owners, "owner", lambda authorization: (authorization or "").removeprefix("Bearer ") or None
    )


def test_until_the_hub_logs_in_with_id_no_one_owns_a_station(cloud: TestClient) -> None:
    station = outside()["station_id"]
    refused = cloud.post(f"{ROUTE}/{station}/versions?base=0", content=package())
    assert refused.status_code == 403 and "TrainMeet ID" in refused.json()["detail"]
    assert cloud.get(f"{ROUTE}/{station}/versions").status_code == 403


def test_the_owner_saves_versions_one_after_another(
    cloud: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_owner(cloud, monkeypatch)
    station = outside()["station_id"]
    me = {"Authorization": "Bearer owner-1"}
    saved = cloud.post(f"{ROUTE}/{station}/versions?base=0", content=package(), headers=me)
    assert saved.status_code == 201, saved.text
    assert saved.json()["version"] == 1
    behind = cloud.post(
        f"{ROUTE}/{station}/versions?base=0", content=package(signals=6), headers=me
    )
    assert behind.status_code == 409 and behind.headers["TrainMeet-Latest"] == "1"
    assert (
        cloud.post(f"{ROUTE}/{station}/versions?base=1", content=package(), headers=me).status_code
        == 201
    )
    listed = cloud.get(f"{ROUTE}/{station}/versions", headers=me).json()
    assert [v["version"] for v in listed["versions"]] == [1, 2]
    assert cloud.get(f"{ROUTE}/{station}/versions/1", headers=me).content == package()
    # Someone else's station is not theirs to read or write.
    other = {"Authorization": "Bearer someone-else"}
    assert cloud.get(f"{ROUTE}/{station}/versions", headers=other).status_code == 403
    assert (
        cloud.post(
            f"{ROUTE}/{station}/versions?base=2", content=package(), headers=other
        ).status_code
        == 403
    )
    # A package for another station, or one that cannot be read, is refused.
    assert (
        cloud.post(f"{ROUTE}/annan/versions?base=0", content=package(), headers=me).status_code
        == 422
    )
    assert (
        cloud.post(f"{ROUTE}/{station}/versions?base=2", content=b"{}", headers=me).status_code
        == 422
    )
