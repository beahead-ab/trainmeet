"""SQLite backing for independent, temporary Provbanan runs on the public test hub."""

from __future__ import annotations

import json
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
from contracts.meet import MeetPackage, PlaceKind
from contracts.reasons import TEXT_SV, Reason
from contracts.terminal import DisplaySize
from drift.engine import Drift, Outcome, Refused, now_utc
from drift.snapshot import snapshot
from drift.terminal import Box, Boxes
from drift.terminal_text import COUNTRY_LANGUAGE

RUN_LIFETIME: Final = timedelta(days=1)
MAX_RUNS: Final = 256
MAX_ACTIONS: Final = 2000
MAX_BOXES: Final = 16
MAX_STATION_CLIENTS: Final = 16

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
CREATE TABLE IF NOT EXISTS station_client (
    client_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    request TEXT NOT NULL,
    status TEXT NOT NULL,
    places TEXT NOT NULL,
    key_hash TEXT UNIQUE,
    key_once TEXT
);
CREATE TABLE IF NOT EXISTS station_reply (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL, message_id TEXT NOT NULL, signature TEXT NOT NULL,
    answer TEXT NOT NULL,
    PRIMARY KEY (run_id, client_id, message_id)
);
"""


class MissingRun(Exception):
    """The browser has no live preview run."""


class RunLimit(Exception):
    """A preview run or the shared test hub reached its limit."""


class UnknownBox(Exception):
    """The box's session key does not belong to a live run."""


class UnknownClient(Exception):
    """No station client with that id, or its key is not (or no longer) valid."""


