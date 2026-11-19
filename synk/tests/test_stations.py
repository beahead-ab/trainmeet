"""Stationspaketen i Synk (SYNK-06, SYNK-12, SYNK-18, H71): the owner's private versions, linear,
kept as they came; only the outside goes on."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from synk.stations import MAX_BYTES, Behind, NotOwner, StationError, Stations


def outside() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        files("contracts").joinpath("examples/asen.station-outside.json").read_text()
    )
    return data


def package(name: str = "Åsen", signals: int = 4) -> bytes:
    side = {**outside(), "name": name}
    body = {"station_id": side["station_id"], "outside": side, "inside": {"signaler": signals}}
    return json.dumps(body, ensure_ascii=False).encode()


@pytest.fixture
def stations(tmp_path: Path) -> Stations:
    return Stations(tmp_path / "planering.sqlite3")


def test_versions_are_linear_and_nothing_is_written_over(stations: Stations) -> None:
    station = outside()["station_id"]
    first = stations.save("ägare-1", 0, package())
    assert (first.version, first.name) == (1, "Åsen")
    assert first.checksum == hashlib.sha256(package()).hexdigest()
    # A second save on top of version 0 is refused, and says which is the latest (H71).
    with pytest.raises(Behind) as behind:
        stations.save("ägare-1", 0, package(signals=6))
    assert behind.value.latest == 1 and "version 1" in str(behind.value)
    second = stations.save("ägare-1", 1, package("Åsen ny", signals=6))
    assert second.version == 2
    assert [v.version for v in stations.versions("ägare-1", station)] == [1, 2]
    # Kept as the bytes that came, the inside too.
    assert stations.package("ägare-1", station, 1) == package()
    assert json.loads(stations.package("ägare-1", station, 2))["inside"] == {"signaler": 6}


def test_only_the_outside_goes_on(stations: Stations) -> None:
    station = outside()["station_id"]
    stations.save("ägare-1", 0, package())
    stations.save("ägare-1", 1, package("Åsen ny"))
    version, side = stations.outside(station)
    assert (version, side.name) == (2, "Åsen ny")
    assert stations.outside(station, 1)[1].name == "Åsen"
    assert "signaler" not in side.model_dump_json()
    with pytest.raises(StationError):
        stations.outside("finns-inte")


def test_the_station_is_its_owners(stations: Stations) -> None:
    station = outside()["station_id"]
    stations.save("ägare-1", 0, package())
    with pytest.raises(NotOwner):
        stations.save("någon-annan", 1, package())
    with pytest.raises(NotOwner):
        stations.versions("någon-annan", station)
    with pytest.raises(NotOwner):
        stations.package("någon-annan", station, 1)


def test_a_package_that_is_too_big_or_broken_is_not_kept(stations: Stations) -> None:
    with pytest.raises(StationError):
        stations.save("ägare-1", 0, b"x" * (MAX_BYTES + 1))
    with pytest.raises(ValueError):
        stations.save("ägare-1", 0, b'{"station_id": "asen"}')


def test_the_owner_s_stations_are_listed_with_their_latest_version(stations: Stations) -> None:
    """Dina stationer (TKL5, TKLMOLN-02): each of the owner's stations once, its latest version;
    never another owner's."""

    def other(station_id: str, name: str) -> bytes:
        side = {**outside(), "station_id": station_id, "name": name}
        return json.dumps({"station_id": station_id, "outside": side}).encode()

    stations.save("ägare-1", 0, package())
    stations.save("ägare-1", 1, package("Åsen ny"))
    stations.save("ägare-1", 0, other("exb", "Exempelby"))
    stations.save("någon-annan", 0, other("ovr", "Övrigby"))
    mine = stations.owned("ägare-1")
    assert sorted((s.station_id, s.version, s.name) for s in mine) == [
        (outside()["station_id"], 2, "Åsen ny"),
        ("exb", 1, "Exempelby"),
    ]
    assert [s.station_id for s in stations.owned("någon-annan")] == ["ovr"]
    assert stations.owned("ingen") == []
