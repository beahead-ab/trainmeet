"""SQLite backing for independent, temporary Provbanan runs on the public test hub."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from secrets import token_hex
from threading import Lock
from typing import Final

from contracts import drift as events
from contracts import station
from contracts.common import checksum
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Refused, now_utc

RUN_LIFETIME: Final = timedelta(days=1)
MAX_RUNS: Final = 256
MAX_ACTIONS: Final = 2000

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS preview_run (
    id TEXT PRIMARY KEY, expires REAL NOT NULL, package TEXT NOT NULL, boot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preview_event (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS preview_receipt (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL, message_id TEXT NOT NULL, reason TEXT,
    PRIMARY KEY (run_id, client_id, message_id)
);
"""


class MissingRun(Exception):
    """The browser has no live preview run."""


class RunLimit(Exception):
    """A preview run or the shared test hub reached its limit."""


class PreviewStore:
    def __init__(self, path: Path, package: MeetPackage) -> None:
        self.path = path
        self.package = package
        self.package_key = checksum(package.model_dump(mode="json"))
        self.boot = token_hex(16)
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
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def _save(db: sqlite3.Connection, run_id: str, new_events: list[events.DriftEvent]) -> None:
        db.executemany(
            "INSERT INTO preview_event VALUES (?, ?, ?)",
            ((run_id, event.seq, event.model_dump_json()) for event in new_events),
        )

    def _load(self, db: sqlite3.Connection, run_id: str, now: datetime) -> Drift:
        row = db.execute(
            "SELECT boot FROM preview_run WHERE id=? AND expires>? AND package=?",
            (run_id, now.timestamp(), self.package_key),
        ).fetchone()
        if row is None:
            raise MissingRun()
        history = [
            events.DriftEvent.model_validate_json(body)
            for (body,) in db.execute(
                "SELECT body FROM preview_event WHERE run_id=? ORDER BY seq", (run_id,)
            )
        ]
        drift = Drift(self.package, history, now=now)
        if row[0] != self.boot:
            size = len(history)
            drift.pause_after_restart(now)
            self._save(db, run_id, drift.history[size:])
            db.execute("UPDATE preview_run SET boot=? WHERE id=?", (self.boot, run_id))
        return drift

    def start(self) -> str:
        now = now_utc()
        with self._transaction() as db:
            db.execute(
                "DELETE FROM preview_run WHERE expires<=? OR package!=?",
                (
                    now.timestamp(),
                    self.package_key,
                ),
            )
            count = db.execute("SELECT count(*) FROM preview_run").fetchone()[0]
            if count >= MAX_RUNS:
                raise RunLimit()
            run_id = token_hex(24)
            db.execute(
                "INSERT INTO preview_run VALUES (?, ?, ?, ?)",
                (run_id, (now + RUN_LIFETIME).timestamp(), self.package_key, self.boot),
            )
            drift = Drift(self.package, [], now=now)
            drift.start(now)
            self._save(db, run_id, drift.history)
        return run_id

    def state(self, run_id: str) -> Drift:
        with self._transaction() as db:
            return self._load(db, run_id, now_utc())

    def clock(self, run_id: str, control: events.ClockControl) -> Drift:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if size >= MAX_ACTIONS:
                raise RunLimit()
            drift.control_clock(control, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def command(self, run_id: str, command: station.Command) -> Drift:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            identity = (run_id, command.client_id, command.message_id)
            receipt = db.execute(
                "SELECT reason FROM preview_receipt "
                "WHERE run_id=? AND client_id=? AND message_id=?",
                identity,
            ).fetchone()
            if receipt is not None:
                if receipt[0] is not None:
                    raise Refused(Reason(receipt[0]))
                return drift
            size = len(drift.history)
            count = db.execute(
                "SELECT count(*) FROM preview_receipt WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if max(size, count) >= MAX_ACTIONS:
                raise RunLimit()
            reason = None
            try:
                drift.command(command, now)
            except Refused as error:
                reason = error.reason
            self._save(db, run_id, drift.history[size:])
            db.execute("INSERT INTO preview_receipt VALUES (?, ?, ?, ?)", (*identity, reason))
        if reason is not None:
            raise Refused(reason)
        return drift