class NotApproved(Exception):
    """The client is not approved for that place."""


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

    def login(self, name: str, code: str, display: DisplaySize | None = None) -> tuple[str, str]:
        """A new box under Väntar. Returns its client id and its session key, shown once.
        The box speaks the meet's language until the dispatcher picks another, and is drawn
        at the size it announced (16×2 unless it says 20×4)."""
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
            size = display or DisplaySize()
            box = Box(
                client_id=client_id,
                name=name,
                seen=len(drift.history),
                language=COUNTRY_LANGUAGE.get(drift.package.meet.country, "sv"),
                rows=size.rows,
                cols=size.cols,
            )
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
        """The boxes and station clients of the run, waiting ones first, as the Client
        contract says."""
        with self._transaction() as db:
            boxes = self._with_boxes(db, run_id, lambda b: list(b.boxes.values()))
            others = self._station_clients(db, run_id)
        listed = [
            {
                "client_id": box.client_id,
                "name": box.name,
                "kind": "tmbox_web",
                "status": "approved" if box.place else "waiting",
                "places": [box.place] if box.place else [],
                "side": box.side,
                "language": box.language,
                "display": {"rows": box.rows, "cols": box.cols},
            }
            for box in boxes
        ]
        return sorted(listed + others, key=lambda item: item["status"] != "waiting")

    def assign(self, run_id: str, assignment: events.Assign) -> list[dict[str, Any]]:
        with self._transaction() as db:

            def give(boxes: Boxes) -> None:
                box = boxes.boxes.get(assignment.client_id)
                if box is None:
                    raise UnknownBox()
                boxes.assign(box, assignment.places[0], assignment.side, assignment.language)

            self._with_boxes(db, run_id, give)
        return self.clients(run_id)

    # --- The station protocol: TKL, the TMBox app and the dispatcher's views -------------

    def _run_by_code(self, db: sqlite3.Connection, code: str) -> str:
        row = db.execute(
            "SELECT j.run_id FROM preview_join j JOIN preview_run r ON r.id=j.run_id "
            "WHERE j.code=? AND r.expires>? AND r.package=?",
            (code, now_utc().timestamp(), self.package_key),
        ).fetchone()
        if row is None:
            raise MissingRun()
        return str(row[0])

    def connect(self, request: station.ConnectRequest) -> station.ConnectReply:
        """A client says what it is; it waits under Väntar until the dispatcher approves it
        (H31). In a Provbana run it finds the run with the run's code."""
        with self._transaction() as db:
            run_id = self._run_by_code(db, request.code or "")
            count = db.execute(
                "SELECT count(*) FROM station_client WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if count >= MAX_STATION_CLIENTS:
                raise RunLimit()
            client_id = f"{request.kind.value}-{token_hex(6)}"
            stored = request.model_copy(update={"code": None})
            db.execute(
                "INSERT INTO station_client VALUES (?, ?, ?, ?, ?, '[]', NULL, NULL)",
                (
                    client_id,
                    run_id,
                    now_utc().timestamp(),
                    stored.model_dump_json(),
                    station.ApprovalStatus.WAITING.value,
                ),
            )
        return station.ConnectReply(client_id=client_id, status=station.ApprovalStatus.WAITING)

    def connection(self, client_id: str) -> station.ConnectReply:
        """How the approval stands. The key comes once, in the first answer after it."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT c.status, c.places, c.key_once FROM station_client c "
                "JOIN preview_run r ON r.id=c.run_id WHERE c.client_id=? AND r.expires>?",
                (client_id, now_utc().timestamp()),
            ).fetchone()
            if row is None:
                raise UnknownClient()
            status, places, key = station.ApprovalStatus(row[0]), json.loads(row[1]), row[2]
            if key is not None:
                db.execute(
                    "UPDATE station_client SET key_once=NULL WHERE client_id=?", (client_id,)
                )
        return station.ConnectReply(client_id=client_id, status=status, places=places, key=key)

    def approve(self, run_id: str, approval: events.Approve) -> list[dict[str, Any]]:
        """The dispatcher approves a client for places. A new key replaces any old one."""
        with self._transaction() as db:
            drift = self._load(db, run_id, now_utc())
            stops = {p.id for p in drift.package.places if p.kind != PlaceKind.HALT}
            if not set(approval.places) <= stops:
                raise Refused(Reason.WRONG_PLACE)
            key = token_urlsafe(32)
            changed = db.execute(
                "UPDATE station_client SET status=?, places=?, key_hash=?, key_once=? "
                "WHERE client_id=? AND run_id=?",
                (
                    station.ApprovalStatus.APPROVED.value,
                    json.dumps(approval.places),
                    _key_hash(key),
                    key,
                    approval.client_id,
                    run_id,
                ),
            ).rowcount
            if not changed:
                raise UnknownClient()
        return self.clients(run_id)

    def revoke(self, run_id: str, revocation: events.Revoke) -> list[dict[str, Any]]:
        """The key stops working at once; the client has to be approved again."""
        with self._transaction() as db:
            changed = db.execute(
                "UPDATE station_client SET status=?, key_hash=NULL, key_once=NULL "
                "WHERE client_id=? AND run_id=?",
                (station.ApprovalStatus.REVOKED.value, revocation.client_id, run_id),
            ).rowcount
            if not changed:
                raise UnknownClient()
        return self.clients(run_id)

    def _station_clients(self, db: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
        listed = []
        for client_id, request, status, places in db.execute(
            "SELECT client_id, request, status, places FROM station_client WHERE run_id=? "
            "ORDER BY created, client_id",
            (run_id,),
        ):
            asked = station.ConnectRequest.model_validate_json(request)
            listed.append(
                {
                    "client_id": client_id,
                    "name": asked.name,
                    "kind": asked.kind.value,
                    "status": status,
                    "places": json.loads(places) or asked.wants,
                    "side": "both",
                }
            )
        return listed

    def _approved(self, db: sqlite3.Connection, key: str) -> tuple[str, str, list[str]]:
        row = db.execute(
            "SELECT c.client_id, c.run_id, c.places FROM station_client c "
            "JOIN preview_run r ON r.id=c.run_id "
            "WHERE c.key_hash=? AND c.status=? AND r.expires>?",
            (_key_hash(key), station.ApprovalStatus.APPROVED.value, now_utc().timestamp()),
        ).fetchone()
        if row is None:
            raise UnknownClient()
        return str(row[0]), str(row[1]), list(json.loads(row[2]))

    def place_snapshot(self, key: str, place: str) -> station.Snapshot:
        with self._transaction() as db:
            _, run_id, places = self._approved(db, key)
            if place not in places:
                raise NotApproved()
            now = now_utc()
            return snapshot(self._load(db, run_id, now), place, now)

    def place_revision(self, key: str, place: str) -> int:
        """For the event stream: the number that moves when the place's snapshot changes."""
        with self._transaction() as db:
            _, run_id, places = self._approved(db, key)
            if place not in places:
                raise NotApproved()
            drift = self._load(db, run_id, now_utc())
            return drift.place_revision.get(place, 0)

    def station_command(self, key: str, command: station.Command) -> station.Reply:
        """One command from an approved client, answered with the place's snapshot. The same
        message id answers the same, without a second effect (v2)."""
        with self._transaction() as db:
            client_id, run_id, places = self._approved(db, key)
            if command.client_id != client_id or command.place not in places:
                raise NotApproved()
            now = now_utc()
            signature = sha256(command.model_dump_json().encode()).hexdigest()
            earlier = db.execute(
                "SELECT signature, answer FROM station_reply "
                "WHERE run_id=? AND client_id=? AND message_id=?",
                (run_id, client_id, command.message_id),
            ).fetchone()
            drift = self._load(db, run_id, now)
            if earlier is not None:
                if earlier[0] != signature:
                    raise NotApproved()  # One message id, one command.
                first = json.loads(earlier[1])
                status = (
                    station.ReplyStatus.DUPLICATE
                    if first["status"] == station.ReplyStatus.ACCEPTED
                    else station.ReplyStatus(first["status"])
                )
                return station.Reply.model_validate(
                    {
                        **first,
                        "status": status,
                        "snapshot": snapshot(drift, command.place, now).model_dump(mode="json"),
                    }
                )
            if (
                db.execute(
                    "SELECT count(*) FROM station_reply WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                >= MAX_ACTIONS
                or len(drift.history) >= MAX_ACTIONS
            ):
                raise RunLimit()
            size = len(drift.history)
            reason: Reason | None = None
            outcome = Outcome()
            try:
                outcome = drift.command(command, now)
            except Refused as error:
                reason = error.reason
            self._save(db, run_id, drift.history[size:])
            answer: dict[str, Any] = {
                "message_id": command.message_id,
                "status": station.ReplyStatus.REJECTED if reason else station.ReplyStatus.ACCEPTED,
                "reason": reason,
                "message": TEXT_SV[reason] if reason else None,
                "revision": outcome.revision.model_dump(mode="json") if outcome.revision else None,
                "result": [m.model_dump(mode="json") for m in outcome.result]
                if command.action == station.Action.TRAIN_LOOKUP and reason is None
                else None,
            }
            db.execute(
                "INSERT INTO station_reply VALUES (?, ?, ?, ?, ?)",
                (run_id, client_id, command.message_id, signature, json.dumps(answer)),
            )
            return station.Reply.model_validate(
                {**answer, "snapshot": snapshot(drift, command.place, now).model_dump(mode="json")}
            )
