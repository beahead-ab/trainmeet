"""SQLite backing for independent, temporary Provbanan runs on the public test hub."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from secrets import randbelow, token_hex, token_urlsafe
from threading import Lock
from typing import Any, Final, TypeVar

from contracts import drift as events
from contracts import station
from contracts.common import checksum
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift.engine import Drift, Refused, now_utc
from drift.terminal import Box, Boxes

RUN_LIFETIME: Final = timedelta(days=1)
MAX_RUNS: Final = 256
MAX_ACTIONS: Final = 2000
MAX_BOXES: Final = 16

T = TypeVar("T")

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
CREATE TABLE IF NOT EXISTS preview_join (
    run_id TEXT PRIMARY KEY REFERENCES preview_run(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS preview_box (
    client_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    state TEXT NOT NULL
);
"""


class MissingRun(Exception):
    """The browser has no live preview run."""


class RunLimit(Exception):
    """A preview run or the shared test hub reached its limit."""


class UnknownBox(Exception):
    """The box's session key does not belong to a live run."""


def _key_hash(key: str) -> str:
    return sha256(key.encode()).hexdigest()


def epoch_of(run_id: str) -> str:
    """What the boxes see of their run. Never the run id itself: that is the browser's key."""
    return sha256(("epoch:" + run_id).encode()).hexdigest()[:16]


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

    # --- TMBox web: boxes that join a run with its code ------------------------------------

    def join_code(self, run_id: str) -> str:
        """The run's code for boxes, made the first time it is asked for."""
        with self._transaction() as db:
            self._load(db, run_id, now_utc())
            row = db.execute("SELECT code FROM preview_join WHERE run_id=?", (run_id,)).fetchone()
            if row is not None:
                return str(row[0])
            while True:
                code = f"{randbelow(10**6):06d}"
                taken = db.execute("SELECT 1 FROM preview_join WHERE code=?", (code,)).fetchone()
                if taken is None:
                    db.execute("INSERT INTO preview_join VALUES (?, ?)", (run_id, code))
                    return code

    def login(self, name: str, code: str) -> tuple[str, str]:
        """A new box under Väntar. Returns its client id and its session key, shown once."""
        now = now_utc()
        with self._transaction() as db:
            row = db.execute(
                "SELECT j.run_id FROM preview_join j JOIN preview_run r ON r.id=j.run_id "
                "WHERE j.code=? AND r.expires>? AND r.package=?",
                (code, now.timestamp(), self.package_key),
            ).fetchone()
            if row is None:
                raise MissingRun()
            run_id = str(row[0])
            drift = self._load(db, run_id, now)
            count = db.execute(
                "SELECT count(*) FROM preview_box WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if count >= MAX_BOXES:
                raise RunLimit()
            client_id = "box-" + token_hex(6)
            key = token_urlsafe(32)
            box = Box(client_id=client_id, name=name, seen=len(drift.history))
            db.execute(
                "INSERT INTO preview_box VALUES (?, ?, ?, ?, ?)",
                (client_id, run_id, _key_hash(key), now.timestamp(), box.to_json()),
            )
        return client_id, key

    def _boxes(self, db: sqlite3.Connection, run_id: str) -> dict[str, tuple[Box, str]]:
        rows = db.execute(
            "SELECT client_id, state FROM preview_box WHERE run_id=? ORDER BY created, client_id",
            (run_id,),
        ).fetchall()
        return {str(cid): (Box.from_json(state), str(state)) for cid, state in rows}

    def _with_boxes(
        self, db: sqlite3.Connection, run_id: str, operation: Callable[[Boxes], T]
    ) -> T:
        now = now_utc()
        drift = self._load(db, run_id, now)
        size = len(drift.history)
        stored = self._boxes(db, run_id)
        boxes = Boxes(
            drift, {cid: box for cid, (box, _) in stored.items()}, epoch=epoch_of(run_id), now=now
        )
        boxes.catch_up()
        result = operation(boxes)
        self._save(db, run_id, drift.history[size:])
        for cid, box in boxes.boxes.items():
            state = box.to_json()
            if state != stored[cid][1]:
                db.execute("UPDATE preview_box SET state=? WHERE client_id=?", (state, cid))
        return result

    def _box_run(self, db: sqlite3.Connection, key: str) -> tuple[str, str]:
        row = db.execute(
            "SELECT b.client_id, b.run_id FROM preview_box b JOIN preview_run r ON r.id=b.run_id "
            "WHERE b.key_hash=? AND r.expires>?",
            (_key_hash(key), now_utc().timestamp()),
        ).fetchone()
        if row is None:
            raise UnknownBox()
        return str(row[0]), str(row[1])

    def box_frame(self, key: str) -> dict[str, Any]:
        with self._transaction() as db:
            client_id, run_id = self._box_run(db, key)
            return self._with_boxes(db, run_id, lambda b: b.frame(b.boxes[client_id]))

    def box_press(self, key: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as db:
            client_id, run_id = self._box_run(db, key)
            size = db.execute(
                "SELECT count(*) FROM preview_event WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if size >= MAX_ACTIONS:
                raise RunLimit()
            return self._with_boxes(db, run_id, lambda b: b.press(b.boxes[client_id], body))

    def clients(self, run_id: str) -> list[dict[str, Any]]:
        """The boxes of the run, waiting ones first, as the Client contract says."""
        with self._transaction() as db:
            boxes = self._with_boxes(db, run_id, lambda b: list(b.boxes.values()))
        listed = [
            {
                "client_id": box.client_id,
                "name": box.name,
                "kind": "tmbox_web",
                "status": "approved" if box.place else "waiting",
                "places": [box.place] if box.place else [],
                "side": box.side,
            }
            for box in boxes
        ]
        return sorted(listed, key=lambda item: item["status"] != "waiting")

    def assign(self, run_id: str, assignment: events.Assign) -> list[dict[str, Any]]:
        with self._transaction() as db:

            def give(boxes: Boxes) -> None:
                box = boxes.boxes.get(assignment.client_id)
                if box is None:
                    raise UnknownBox()
                boxes.assign(box, assignment.places[0], assignment.side)

            self._with_boxes(db, run_id, give)
        return self.clients(run_id)
