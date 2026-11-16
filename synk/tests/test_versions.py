"""Synk's versions (SYNK-08, SYNK-20, GRUND-17, GRUND-18): frozen, numbered, kept as the bytes
they were published as, and checked against their checksum."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from contracts.common import checksum
from synk.store import Damaged, SyncError, UnknownVersion, Versions, newer

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "provbanan.meet.json"


def published(phone: str = "101", **more: object) -> bytes:
    """Provbanan's package as Planering would hand it over, with one place's phone set."""
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for place in data["places"]:
        if place["id"] == "nby":
            place["phone"] = phone
    return json.dumps({**data, **more}, ensure_ascii=False).encode()


@pytest.fixture
def versions(tmp_path: Path) -> Versions:
    return Versions(tmp_path / "planering.sqlite3")


def meet() -> str:
    return str(json.loads(published())["meet"]["id"])


def test_a_published_package_gets_the_next_number_and_stays(versions: Versions) -> None:
    first = versions.publish(meet(), published())
    assert (first.number, first.checksum) == (1, checksum(json.loads(published())))
    with pytest.raises(SyncError, match="samma som version 1"):
        versions.publish(meet(), published())
    second = versions.publish(meet(), published("999"))
    assert second.number == 2
    old, new = versions.package(meet(), 1), versions.package(meet(), 2)
    assert next(p.phone for p in old.places if p.id == "nby") == "101"
    assert next(p.phone for p in new.places if p.id == "nby") == "999"
    assert [v.number for v in versions.versions(meet())] == [1, 2]
    assert list(versions.meets()) == [meet()]
    with pytest.raises(UnknownVersion):
        versions.package(meet(), 3)
    with pytest.raises(SyncError, match="annan träff"):
        versions.publish("en-annan", published("1"))
    with pytest.raises(SyncError, match="går inte att läsa"):
        versions.publish(meet(), b"{}")


def test_a_field_the_contracts_gained_makes_no_new_version(versions: Versions) -> None:
    """The same draft published after the contracts gained a field (here requires_hub, written
    as null) has other bytes but the same content: it is the same version."""
    versions.publish(meet(), published())
    with pytest.raises(SyncError, match="samma som version 1"):
        versions.publish(meet(), published(requires_hub=None))


def test_a_withdrawn_version_stays_but_is_marked(versions: Versions) -> None:
    """Dra tillbaka (PLAN-18, F21): the version is kept, frozen, so that history and logs hold."""
    versions.publish(meet(), published())
    withdrawn = versions.withdraw(meet(), 1)
    assert withdrawn.withdrawn is not None
    (listed,) = versions.versions(meet())
    assert listed.withdrawn == withdrawn.withdrawn
    assert versions.package(meet(), 1).meet.id == meet(), "still there to be read"
    with pytest.raises(SyncError, match="redan"):
        versions.withdraw(meet(), 1)
    with pytest.raises(UnknownVersion):
        versions.withdraw(meet(), 2)


def test_unknown_fields_are_kept_with_the_same_checksum(versions: Versions) -> None:
    """GRUND-17 and A11: a package from newer contracts keeps what this hub does not know, and
    its checksum is that of the bytes, never of the package read and written again."""
    data = published(later={"lane": 2})
    version = versions.publish(meet(), data)
    kept, raw = versions.stored(meet(), 1)
    assert raw == data and json.loads(raw)["later"] == {"lane": 2}
    assert kept.checksum == version.checksum == checksum(json.loads(data))


def test_a_damaged_version_is_said_and_never_run(versions: Versions, tmp_path: Path) -> None:
    versions.publish(meet(), published())
    with closing(sqlite3.connect(tmp_path / "planering.sqlite3")) as db, db:
        db.execute("UPDATE version SET package=replace(package, '101', '102')")
    with pytest.raises(Damaged, match="kontrollsumma"):
        versions.package(meet(), 1)


def test_the_versions_planering_kept_before_synk_are_read(tmp_path: Path) -> None:
    """A hub's file from step 4 has the versions in Planering's table, with a reference to the
    meet: Synk reads them where they are."""
    path = tmp_path / "planering.sqlite3"
    data = published()
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            "CREATE TABLE meet (id TEXT PRIMARY KEY);"
            "CREATE TABLE version (meet_id TEXT NOT NULL REFERENCES meet(id),"
            " number INTEGER NOT NULL, info TEXT NOT NULL, package TEXT NOT NULL,"
            " PRIMARY KEY (meet_id, number));"
        )
        info = {
            "meet": meet(),
            "number": 1,
            "published": "2026-11-15T10:00:00Z",
            "checksum": checksum(json.loads(data)),
        }
        db.execute("INSERT INTO meet VALUES (?)", (meet(),))
        db.execute(
            "INSERT INTO version VALUES (?, 1, ?, ?)", (meet(), json.dumps(info), data.decode())
        )
    versions = Versions(path)
    assert [v.number for v in versions.versions(meet())] == [1]
    assert versions.publish(meet(), published("999")).number == 2


def test_a_package_can_need_a_newer_hub() -> None:
    """GRUND-18: the lowest hub version a package needs."""
    assert newer("1.10.0", "1.9.3") and not newer("1.9.0", "1.10.0")
    assert not newer("0.1.0", "0.1.0") and not newer(None, "0.1.0")
    assert not newer("2.0.0", "dev"), "a hub in development runs everything"
