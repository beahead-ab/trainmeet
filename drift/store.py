"""SQLite backing for independent, temporary Provbanan runs on the public test hub."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from secrets import randbelow, token_hex, token_urlsafe
from threading import Lock, local
from typing import Any, Final, TypeVar

from contracts import drift as events
from contracts import station
from contracts.common import Weekday, checksum
from contracts.meet import DriverLevel, MeetPackage, PlaceKind
from contracts.reasons import TEXT_SV, Reason
from contracts.station_outside import StationOutside
from contracts.terminal import DisplaySize
from drift.automatik import Automatik
from drift.copy import EventCopy
from drift.drivers import messages_here
from drift.engine import Drift, Outcome, Refused, model_time, now_utc
from drift.exits import ExitMemory, couple
from drift.notices import notices
from drift.snapshot import snapshot
from drift.terminal import Box, Boxes
from drift.terminal_text import COUNTRY_LANGUAGE
from drift.track_display import base_order, checked, shown

RUN_LIFETIME: Final = timedelta(days=1)
MAX_RUNS: Final = 256
MAX_ACTIONS: Final = 2000
MAX_CLIENTS: Final = 16  # boxes, station clients and screens of each kind in a Provbanan run
MAX_REFUSALS: Final = 500
# Drivers in a run: more than a big meet has drivers, phones changed included (LOK-40).
MAX_DRIVERS: Final = 500
# A driver's photo is a small picture the phone has already cut and scaled (LOK-27).
PHOTO_MAX_BYTES: Final = 96 * 1024

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
CREATE TABLE IF NOT EXISTS station_push (
    client_id TEXT PRIMARY KEY REFERENCES station_client(client_id) ON DELETE CASCADE,
    token TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screen (
    client_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    name TEXT NOT NULL,
    view TEXT
);
CREATE TABLE IF NOT EXISTS drift_refusal (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    at REAL NOT NULL, model_time TEXT NOT NULL, client_id TEXT NOT NULL, place TEXT,
    what TEXT NOT NULL, reason TEXT, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mirror_run (
    run_id TEXT PRIMARY KEY REFERENCES preview_run(id) ON DELETE CASCADE,
    leader TEXT NOT NULL, heard REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS forked_event (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, body TEXT NOT NULL, set_aside REAL NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS station_exit (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    station_id TEXT NOT NULL, section TEXT NOT NULL, exit TEXT NOT NULL,
    PRIMARY KEY (run_id, station_id, section)
);
CREATE TABLE IF NOT EXISTS track_display (
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    place TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT,
    PRIMARY KEY (run_id, place)
);
CREATE TABLE IF NOT EXISTS driver (
    driver_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES preview_run(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    state TEXT,
    person TEXT,
    photo BLOB,
    photo_type TEXT,
    photo_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS driver_join (
    run_id TEXT PRIMARY KEY REFERENCES preview_run(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE
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


class ExitAnswered(Exception):
    """Hubbens fråga om utfarten är redan besvarad: det första svaret gäller (TRAFIK-05)."""

    def __init__(self, exit_id: str) -> None:
        super().__init__(f"Frågan är redan besvarad: utfart {exit_id}.")


class UnknownExit(Exception):
    """No such exit at the station, or no such section at the place."""


class UnknownDriver(Exception):
    """No driver in a live run with that key or id."""


@dataclass(frozen=True)
class DriverRecord:
    """A driver as the store keeps them, beside the events: the name, the level and whether a
    photo is there. The key is kept only as its hash, and the person from TrainMeet ID only
    as ID's id (LOK-16)."""

    id: str
    run_id: str
    name: str
    level: DriverLevel
    state: str | None
    person: str | None
    photo_type: str | None
    photo_version: int
    joined: datetime


def _key_hash(key: str) -> str:
    return sha256(key.encode()).hexdigest()


class KeyHash(str):
    """A station client's key as its hash, as the relay carries it (H31, SYNK-11). A station
    client's calls take it in place of the key."""


def key_hash(key: str) -> KeyHash:
    """What the relay sends instead of the key."""
    return KeyHash(_key_hash(key))


def epoch_of(run_id: str) -> str:
    """What the boxes see of their run. Never the run id itself: that is the browser's key."""
    return sha256(("epoch:" + run_id).encode()).hexdigest()[:16]


