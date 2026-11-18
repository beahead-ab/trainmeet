"""Stationspaketen i Synk (SYNK-06, SYNK-08, SYNK-12, SYNK-18, H71): the station owner's private
versions of the whole package, kept in the cloud hub.

The owner owns them; Synk only keeps them. Each save builds on the latest version: one on top of
an older version is refused, and the owner chooses which counts (linear, H71). Nothing is
written over quietly, and the package is kept as the bytes it came as, with its checksum. Only
the outside ever goes on, to a meet or a Pi (SYNK-12).

Who the owner is comes from TrainMeet ID (TKL18): the person TKL's token from ID names (#78,
SYNK-30). A hub without the login with ID has no owners, and every call is refused with 403.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Final, Protocol

from contracts.station_outside import StationOutside
from contracts.sync import StationPackage, StationVersionInfo

MAX_BYTES: Final = 2 * 1024 * 1024
MAX_VERSIONS: Final = 500

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS sync_station (
    station_id TEXT NOT NULL, version INTEGER NOT NULL, owner TEXT NOT NULL,
    saved REAL NOT NULL, checksum TEXT NOT NULL, name TEXT NOT NULL, body BLOB NOT NULL,
    PRIMARY KEY (station_id, version)
);
"""


class StationError(Exception):
    """The message is for the owner."""

    status = 409


class NotOwner(StationError):
    status = 403


class Behind(StationError):
    """A save on top of an older version. The latest is said, so the owner can choose."""

    def __init__(self, latest: int) -> None:
        super().__init__(
            f"Stationen har en nyare version, {latest}, än den sparningen bygger på. "
            "Välj vilken som ska gälla: hämta version "
            f"{latest} eller spara igen ovanpå den."
        )
        self.latest = latest


class Owners(Protocol):
    """Who calls, as TrainMeet ID says (TKL18): the owner's id, or None."""

    def owner(self, authorization: str | None) -> str | None: ...


class NoOwners:
    """A hub without the login with TrainMeet ID: no one is an owner here."""

    def owner(self, authorization: str | None) -> str | None:
        return None


class Stations:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ready = False
        self._lock = Lock()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(_SCHEMA)
                self._ready = True
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                yield db

    @staticmethod
    def _owned(db: sqlite3.Connection, station: str, owner: str) -> int:
        """The latest version, 0 for none. Raises NotOwner when someone else owns it."""
        row = db.execute(
            "SELECT owner, max(version) FROM sync_station WHERE station_id=? GROUP BY owner",
            (station,),
        ).fetchone()
        if row is None:
            return 0
        if row[0] != owner:
            raise NotOwner("Stationen är någon annans.")
        return int(row[1])

    def save(self, owner: str, base: int, data: bytes) -> StationVersionInfo:
        """A new version on top of base, kept as the bytes that came. Raises Behind when base
        is not the latest, and NotOwner for someone else's station."""
        if len(data) > MAX_BYTES:
            raise StationError("Stationspaketet är större än 2 MB.")
        package = StationPackage.model_validate_json(data)
        now = datetime.now(UTC)
        with self._transaction() as db:
            latest = self._owned(db, package.station_id, owner)
            if base != latest:
                raise Behind(latest)
            if latest >= MAX_VERSIONS:
                raise StationError("Stationen har redan 500 versioner.")
            info = StationVersionInfo(
                station_id=package.station_id,
                version=latest + 1,
                saved=now,
                checksum=hashlib.sha256(data).hexdigest(),
                name=package.outside.name,
            )
            db.execute(
                "INSERT INTO sync_station VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    info.station_id,
                    info.version,
                    owner,
                    now.timestamp(),
                    info.checksum,
                    info.name,
                    data,
                ),
            )
        return info

    def versions(self, owner: str, station: str) -> list[StationVersionInfo]:
        with self._transaction() as db:
            self._owned(db, station, owner)
            rows = db.execute(
                "SELECT version, saved, checksum, name FROM sync_station "
                "WHERE station_id=? ORDER BY version",
                (station,),
            ).fetchall()
        return [
            StationVersionInfo(
                station_id=station,
                version=version,
                saved=datetime.fromtimestamp(saved, UTC),
                checksum=checksum,
                name=name,
            )
            for version, saved, checksum, name in rows
        ]

    def package(self, owner: str, station: str, version: int) -> bytes:
        """The whole package of a version, as it came: only to its owner."""
        with self._transaction() as db:
            self._owned(db, station, owner)
            row = db.execute(
                "SELECT body FROM sync_station WHERE station_id=? AND version=?",
                (station, version),
            ).fetchone()
        if row is None:
            raise StationError(f"Stationen har ingen version {version}.")
        return bytes(row[0])

    def outside(self, station: str, version: int | None = None) -> tuple[int, StationOutside]:
        """Only the outside, for a meet or a Pi (SYNK-12): the latest version, or the one
        asked for. The inside never leaves Synk."""
        with self._transaction() as db:
            if version is None:
                row = db.execute(
                    "SELECT version, body FROM sync_station WHERE station_id=? "
                    "ORDER BY version DESC LIMIT 1",
                    (station,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT version, body FROM sync_station WHERE station_id=? AND version=?",
                    (station, version),
                ).fetchone()
        if row is None:
            raise StationError("Stationen finns inte i Synk.")
        return int(row[0]), StationPackage.model_validate_json(row[1]).outside
