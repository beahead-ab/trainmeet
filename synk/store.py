"""Synk's versions (SYNK-08, SYNK-20): each meet's published versions, frozen, with their
checksums.

Synk shares Planering's SQLite file (SYNK-20) but owns the table of versions. Planering makes
the next version of the draft (Planning.freeze), and Synk keeps it: a version is written once,
never changed or deleted, and only its withdrawal is noted (PLAN-18). The package is kept as
the bytes it was published as, and the checksum is the SHA-256 of their canonical JSON (A11).
A hub that reads it with another version of the contracts gets the same bytes, unknown fields
and all (GRUND-17), and the same checksum, which says the package is whole (SYNK-10).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Final

from pydantic import ValidationError

from contracts.common import checksum
from contracts.meet import MeetPackage
from contracts.planning import Version
from core.sqlite import connect, prepare

# The same table Planering kept before Synk came (step 4a), so the versions in a hub's file
# stay where they are.
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS version (
    meet_id TEXT NOT NULL,
    number INTEGER NOT NULL, info TEXT NOT NULL, package TEXT NOT NULL,
    PRIMARY KEY (meet_id, number)
);
"""
_SEMVER: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


class SyncError(Exception):
    """Something Synk cannot do. The message is for the planner."""

    status = 409


class UnknownVersion(SyncError):
    status = 404


class Damaged(SyncError):
    """The stored package does not match its checksum: it is not whole."""

    status = 500


def newer(needed: str | None, running: str) -> bool:
    """Does the package need a newer hub than the one running (GRUND-18)? A version that is
    not a number, as in development, can run everything."""
    if not needed:
        return False
    want, have = _SEMVER.match(needed), _SEMVER.match(running)
    if want is None or have is None:
        return False
    return tuple(map(int, want.groups())) > tuple(map(int, have.groups()))


class Versions:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        # Ready before any thread uses Planering's file, which the stores share (core/sqlite.py).
        prepare(path, _SCHEMA)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, closing(connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    # --- Reading -----------------------------------------------------------------------------

    def meets(self) -> dict[str, list[Version]]:
        """Every meet's versions, in order."""
        found: dict[str, list[Version]] = {}
        with self._transaction() as db:
            for meet, info in db.execute("SELECT meet_id, info FROM version ORDER BY number"):
                found.setdefault(meet, []).append(Version.model_validate_json(info))
        return found

    def versions(self, meet: str) -> list[Version]:
        with self._transaction() as db:
            return _versions(db, meet)

    def stored(self, meet: str, number: int) -> tuple[Version, bytes]:
        """The version and its package as the bytes it was published as, checked against the
        checksum. Raises UnknownVersion or Damaged."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT info, package FROM version WHERE meet_id=? AND number=?", (meet, number)
            ).fetchone()
        if row is None:
            raise UnknownVersion("Den versionen av träffen finns inte.")
        version = Version.model_validate_json(row[0])
        data = str(row[1]).encode()
        if checksum(json.loads(data)) != version.checksum:
            raise Damaged(f"Version {number} stämmer inte med sin kontrollsumma.")
        return version, data

    def package(self, meet: str, number: int) -> MeetPackage:
        return MeetPackage.model_validate_json(self.stored(meet, number)[1])

    # --- Changing ----------------------------------------------------------------------------

    def publish(self, meet: str, data: bytes) -> Version:
        """The package, as published, becomes the meet's next version. The same package as the
        latest version is not a new version."""
        try:
            package = MeetPackage.model_validate_json(data)
            digest = checksum(json.loads(data))
        except (ValidationError, ValueError) as error:
            raise SyncError("Paketet går inte att läsa som ett träffpaket.") from error
        if package.meet.id != meet:
            raise SyncError("Paketet hör till en annan träff.")
        with self._transaction() as db:
            versions = _versions(db, meet)
            if versions and _same(db, versions[-1], digest, package):
                raise SyncError(f"Utkastet är detsamma som version {versions[-1].number}.")
            version = Version(
                meet=meet,
                number=(versions[-1].number + 1) if versions else 1,
                published=datetime.now(UTC),
                checksum=digest,
                conflicts=sum(f.severity == "conflict" for f in package.findings),
                observations=sum(f.severity == "observation" for f in package.findings),
            )
            db.execute(
                "INSERT INTO version VALUES (?, ?, ?, ?)",
                (meet, version.number, version.model_dump_json(), data.decode()),
            )
            return version

    def receive(self, version: Version, data: bytes) -> bool:
        """A version from the hub this one follows (SYNK-10): kept with the same number, only
        if the bytes match the checksum. A withdrawal there is noted here. True if anything
        changed. Raises Damaged, or SyncError if the number is taken by other bytes."""
        if checksum(json.loads(data)) != version.checksum:
            raise Damaged(f"Version {version.number} kom inte hel. Den hämtas igen.")
        with self._transaction() as db:
            row = db.execute(
                "SELECT info FROM version WHERE meet_id=? AND number=?",
                (version.meet, version.number),
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO version VALUES (?, ?, ?, ?)",
                    (version.meet, version.number, version.model_dump_json(), data.decode()),
                )
                return True
            kept = Version.model_validate_json(row[0])
            if kept.checksum != version.checksum:
                raise SyncError(f"Version {version.number} finns redan här med ett annat innehåll.")
            if kept.withdrawn is None and version.withdrawn is not None:
                db.execute(
                    "UPDATE version SET info=? WHERE meet_id=? AND number=?",
                    (
                        kept.model_copy(update={"withdrawn": version.withdrawn}).model_dump_json(),
                        version.meet,
                        version.number,
                    ),
                )
                return True
            return False

    def withdraw(self, meet: str, number: int) -> Version:
        """Dra tillbaka en version (PLAN-18, F21): it can no longer be started or switched to,
        but it stays, frozen, so that history and logs hold. A meet that runs it goes on, with
        a warning (H68)."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT info FROM version WHERE meet_id=? AND number=?", (meet, number)
            ).fetchone()
            if row is None:
                raise UnknownVersion("Versionen finns inte.")
            version = Version.model_validate_json(row[0])
            if version.withdrawn is not None:
                raise SyncError("Versionen är redan tillbakadragen.")
            withdrawn = version.model_copy(update={"withdrawn": datetime.now(UTC)})
            db.execute(
                "UPDATE version SET info=? WHERE meet_id=? AND number=?",
                (withdrawn.model_dump_json(), meet, number),
            )
            return withdrawn


def _same(db: sqlite3.Connection, latest: Version, digest: str, package: MeetPackage) -> bool:
    """The same package as the latest version: the same bytes, or the same content read with
    these contracts, so that a field the contracts gained since does not make a new version."""
    if latest.checksum == digest:
        return True
    (stored,) = db.execute(
        "SELECT package FROM version WHERE meet_id=? AND number=?", (latest.meet, latest.number)
    ).fetchone()
    try:
        return MeetPackage.model_validate_json(stored) == package
    except ValidationError:
        return False


def _versions(db: sqlite3.Connection, meet: str) -> list[Version]:
    return [
        Version.model_validate_json(info)
        for (info,) in db.execute(
            "SELECT info FROM version WHERE meet_id=? ORDER BY number", (meet,)
        )
    ]