class PreviewStore:
    def __init__(
        self,
        path: Path,
        package: MeetPackage,
        *,
        lifetime: timedelta = RUN_LIFETIME,
        max_runs: int = MAX_RUNS,
        max_actions: int = MAX_ACTIONS,
        version: int = 1,
        package_key: str | None = None,
        automation: bool = True,
        packages: Callable[[int], MeetPackage] | None = None,
        copy: EventCopy | None = None,
        max_clients: int = MAX_CLIENTS,
        exit_memory: ExitMemory | None = None,
    ) -> None:
        """Provbanan's runs by default: one per browser for a day, with limits for the shared
        test hub. The hub's own meet uses the same store in a file of its own, with no end
        and no small limits (spec 7: a file per running meet)."""
        self.path = path
        self.package = package
        self.version = version
        # The meet's other versions, for a version switch in the run (DRIFT-29).
        self.packages = packages
        self.lifetime = lifetime
        self.max_runs = max_runs
        self.max_actions = max_actions
        # Boxes, station clients and screens per run: few in Provbanan's runs on the shared
        # test hub, as many as a big meet has in the hub's own.
        self.max_clients = max_clients
        # Earlier meets' answers about the stations' exits, shared by the hub's meets (H26).
        self.exit_memory = exit_memory
        # Which package a run belongs to. A published version brings the checksum it was
        # published with, so a run keeps its package when the contracts gain a field.
        self.package_key = package_key or checksum(package.model_dump(mode="json"))
        # Provbanan's runs per browser have no one ticking the automation, so it starts off.
        self.automation_on = automation
        self.boot = token_hex(16)
        self._ready = False
        self._lock = Lock()
        # The USB copy of the hub's meet (DRIFT-21); Provbanan's runs have none.
        self.copy = copy
        self._local = local()
        # The automation of each run (F14): what it knows of contact lives in memory.
        self._automatik: dict[str, Automatik] = {}

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(_SCHEMA)
                self._ready = True
        # The events saved in this transaction, for the USB copy once they are committed.
        saved: list[tuple[str, list[events.DriftEvent]]] = []
        self._local.saved = saved
        try:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            self._local.saved = None
        if self.copy is not None:
            for run_id, written in saved:
                self.copy.write(epoch_of(run_id), written)

    def _save(
        self,
        db: sqlite3.Connection,
        run_id: str,
        new_events: list[events.DriftEvent],
        *,
        mirror: bool = False,
    ) -> None:
        """The new events, written before Drift answers (DRIFT-21), and then copied to the USB
        stick if one is in. A run this hub follows takes events only from the hub that leads
        it (SYNK-14)."""
        if new_events and not mirror and _mirrored(db, run_id):
            raise Refused(Reason.NOT_LEADER)
        db.executemany(
            "INSERT INTO preview_event VALUES (?, ?, ?)",
            ((run_id, event.seq, event.model_dump_json()) for event in new_events),
        )
        saved = getattr(self._local, "saved", None)
        if new_events and saved is not None:
            saved.append((run_id, list(new_events)))

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
        drift = Drift(self.package, history, now=now, version=self.version, packages=self.packages)
        if row[0] != self.boot and not _mirrored(db, run_id):
            size = len(history)
            drift.pause_after_restart(now)
            self._save(db, run_id, drift.history[size:])
            db.execute("UPDATE preview_run SET boot=? WHERE id=?", (self.boot, run_id))
        return drift

    def start(
        self, traffic_day: Weekday | None = None, game_day: int = 1, *, replace: bool = False
    ) -> str:
        """A new run. With replace (the hub's meet), the runs before it are archived: their
        boxes and clients are let go and must join the new meet with its code (B14)."""
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
            if count >= self.max_runs:
                raise RunLimit()
            run_id = token_hex(24)
            db.execute(
                "INSERT INTO preview_run VALUES (?, ?, ?, ?)",
                (run_id, (now + self.lifetime).timestamp(), self.package_key, self.boot),
            )
            if replace:
                for table in (
                    "preview_box",
                    "station_client",
                    "screen",
                    "preview_join",
                    "driver",
                    "driver_join",
                ):
                    db.execute(f"DELETE FROM {table} WHERE run_id!=?", (run_id,))
            drift = Drift(self.package, [], now=now, version=self.version)
            drift.start(now, traffic_day, game_day)
            if not self.automation_on:
                drift.set_automation(events.AutomationSettings(enabled=False), now)
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
            if size >= self.max_actions:
                raise RunLimit()
            drift.control_clock(control, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def follow_clock(self, run_id: str, seconds: float | None, speed: float, running: bool) -> bool:
        """FastClock as the meet's clock (F12, IMPORT-35); see Drift.follow_clock."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if size >= self.max_actions:
                raise RunLimit()
            written = drift.follow_clock(seconds, speed, running, now)
            self._save(db, run_id, drift.history[size:])
            return written

    def new_day(self, run_id: str, request: events.NewDay) -> Drift:
        """Starta ny dag (F7): the next game day, from Nu."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if size >= self.max_actions:
                raise RunLimit()
            drift.new_day(request, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def set_day(self, run_id: str, settings: events.DaySettings) -> events.DayStatus:
        """Dygnsskiftet by hand or automatic, and its time (F7)."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if settings != drift.day_settings:
                drift.set_day(settings, now)
            self._save(db, run_id, drift.history[size:])
            return drift.day_status(now)

    def make_change(self, run_id: str, request: events.MakeChange) -> Drift:
        """Ny driftändring from Nu (TRAFIK-02, DRIFT-41)."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if size >= self.max_actions:
                raise RunLimit()
            drift.make_change(request, now, f"c{token_hex(5)}")
            self._save(db, run_id, drift.history[size:])
            return drift

    def force_change(self, run_id: str, change_id: str) -> Drift:
        """Tvinga igenom a waiting driftändring (H38)."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            drift.force_change(change_id, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def drop_change(self, run_id: str, change_id: str) -> Drift:
        """Släpp a driftändring: the version that runs is as before it."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            drift.drop_change(change_id, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    # --- Versionsbyte (DRIFT-29) and påbörjat och klart (DRIFT-47) ---------------------------

    def switch(self, run_id: str, request: events.SwitchVersion, included: list[str]) -> Drift:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            drift.switch_version(request, included, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def take_small_correction(self, run_id: str, version: int, included: list[str]) -> bool:
        """Små rättelser (F5, DRIFT-31): a version that only corrects times and tracks of trains
        that have not run is taken at once. True if it was."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            if (
                drift.locked is not None
                or drift.waiting_switch is not None
                or version <= drift.version
                or not drift.small_correction(version)
            ):
                return False
            size = len(drift.history)
            drift.switch_version(events.SwitchVersion(version=version), included, now, small=True)
            self._save(db, run_id, drift.history[size:])
            return True

    def force_switch(self, run_id: str) -> Drift:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            drift.force_switch(now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def call_off_switch(self, run_id: str) -> Drift:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            drift.call_off_switch(now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def unlock(self, run_id: str) -> Drift:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            drift.unlock(now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def phones(self, run_id: str) -> list[events.PlacePhone]:
        """Every place's game number, as changed during the meet (H30)."""
        drift = self.state(run_id)
        return [events.PlacePhone(place=place, phone=drift.phone(place)) for place in drift.stops()]

    def set_phone(self, run_id: str, change: events.PlacePhone) -> list[events.PlacePhone]:
        """Trafikledningen changes a place's number during the meet (TRAFIK-06)."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if size >= self.max_actions:
                raise RunLimit()
            drift.set_phone(change, now)
            self._save(db, run_id, drift.history[size:])
            return [
                events.PlacePhone(place=place, phone=drift.phone(place)) for place in drift.stops()
            ]

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
            if max(size, count) >= self.max_actions:
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
            if count >= self.max_clients:
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

    def automatik(self, run_id: str) -> Automatik:
        if run_id not in self._automatik:
            self._automatik[run_id] = Automatik()
        return self._automatik[run_id]

    def _heard(
        self, run_id: str, drift: Drift, client: str, place: str | None, now: datetime
    ) -> None:
        """A box or TKL at work: in contact now, and the first one at a place mans it."""
        if place is None:
            return
        self.automatik(run_id).observe(client, place)
        drift.man(place, client, now)

    def _with_boxes(
        self,
        db: sqlite3.Connection,
        run_id: str,
        operation: Callable[[Boxes], T],
        heard: str | None = None,
    ) -> T:
        now = now_utc()
        drift = self._load(db, run_id, now)
        size = len(drift.history)
        stored = self._boxes(db, run_id)
        boxes = Boxes(
            drift, {cid: box for cid, (box, _) in stored.items()}, epoch=epoch_of(run_id), now=now
        )
        boxes.catch_up()
        if heard is not None and heard in boxes.boxes:
            self._heard(run_id, drift, heard, boxes.boxes[heard].place, now)
        result = operation(boxes)
        self._save(db, run_id, drift.history[size:])
        for client_id, place, key, message in boxes.refusals:
            self._refused(db, run_id, drift, client_id, place, f"knapp {key}", None, message)
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
            return self._with_boxes(
                db, run_id, lambda b: b.frame(b.boxes[client_id]), heard=client_id
            )

    def box_press(self, key: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as db:
            client_id, run_id = self._box_run(db, key)
            size = db.execute(
                "SELECT count(*) FROM preview_event WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if size >= self.max_actions:
                raise RunLimit()
            return self._with_boxes(
                db, run_id, lambda b: b.press(b.boxes[client_id], body), heard=client_id
            )

    # --- Physical boxes over MQTT (BOX-10, DRIFT-22): no code and no key, as today ------------

    @staticmethod
    def _device_hash(run_id: str, device: str) -> str:
        """Where a physical box is found in a run. Not a secret: physical boxes are accepted
        without a key (BOX-10); the hash only keeps the table's one-key-per-box rule."""
        return _key_hash(f"mqtt:{run_id}:{device}")

    def _device_box(self, db: sqlite3.Connection, run_id: str, device: str) -> str | None:
        row = db.execute(
            "SELECT client_id FROM preview_box WHERE key_hash=? AND run_id=?",
            (self._device_hash(run_id, device), run_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def device_hello(
        self, run_id: str, device: str, name: str, display: DisplaySize | None = None
    ) -> dict[str, Any]:
        """A physical box said hello: it is under Väntar in the run, or already has its place.
        Returns its frame. A box keeps its place over a reconnect; the size it announces now
        counts."""
        now = now_utc()
        size = display or DisplaySize()
        with self._transaction() as db:
            drift = self._load(db, run_id, now)
            client_id = self._device_box(db, run_id, device)
            if client_id is None:
                count = db.execute(
                    "SELECT count(*) FROM preview_box WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                if count >= self.max_clients:
                    raise RunLimit()
                client_id = "tmbox-" + token_hex(6)
                box = Box(
                    client_id=client_id,
                    name=name,
                    kind="tmbox",
                    seen=len(drift.history),
                    language=COUNTRY_LANGUAGE.get(drift.package.meet.country, "sv"),
                    rows=size.rows,
                    cols=size.cols,
                )
                db.execute(
                    "INSERT INTO preview_box VALUES (?, ?, ?, ?, ?)",
                    (
                        client_id,
                        run_id,
                        self._device_hash(run_id, device),
                        now.timestamp(),
                        box.to_json(),
                    ),
                )

            def resize(boxes: Boxes) -> dict[str, Any]:
                box = boxes.boxes[client_id]
                box.name, box.rows, box.cols = name, size.rows, size.cols
                return boxes.frame(box)

            return self._with_boxes(db, run_id, resize, heard=client_id)

    def device_frames(
        self, run_id: str, devices: Iterable[str], heard: Iterable[str] = ()
    ) -> dict[str, dict[str, Any]]:
        """The frames of the physical boxes asked for, in one go: a box not in the run is left
        out, so it says hello again. The boxes heard from since last time are in contact."""
        wanted = list(devices)
        recent = set(heard)
        with self._transaction() as db:
            ids = {device: self._device_box(db, run_id, device) for device in wanted}
            known = {device: cid for device, cid in ids.items() if cid is not None}

            def frames(boxes: Boxes) -> dict[str, dict[str, Any]]:
                for device in recent & known.keys():
                    box = boxes.boxes[known[device]]
                    self._heard(run_id, boxes.drift, box.client_id, box.place, boxes.now)
                return {device: boxes.frame(boxes.boxes[cid]) for device, cid in known.items()}

            return self._with_boxes(db, run_id, frames) if known else {}

    def device_press(self, run_id: str, device: str, body: dict[str, Any]) -> dict[str, Any]:
        """A key press from a physical box, answered as the Ack contract."""
        with self._transaction() as db:
            client_id = self._device_box(db, run_id, device)
            if client_id is None:
                raise UnknownBox()
            size = db.execute(
                "SELECT count(*) FROM preview_event WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if size >= self.max_actions:
                raise RunLimit()
            return self._with_boxes(
                db, run_id, lambda b: b.press(b.boxes[client_id], body), heard=client_id
            )

    def clients(self, run_id: str) -> list[dict[str, Any]]:
        """The boxes and station clients of the run, waiting ones first, as the Client
        contract says."""
        with self._transaction() as db:
            boxes = self._with_boxes(db, run_id, lambda b: list(b.boxes.values()))
            others = self._station_clients(db, run_id) + self._screens(db, run_id)
        listed = [
            {
                "client_id": box.client_id,
                "name": box.name,
                "kind": box.kind,
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

    def connect(
        self, request: station.ConnectRequest, *, here: bool = False
    ) -> station.ConnectReply:
        """A client says what it is; it waits under Väntar until the dispatcher approves it
        (H31). Over the internet it finds the run with the run's code; on the meet's network
        (here) it joins the meet that runs, with no code (H23, KLAR-13)."""
        meet = self.current() if here and not request.code else None
        with self._transaction() as db:
            run_id = meet or self._run_by_code(db, request.code or "")
            count = db.execute(
                "SELECT count(*) FROM station_client WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if count >= self.max_clients:
                raise RunLimit()
            client_id = f"{request.kind.value}-{token_hex(6)}"
            stored = request.model_copy(update={"code": None})
            if not stored.wants:
                stored = stored.model_copy(update={"wants": self._place_of(stored)})
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
        drift: Drift | None = None
        for client_id, request, status, places in db.execute(
            "SELECT client_id, request, status, places FROM station_client WHERE run_id=? "
            "ORDER BY created, client_id",
            (run_id,),
        ).fetchall():
            asked = station.ConnectRequest.model_validate_json(request)
            approved = list(json.loads(places))
            questions: list[dict[str, Any]] = []
            if status == station.ApprovalStatus.APPROVED.value and approved:
                drift = drift or self._load(db, run_id, now_utc())
                for place in approved:
                    _, asking = self._coupling(db, run_id, drift, asked, place)
                    questions += [q.model_dump(mode="json") for q in asking]
            outside = self._outside(asked, approved[0] if approved else None)
            listed.append(
                {
                    "client_id": client_id,
                    "name": asked.name,
                    "kind": asked.kind.value,
                    "status": status,
                    "places": approved or asked.wants,
                    "side": "both",
                    "station_id": outside.station_id if outside else asked.station_id,
                    "questions": questions,
                }
            )
        return listed

    # --- Stationens utfarter (H26, PLAN-31, TRAFIK-05) -----------------------------------

    def _place_of(self, request: station.ConnectRequest) -> list[str]:
        """The place a TKL most likely wants, so that Klienter suggests it: the one the station
        is coupled to in advance, or the one with the station's name (H25)."""
        stops = [p for p in self.package.places if p.kind != PlaceKind.HALT]
        station_id = request.outside.station_id if request.outside else request.station_id
        coupled = [p.id for p in stops if p.station and p.station.station_id == station_id]
        if coupled:
            return coupled[:1]
        if request.outside is None:
            return []
        name = request.outside.name.casefold()
        named = [p.id for p in stops if name in (p.name.casefold(), p.code.casefold())]
        return named[:1]

    def _outside(self, request: station.ConnectRequest, place: str | None) -> StationOutside | None:
        """The station's outside at the place: pinned in the version when the planner coupled
        it in advance, else the one the TKL brought when it connected (KLAR-12)."""
        found = next((p for p in self.package.places if p.id == place), None)
        if found is not None and found.station is not None:
            wanted = request.outside.station_id if request.outside else request.station_id
            if wanted in (None, found.station.station_id):
                return found.station.outside
        return request.outside

    def _coupling(
        self,
        db: sqlite3.Connection,
        run_id: str,
        drift: Drift,
        request: station.ConnectRequest,
        place: str,
    ) -> tuple[dict[str, str], list[station.ExitQuestion]]:
        outside = self._outside(request, place)
        if outside is None:
            return {}, []
        seen = snapshot(drift, place, now_utc())
        found = next((p for p in self.package.places if p.id == place), None)
        pinned = (
            found.station.exit_map
            if found is not None
            and found.station is not None
            and found.station.station_id == outside.station_id
            else {}
        )
        answered = {
            str(section): str(exit_id)
            for section, exit_id in db.execute(
                "SELECT section, exit FROM station_exit WHERE run_id=? AND station_id=?",
                (run_id, outside.station_id),
            )
        }
        remembered = self.exit_memory.remembered(outside.station_id) if self.exit_memory else {}
        return couple(
            outside,
            place,
            seen.sections,
            {n.place: n for n in seen.all_places},
            pinned=pinned,
            answered=answered,
            remembered=remembered,
        )

    def _dressed(
        self,
        db: sqlite3.Connection,
        run_id: str,
        drift: Drift,
        client_id: str,
        seen: station.Snapshot,
    ) -> station.Snapshot:
        """The snapshot with the place's Spår-vy, the station's exits and Hubbens questions
        about them."""
        seen = seen.model_copy(
            update={"track_display": self._track_display(db, run_id, drift, seen)[0]}
        )
        row = db.execute(
            "SELECT request FROM station_client WHERE client_id=?", (client_id,)
        ).fetchone()
        if row is None:
            return seen
        request = station.ConnectRequest.model_validate_json(row[0])
        found, questions = self._coupling(db, run_id, drift, request, seen.place.place)
        # The drivers' messages go to the clearers with TKL, not to the TMBox (DRIFT-38).
        told = (
            messages_here(drift, seen.place.place, now_utc())
            if request.kind == station.ClientKind.TKL
            else []
        )
        return seen.model_copy(
            update={
                "sections": [
                    s.model_copy(update={"exit": found.get(s.section)}) for s in seen.sections
                ],
                "questions": questions,
                "driver_messages": told,
            }
        )

    def _answer_exit(
        self,
        db: sqlite3.Connection,
        run_id: str,
        drift: Drift,
        request: station.ConnectRequest,
        places: list[str],
        answer: station.ExitAnswer,
    ) -> str:
        """The first answer stands (TRAFIK-05). The same answer again changes nothing; it is
        remembered for the next meet with the same neighbour. Returns the section's place."""
        for place in places:
            outside = self._outside(request, place)
            seen = snapshot(drift, place, now_utc())
            here = next((s for s in seen.sections if s.section == answer.section), None)
            if outside is None or here is None:
                continue
            if answer.exit not in {e.id for e in outside.exits}:
                raise UnknownExit()
            before = db.execute(
                "SELECT exit FROM station_exit WHERE run_id=? AND station_id=? AND section=?",
                (run_id, outside.station_id, answer.section),
            ).fetchone()
            if before is not None:
                if before[0] != answer.exit:
                    raise ExitAnswered(str(before[0]))
                return place
            db.execute(
                "INSERT INTO station_exit VALUES (?, ?, ?, ?)",
                (run_id, outside.station_id, answer.section, answer.exit),
            )
            if self.exit_memory is not None:
                other = next((n for n in seen.all_places if n.place == here.other_place), None)
                self.exit_memory.remember(
                    outside.station_id, other.name if other else here.other_code, answer.exit
                )
            return place
        raise UnknownExit()

    # --- Spår-vyn (BOXIOS-16, H65) ----------------------------------------------------------

    def _track_display(
        self, db: sqlite3.Connection, run_id: str, drift: Drift, seen: station.Snapshot
    ) -> tuple[station.TrackDisplay, list[str]]:
        """The place's tracks as the station shows them, and the plan's own order."""
        here = next(p for p in drift.package.places if p.id == seen.place.place)
        base = base_order(here, [c.planned_track or "" for c in seen.calls])
        row = db.execute(
            "SELECT revision, body FROM track_display WHERE run_id=? AND place=?",
            (run_id, here.id),
        ).fetchone()
        revision, saved = (
            (int(row[0]), json.loads(row[1]) if row[1] else None) if row else (0, None)
        )
        return shown(base, revision, saved), base

    def station_track_display(
        self, key: str, place: str, change: station.TrackDisplayChange
    ) -> station.Snapshot:
        """An app at the place saves the Spår-vy, or goes back to the meet's order. Only
        presentation: nothing in the traffic changes, and no drift event is written."""
        with self._transaction() as db:
            client_id, run_id, places = self._approved(db, key)
            if place not in places:
                raise NotApproved()
            now = now_utc()
            drift = self._load(db, run_id, now)
            seen = snapshot(drift, place, now)
            current, base = self._track_display(db, run_id, drift, seen)
            saved = checked(base, current.revision, change)
            db.execute(
                "INSERT OR REPLACE INTO track_display VALUES (?, ?, ?, ?)",
                (run_id, place, current.revision + 1, json.dumps(saved) if saved else None),
            )
            return self._dressed(db, run_id, drift, client_id, seen)

    def station_exit(self, key: str, place: str, answer: station.ExitAnswer) -> station.Snapshot:
        """TKL answers which exit a section has (H26), with its key."""
        with self._transaction() as db:
            client_id, run_id, places = self._approved(db, key)
            if place not in places:
                raise NotApproved()
            row = db.execute(
                "SELECT request FROM station_client WHERE client_id=?", (client_id,)
            ).fetchone()
            request = station.ConnectRequest.model_validate_json(row[0])
            now = now_utc()
            drift = self._load(db, run_id, now)
            self._answer_exit(db, run_id, drift, request, [place], answer)
            return self._dressed(db, run_id, drift, client_id, snapshot(drift, place, now))

    def couple_exit(self, run_id: str, change: events.CoupleExit) -> list[dict[str, Any]]:
        """The dispatcher answers in Klienter (TRAFIK-05)."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT request, places FROM station_client WHERE client_id=? AND run_id=?",
                (change.client_id, run_id),
            ).fetchone()
            if row is None:
                raise UnknownClient()
            request = station.ConnectRequest.model_validate_json(row[0])
            drift = self._load(db, run_id, now_utc())
            self._answer_exit(
                db,
                run_id,
                drift,
                request,
                list(json.loads(row[1])),
                station.ExitAnswer(section=change.section, exit=change.exit),
            )
        return self.clients(run_id)

    def _approved(self, db: sqlite3.Connection, key: str) -> tuple[str, str, list[str]]:
        row = db.execute(
            "SELECT c.client_id, c.run_id, c.places FROM station_client c "
            "JOIN preview_run r ON r.id=c.run_id "
            "WHERE c.key_hash=? AND c.status=? AND r.expires>?",
            (
                str(key) if isinstance(key, KeyHash) else _key_hash(key),
                station.ApprovalStatus.APPROVED.value,
                now_utc().timestamp(),
            ),
        ).fetchone()
        if row is None:
            raise UnknownClient()
        return str(row[0]), str(row[1]), list(json.loads(row[2]))

    # --- Push (F20, SYNK-05) ----------------------------------------------------------------

    def set_push(self, key: str, token: station.PushToken | None) -> None:
        """The phone's address for push, from the approved client; None stops it."""
        with self._transaction() as db:
            client_id, _, _ = self._approved(db, key)
            if token is None:
                db.execute("DELETE FROM station_push WHERE client_id=?", (client_id,))
            else:
                db.execute(
                    "INSERT OR REPLACE INTO station_push VALUES (?, ?)",
                    (client_id, token.model_dump_json()),
                )

    def push_targets(self, run_id: str) -> list[tuple[station.PushToken, list[str]]]:
        """The approved clients that want push, and the places each is approved for."""
        with self._transaction() as db:
            rows = db.execute(
                "SELECT p.token, c.places FROM station_push p "
                "JOIN station_client c ON c.client_id=p.client_id "
                "WHERE c.run_id=? AND c.status=?",
                (run_id, station.ApprovalStatus.APPROVED.value),
            ).fetchall()
        return [
            (station.PushToken.model_validate_json(token), list(json.loads(places)))
            for token, places in rows
        ]

    def notices(self, run_id: str, after: int) -> tuple[int, list[station.Notice]]:
        """The run's last seq, and the notices of the events after seq (F20)."""
        with self._transaction() as db:
            drift = self._load(db, run_id, now_utc())
        last = drift.history[-1].seq if drift.history else 0
        return last, notices(drift, after)

    def place_snapshot(self, key: str, place: str) -> station.Snapshot:
        with self._transaction() as db:
            client_id, run_id, places = self._approved(db, key)
            if place not in places:
                raise NotApproved()
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            self._heard(run_id, drift, client_id, place, now)
            self._save(db, run_id, drift.history[size:])
            return self._dressed(db, run_id, drift, client_id, snapshot(drift, place, now))

    def place_revision(self, key: str, place: str) -> int:
        """For the event stream: the number that moves when the place's snapshot changes."""
        with self._transaction() as db:
            client_id, run_id, places = self._approved(db, key)
            if place not in places:
                raise NotApproved()
            drift = self._load(db, run_id, now_utc())
            self.automatik(run_id).observe(client_id, place)
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
            heard = len(drift.history)
            self._heard(run_id, drift, client_id, command.place, now)
            self._save(db, run_id, drift.history[heard:])
            if earlier is not None:
                if earlier[0] != signature:
                    raise NotApproved()  # One message id, one command.
                first = json.loads(earlier[1])
                status = (
                    station.ReplyStatus.DUPLICATE
                    if first["status"] == station.ReplyStatus.ACCEPTED
                    else station.ReplyStatus(first["status"])
                )
                seen = self._dressed(
                    db, run_id, drift, client_id, snapshot(drift, command.place, now)
                )
                return station.Reply.model_validate(
                    {**first, "status": status, "snapshot": seen.model_dump(mode="json")}
                )
            if (
                db.execute(
                    "SELECT count(*) FROM station_reply WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                >= self.max_actions
                or len(drift.history) >= self.max_actions
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
            if reason is not None:
                self._refused(
                    db,
                    run_id,
                    drift,
                    client_id,
                    command.place,
                    command.action.value,
                    reason.value,
                    TEXT_SV[reason],
                )
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
            seen = self._dressed(db, run_id, drift, client_id, snapshot(drift, command.place, now))
            return station.Reply.model_validate(
                {**answer, "snapshot": seen.model_dump(mode="json")}
            )

    # --- The automation (F14) -------------------------------------------------------------

    def tick(self, run_id: str) -> None:
        """One round every second or so while the hub runs: the reminders of unanswered
        requests (H39), the automatic day change (F7) and the automation (F14). Nothing
        happens while the clock stands, nor in a run another hub leads."""
        with self._transaction() as db:
            if _mirrored(db, run_id):
                return
            now = now_utc()
            drift = self._load(db, run_id, now)
            if not drift.clock.running or drift.locked is not None:
                return
            size = len(drift.history)
            if size >= self.max_actions:
                raise RunLimit()
            drift.remind(now)
            drift.day_tick(now)
            if drift.automation.enabled:
                self.automatik(run_id).tick(drift, now)
            self._save(db, run_id, drift.history[size:])

    def automation(self, run_id: str) -> events.AutomationStatus:
        with self._transaction() as db:
            drift = self._load(db, run_id, now_utc())
            return self.automatik(run_id).status(drift)

    def set_automation(
        self, run_id: str, settings: events.AutomationSettings
    ) -> events.AutomationStatus:
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if settings != drift.automation:
                drift.set_automation(settings, now)
            self._save(db, run_id, drift.history[size:])
            return self.automatik(run_id).status(drift)

    def automation_place(
        self, run_id: str, change: events.AutomationPlace
    ) -> events.AutomationStatus:
        """Trafikledningen leaves a place to the automation, or gives it back to a box or
        TKL in contact there (the one heard last, unless one is named)."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            automatik = self.automatik(run_id)
            size = len(drift.history)
            if change.action == "leave":
                drift.leave(change.place, events.LeftBy.DISPATCHER, now)
            else:
                present = automatik.present(change.place)
                client = change.client_id or (present[0] if present else None)
                if client is None or client not in present:
                    raise Refused(Reason.CLIENT_NOT_PRESENT)
                drift.take_back(change.place, client, "dispatcher", now)
            self._save(db, run_id, drift.history[size:])
            return automatik.status(drift)

    # --- The hub's own meet ---------------------------------------------------------------

    def current(self) -> str:
        """The meet that runs: the one started last. Older ones stay, archived (T11)."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT id FROM preview_run WHERE expires>? AND package=? "
                "ORDER BY expires DESC LIMIT 1",
                (now_utc().timestamp(), self.package_key),
            ).fetchone()
        if row is None:
            raise MissingRun()
        return str(row[0])

    # --- Följa en annan hubb (SYNK-04, SYNK-14) ------------------------------------------------

    def receive(
        self, run_id: str, leader: str, new_events: list[events.DriftEvent]
    ) -> tuple[int, list[events.DriftEvent]]:
        """The events of a run another hub leads, in order (SYNK-10): kept as they came, after
        the last one here. One already here is passed over; after a gap nothing more is
        taken, so the leader sends again from the answer. The last seq kept, and the events
        taken now."""
        now = now_utc()
        with self._transaction() as db:
            row = db.execute("SELECT package FROM preview_run WHERE id=?", (run_id,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO preview_run VALUES (?, ?, ?, ?)",
                    (run_id, (now + self.lifetime).timestamp(), self.package_key, self.boot),
                )
                db.execute(
                    "INSERT INTO mirror_run VALUES (?, ?, ?)", (run_id, leader, now.timestamp())
                )
            elif row[0] != self.package_key:
                raise Refused(Reason.NOT_LEADER)
            elif not _mirrored(db, run_id):
                raise Refused(Reason.ALREADY_LEADER)  # this hub took over (H9)
            (last,) = db.execute(
                "SELECT coalesce(max(seq), 0) FROM preview_event WHERE run_id=?", (run_id,)
            ).fetchone()
            taken = []
            for event in sorted(new_events, key=lambda e: e.seq):
                if event.seq <= last:
                    continue
                if event.seq != last + 1:
                    break
                taken.append(event)
                last = event.seq
            self._save(db, run_id, taken, mirror=True)
            db.execute(
                "UPDATE mirror_run SET leader=?, heard=? WHERE run_id=?",
                (leader, now.timestamp(), run_id),
            )
            return int(last), taken

    def take_over(self, run_id: str, hub_name: str) -> Drift:
        """Ta över i molnet (H8, H9): the run this hub followed is led from here, with an epoch
        one higher. Done in one write, so it is either done or not at all (DRIFT-47)."""
        now = now_utc()
        with self._transaction() as db:
            if not _mirrored(db, run_id):
                raise Refused(Reason.ALREADY_LEADER)
            drift = self._load(db, run_id, now)
            db.execute("DELETE FROM mirror_run WHERE run_id=?", (run_id,))
            size = len(drift.history)
            drift.take_over(hub_name, now)
            self._save(db, run_id, drift.history[size:])
            return drift

    def give_way(self, run_id: str, leader: str, theirs: list[events.DriftEvent]) -> int:
        """Another hub took over the run this hub led (SYNK-14): this hub follows from here.
        Its own events after the point where the two part are set aside, kept and never
        applied, and the leader's events take their place. How many were set aside."""
        now = now_utc()
        with self._transaction() as db:
            mine = {
                int(seq): str(body)
                for seq, body in db.execute(
                    "SELECT seq, body FROM preview_event WHERE run_id=?", (run_id,)
                )
            }
            fork = 0
            for event in sorted(theirs, key=lambda e: e.seq):
                here = mine.get(event.seq)
                if here is None or events.DriftEvent.model_validate_json(here) != event:
                    break
                fork = event.seq
            aside = [(seq, body) for seq, body in sorted(mine.items()) if seq > fork]
            db.executemany(
                "INSERT OR REPLACE INTO forked_event VALUES (?, ?, ?, ?)",
                ((run_id, seq, body, now.timestamp()) for seq, body in aside),
            )
            db.execute("DELETE FROM preview_event WHERE run_id=? AND seq>?", (run_id, fork))
            db.execute(
                "INSERT OR REPLACE INTO mirror_run VALUES (?, ?, ?)",
                (run_id, leader, now.timestamp()),
            )
            taken = [e for e in sorted(theirs, key=lambda e: e.seq) if e.seq > fork]
            expected = fork + 1
            kept = []
            for event in taken:
                if event.seq != expected:
                    break
                kept.append(event)
                expected += 1
            self._save(db, run_id, kept, mirror=True)
            return len(aside)

    def set_aside(self, run_id: str) -> int:
        """Events this hub made after another took over, kept but never applied."""
        with self._transaction() as db:
            (count,) = db.execute(
                "SELECT count(*) FROM forked_event WHERE run_id=?", (run_id,)
            ).fetchone()
        return int(count)

    def leader(self, run_id: str) -> tuple[str, datetime] | None:
        """The hub that leads the run, and when it was last heard; None if this hub leads."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT leader, heard FROM mirror_run WHERE run_id=?", (run_id,)
            ).fetchone()
        return None if row is None else (str(row[0]), datetime.fromtimestamp(row[1], UTC))

    def events_after(self, run_id: str, seq: int) -> list[events.DriftEvent]:
        """The run's events after seq, read as they are stored: no replay, so a stream can ask
        often even for a big meet."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT 1 FROM preview_run WHERE id=? AND expires>? AND package=?",
                (run_id, now_utc().timestamp(), self.package_key),
            ).fetchone()
            if row is None:
                raise MissingRun()
            return [
                events.DriftEvent.model_validate_json(body)
                for (body,) in db.execute(
                    "SELECT body FROM preview_event WHERE run_id=? AND seq>? ORDER BY seq",
                    (run_id, seq),
                )
            ]

    def log(
        self, run_id: str, place: str | None = None, train: str | None = None
    ) -> list[events.DriftEvent]:
        """The Drift events of the run, newest first, for one place or train if asked."""
        drift = self.state(run_id)
        found = [
            event
            for event in drift.history
            if (place is None or event.place == place or self._touches(drift, event, place))
            and (train is None or event.train == train or self._numbered(drift, event, train))
        ]
        return list(reversed(found))

    @staticmethod
    def _touches(drift: Drift, event: events.DriftEvent, place: str) -> bool:
        if event.call is None:
            return False
        leg = drift.legs.get(event.call) or drift.by_arrival.get(event.call)
        return leg is not None and place in {leg.departure.place, leg.arrival.place}

    @staticmethod
    def _numbered(drift: Drift, event: events.DriftEvent, number: str) -> bool:
        found = drift.calls.get(event.call or "")
        return found is not None and found[0].number == number

    # --- Refused commands, for Logg (B15) -------------------------------------------------

    @staticmethod
    def _refused(
        db: sqlite3.Connection,
        run_id: str,
        drift: Drift,
        client_id: str,
        place: str | None,
        what: str,
        reason: str | None,
        message: str,
    ) -> None:
        """What a client was told no, and why. Kept beside the events, never as one."""
        now = now_utc()
        db.execute(
            "INSERT INTO drift_refusal VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                now.timestamp(),
                model_time(drift.clock.at(now)),
                client_id,
                place,
                what,
                reason,
                message,
            ),
        )
        db.execute(
            "DELETE FROM drift_refusal WHERE run_id=? AND rowid NOT IN (SELECT rowid FROM "
            "drift_refusal WHERE run_id=? ORDER BY at DESC LIMIT ?)",
            (run_id, run_id, MAX_REFUSALS),
        )

    def refusals(self, run_id: str) -> list[events.Refusal]:
        with self._transaction() as db:
            rows = db.execute(
                "SELECT at, model_time, client_id, place, what, reason, message "
                "FROM drift_refusal WHERE run_id=? ORDER BY at DESC",
                (run_id,),
            ).fetchall()
        return [
            events.Refusal(
                wall_time=datetime.fromtimestamp(at, UTC),
                model_time=model,
                client_id=client,
                place=place,
                what=what,
                reason=reason,
                message=message,
            )
            for at, model, client, place, what, reason, message in rows
        ]

    # --- Lokföraren (LOK-01, LOK-16, LOK-40, LOK-41): the drivers of a run ---------------------

    def driver_code(self, run_id: str) -> str:
        """The drivers' code for the meet's QR code, made the first time it is asked for."""
        with self._transaction() as db:
            self._load(db, run_id, now_utc())
            row = db.execute("SELECT code FROM driver_join WHERE run_id=?", (run_id,)).fetchone()
            if row is not None:
                return str(row[0])
            while True:
                code = f"{randbelow(10**6):06d}"
                taken = db.execute("SELECT 1 FROM driver_join WHERE code=?", (code,)).fetchone()
                if taken is None:
                    db.execute("INSERT INTO driver_join VALUES (?, ?)", (run_id, code))
                    return code

    def driver_run(self, code: str) -> str:
        """The live run whose drivers' code it is."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT j.run_id FROM driver_join j JOIN preview_run r ON r.id=j.run_id "
                "WHERE j.code=? AND r.expires>? AND r.package=?",
                (code, now_utc().timestamp(), self.package_key),
            ).fetchone()
        if row is None:
            raise MissingRun()
        return str(row[0])

    def join_driver(
        self, run_id: str, name: str, level: DriverLevel, person: str | None = None
    ) -> tuple[DriverRecord, str]:
        """A new driver in the run, and the phone's key, shown once. The driver stays as long
        as the run does (LOK-41); a new meet needs a new join (B14)."""
        with self._transaction() as db:
            self._load(db, run_id, now_utc())
            count = db.execute("SELECT count(*) FROM driver WHERE run_id=?", (run_id,)).fetchone()
            if count[0] >= MAX_DRIVERS:
                raise RunLimit()
            driver_id = f"forare-{token_hex(6)}"
            key = token_urlsafe(32)
            db.execute(
                "INSERT INTO driver (driver_id, run_id, key_hash, created, name, level, person) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    driver_id,
                    run_id,
                    _key_hash(key),
                    now_utc().timestamp(),
                    " ".join(name.split()),
                    level.value,
                    person,
                ),
            )
            return self._driver(db, run_id, driver_id), key

    _DRIVER_COLUMNS: Final = (
        "driver_id, run_id, name, level, state, person, photo_type, photo_version, created"
    )

    @staticmethod
    def _driver_of(row: tuple[Any, ...]) -> DriverRecord:
        return DriverRecord(
            id=str(row[0]),
            run_id=str(row[1]),
            name=str(row[2]),
            level=DriverLevel(row[3]),
            state=row[4],
            person=row[5],
            photo_type=row[6],
            photo_version=int(row[7]),
            joined=datetime.fromtimestamp(row[8], UTC),
        )

    def _driver(self, db: sqlite3.Connection, run_id: str, driver_id: str) -> DriverRecord:
        row = db.execute(
            f"SELECT {self._DRIVER_COLUMNS} FROM driver WHERE driver_id=? AND run_id=?",
            (driver_id, run_id),
        ).fetchone()
        if row is None:
            raise UnknownDriver()
        return self._driver_of(row)

    def driver_by_key(self, key: str) -> DriverRecord:
        """The driver whose phone has the key, in a live run of this store."""
        if not key or len(key) > 120:
            raise UnknownDriver()
        with self._transaction() as db:
            row = db.execute(
                f"SELECT {', '.join('d.' + c.strip() for c in self._DRIVER_COLUMNS.split(','))} "
                "FROM driver d JOIN preview_run r ON r.id=d.run_id "
                "WHERE d.key_hash=? AND r.expires>? AND r.package=?",
                (_key_hash(key), now_utc().timestamp(), self.package_key),
            ).fetchone()
        if row is None:
            raise UnknownDriver()
        return self._driver_of(row)

    def driver(self, run_id: str, driver_id: str) -> DriverRecord:
        with self._transaction() as db:
            return self._driver(db, run_id, driver_id)

    def drivers(self, run_id: str) -> list[DriverRecord]:
        """The run's drivers, in the order they came."""
        with self._transaction() as db:
            rows = db.execute(
                f"SELECT {self._DRIVER_COLUMNS} FROM driver WHERE run_id=? "
                "ORDER BY created, driver_id",
                (run_id,),
            ).fetchall()
        return [self._driver_of(row) for row in rows]

    def change_driver(
        self,
        run_id: str,
        driver_id: str,
        *,
        name: str | None = None,
        level: DriverLevel | None = None,
        state: str | None = None,
        clear_state: bool = False,
        person: str | None = None,
    ) -> DriverRecord:
        """The driver's own name, level and Paus or Inväntar start (LOK-27), and the person in
        TrainMeet ID once the driver has logged in there (LOK-16)."""
        with self._transaction() as db:
            found = self._driver(db, run_id, driver_id)
            db.execute(
                "UPDATE driver SET name=?, level=?, state=?, person=? WHERE driver_id=?",
                (
                    " ".join(name.split()) if name else found.name,
                    (level or found.level).value,
                    None if clear_state else (state or found.state),
                    person or found.person,
                    driver_id,
                ),
            )
            return self._driver(db, run_id, driver_id)

    def set_driver_photo(
        self, run_id: str, driver_id: str, photo: tuple[bytes, str] | None
    ) -> DriverRecord:
        """The driver's photo icon, already checked to be a small picture; None takes it away."""
        with self._transaction() as db:
            self._driver(db, run_id, driver_id)
            data, kind = photo if photo is not None else (None, None)
            db.execute(
                "UPDATE driver SET photo=?, photo_type=?, photo_version=photo_version+1 "
                "WHERE driver_id=?",
                (data, kind, driver_id),
            )
            return self._driver(db, run_id, driver_id)

    def remove_driver(self, run_id: str, driver_id: str) -> None:
        """The driver leaves the meet: the name, the photo and the key's hash go. What the
        driver did stays in Drift's events, by the driver's id only."""
        with self._transaction() as db:
            self._driver(db, run_id, driver_id)
            db.execute("DELETE FROM driver WHERE driver_id=? AND run_id=?", (driver_id, run_id))

    def driver_photo(self, run_id: str, driver_id: str) -> tuple[bytes, str] | None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT photo, photo_type FROM driver "
                "WHERE driver_id=? AND run_id=? AND photo IS NOT NULL",
                (driver_id, run_id),
            ).fetchone()
        return None if row is None else (bytes(row[0]), str(row[1]))

    def drive(self, run_id: str, action: Callable[[Drift, datetime], T]) -> tuple[Drift, T]:
        """Something a driver, Trafikledningen or the lokledare does about the drivers: the
        action gets Drift and the time, and its events are written before the answer."""
        with self._transaction() as db:
            now = now_utc()
            drift = self._load(db, run_id, now)
            size = len(drift.history)
            if size >= self.max_actions:
                raise RunLimit()
            result = action(drift, now)
            self._save(db, run_id, drift.history[size:])
            return drift, result

    # --- The meet's screens (S3, S4) ------------------------------------------------------

    def screen_login(self, name: str, code: str) -> tuple[str, str]:
        """A screen joins with the run's code and waits under Väntar for a view."""
        with self._transaction() as db:
            run_id = self._run_by_code(db, code)
            count = db.execute("SELECT count(*) FROM screen WHERE run_id=?", (run_id,)).fetchone()[
                0
            ]
            if count >= self.max_clients:
                raise RunLimit()
            client_id, key = "screen-" + token_hex(6), token_urlsafe(32)
            db.execute(
                "INSERT INTO screen VALUES (?, ?, ?, ?, ?, NULL)",
                (client_id, run_id, _key_hash(key), now_utc().timestamp(), " ".join(name.split())),
            )
        return client_id, key

    def _screens(self, db: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "client_id": client_id,
                "name": name,
                "kind": "screen",
                "status": "approved" if view else "waiting",
                "places": [],
                "side": "both",
                "view": view,
            }
            for client_id, name, view in db.execute(
                "SELECT client_id, name, view FROM screen WHERE run_id=? ORDER BY created",
                (run_id,),
            )
        ]

    def show_view(self, run_id: str, client_id: str, view: str | None) -> list[dict[str, Any]]:
        with self._transaction() as db:
            changed = db.execute(
                "UPDATE screen SET view=? WHERE client_id=? AND run_id=?", (view, client_id, run_id)
            ).rowcount
            if not changed:
                raise UnknownClient()
        return self.clients(run_id)

    def screen_picture(self, key: str) -> tuple[str, str | None, Drift]:
        """The screen's name, its view and the run it shows."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT s.name, s.view, s.run_id FROM screen s JOIN preview_run r ON r.id=s.run_id "
                "WHERE s.key_hash=? AND r.expires>?",
                (_key_hash(key), now_utc().timestamp()),
            ).fetchone()
            if row is None:
                raise UnknownClient()
            return str(row[0]), row[1], self._load(db, str(row[2]), now_utc())


def _mirrored(db: sqlite3.Connection, run_id: str) -> bool:
    return db.execute("SELECT 1 FROM mirror_run WHERE run_id=?", (run_id,)).fetchone() is not None
