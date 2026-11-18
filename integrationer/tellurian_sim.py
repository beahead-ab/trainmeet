"""A pretend Tellurian Dispatch server for tests and the test environment (IMPORT-34).

Ported from the old Server's tellurian_sim.py, read side only: the dispatchers and their
arrivals and departures, as Tellurian's SPECIFICATION.md describes them under /api/v1. It runs
no Tellurian code and has no actions, state machine or event stream: a test sets the sections
each dispatcher shows. It binds only to 127.0.0.1, and every answer carries the header
X-Tellurian-Simulator, so that what it shows is never taken for Tellurian itself.

    GET /api/v1/dispatchers         [{id, signature, name, href}]
    GET /api/v1/dispatchers/{id}    {id, signature, stationName, preferredLanguage,
                                     arrivals, departures}

Faults are injected only from Python (fail_next_read), never over HTTP. Any other method than
GET is recorded and refused, so a test can see that nothing was ever written.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, RLock, Thread
from types import TracebackType
from typing import Final
from urllib.parse import urlsplit

from contracts.drift import Now
from contracts.meet import MeetPackage, PlaceKind
from contracts.station import ClearanceStatus

SIMULATOR_HEADER: Final = "X-Tellurian-Simulator"
FAULTS: Final = frozenset({"timeout", "redirect", "oversize", "invalid_json", "server_error"})
_DISPATCHER_PATH: Final = re.compile(r"/api/v1/dispatchers/(\d{1,9})")


@dataclass(frozen=True)
class SimDispatcher:
    id: int
    signature: str
    name: str


@dataclass(frozen=True)
class SimSection:
    """A train on a section: shown as a departure at `from_code` and an arrival at `to_code`.

    States are Tellurian's words (None, Requested, Accepted, ..., and Planned, Manned, ... for
    the train). They are sent as given, so a test can also send one Tellurian does not have.
    """

    train: str
    from_code: str
    to_code: str
    state: str = "None"
    train_state: str = "Planned"
    current: int = 0
    total: int = 1
    departure_time: str = ""
    arrival_time: str = ""


@dataclass(frozen=True)
class _Answer:
    status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


def _json(status: int, data: object) -> _Answer:
    return _Answer(status, json.dumps(data, ensure_ascii=False).encode())


_NOT_FOUND: Final = _json(404, {"title": "Not Found", "status": 404})


class TellurianSimulator:
    """Tellurian's read API on a loopback port of its own choosing."""

    def __init__(
        self, dispatchers: Iterable[tuple[str, str]], *, max_items: int = 10, stall: float = 1.0
    ) -> None:
        """`dispatchers` are (signature, name) pairs. Tellurian shows at most `max_items`
        sections per list; a "timeout" fault holds the answer back for `stall` seconds."""
        self.max_items = max_items
        self.stall = stall
        self._lock = RLock()
        self._dispatchers = tuple(
            SimDispatcher(number, signature, name)
            for number, (signature, name) in enumerate(dispatchers, start=1)
        )
        self._sections: dict[int, SimSection] = {}
        self._train_ids: dict[str, int] = {}
        self._next_section = 101
        self._faults: list[str] = []
        self._requests: list[tuple[str, str]] = []
        self._stopping = Event()
        self._server: _Server | None = None
        self._thread: Thread | None = None

    @classmethod
    def from_package(
        cls, package: MeetPackage, *, max_items: int = 10, stall: float = 1.0
    ) -> TellurianSimulator:
        """One dispatcher per place, signature = the place's code. A halt clears no trains and
        has no dispatcher, as in Tellurian."""
        return cls(
            ((place.code, place.name) for place in package.places if place.kind != PlaceKind.HALT),
            max_items=max_items,
            stall=stall,
        )

    # --- What the dispatchers show ------------------------------------------------------------

    @property
    def dispatchers(self) -> tuple[SimDispatcher, ...]:
        return self._dispatchers

    def dispatcher_id(self, signature: str) -> int:
        return next(d.id for d in self._dispatchers if d.signature == signature)

    def set_sections(self, sections: Iterable[SimSection]) -> list[int]:
        """Replace every section; gives their ids in order. A train keeps its trainId."""
        with self._lock:
            self._sections.clear()
            return [self._add(section) for section in sections]

    def add_section(self, section: SimSection) -> int:
        with self._lock:
            return self._add(section)

    def update(
        self,
        section_id: int,
        *,
        state: str | None = None,
        train_state: str | None = None,
        current: int | None = None,
    ) -> None:
        """Move a section on, as Tellurian's own view or another client would."""
        with self._lock:
            section = self._sections[section_id]
            self._sections[section_id] = replace(
                section,
                state=section.state if state is None else state,
                train_state=section.train_state if train_state is None else train_state,
                current=section.current if current is None else current,
            )

    def _add(self, section: SimSection) -> int:
        number = self._next_section
        self._next_section += 1
        self._sections[number] = section
        self._train_ids.setdefault(section.train, len(self._train_ids) + 1)
        return number

    def dispatcher_list(self) -> list[dict[str, object]]:
        return [
            {"id": d.id, "signature": d.signature, "name": d.name, "href": self._href(d.id)}
            for d in self._dispatchers
        ]

    def dispatcher_view(self, dispatcher_id: int) -> dict[str, object]:
        """A dispatcher's arrivals and departures. Arrived sections are hidden, as Tellurian
        hides them, and each list holds at most `max_items`. KeyError for an unknown id."""
        dispatcher = next((d for d in self._dispatchers if d.id == dispatcher_id), None)
        if dispatcher is None:
            raise KeyError(dispatcher_id)
        sig = dispatcher.signature
        with self._lock:
            visible = [(i, s) for i, s in sorted(self._sections.items()) if s.state != "Arrived"]
            arrivals = sorted(
                ((i, s) for i, s in visible if s.to_code == sig),
                key=lambda item: (item[1].arrival_time, item[0]),
            )
            departures = sorted(
                ((i, s) for i, s in visible if s.from_code == sig),
                key=lambda item: (item[1].departure_time, item[0]),
            )
            return {
                "id": dispatcher.id,
                "signature": sig,
                "stationName": dispatcher.name,
                "preferredLanguage": None,
                "arrivals": [self._dto(i, s) for i, s in arrivals[: self.max_items]],
                "departures": [self._dto(i, s) for i, s in departures[: self.max_items]],
            }

    def _dto(self, section_id: int, section: SimSection) -> dict[str, object]:
        return {
            "id": section_id,
            "trainId": self._train_ids[section.train],
            "train": section.train,
            "trainState": section.train_state,
            "state": section.state,
            "currentTrackStretch": section.current,
            "totalTrackStretches": section.total,
            "from": section.from_code,
            "to": section.to_code,
            "departureTime": section.departure_time,
            "arrivalTime": section.arrival_time,
        }

    @staticmethod
    def _href(dispatcher_id: int) -> str:
        return f"/api/v1/dispatchers/{dispatcher_id}"

    # --- Faults and what was asked, for tests only ---------------------------------------------

    def fail_next_read(self, kind: str) -> None:
        """The next GET fails: timeout, redirect, oversize, invalid_json or server_error."""
        if kind not in FAULTS:
            raise ValueError(kind)
        with self._lock:
            self._faults.append(kind)

    @property
    def requests(self) -> list[tuple[str, str]]:
        """Every request so far, as (method, path)."""
        with self._lock:
            return list(self._requests)

    def _answer(self, method: str, raw_path: str) -> _Answer | None:
        """The answer to a request, or None to hold it back and drop it (a timeout)."""
        path = urlsplit(raw_path).path
        with self._lock:
            self._requests.append((method, path))
            if method != "GET":
                return _json(405, {"title": "Method Not Allowed", "status": 405})
            fault = self._faults.pop(0) if self._faults else None
        if fault == "timeout":
            return None
        if fault == "redirect":
            location = ("Location", "http://example.invalid/api/v1/dispatchers")
            return _Answer(302, b"", (location,))
        if fault == "oversize":
            return _Answer(200, b"[" + b" " * (2 * 1024 * 1024) + b"]")
        if fault == "invalid_json":
            return _Answer(200, b"{")
        if fault == "server_error":
            return _json(500, {"title": "Internal Server Error", "detail": "secret stack trace"})
        if path == "/api/v1/dispatchers":
            return _json(200, self.dispatcher_list())
        match = _DISPATCHER_PATH.fullmatch(path)
        if match is None:
            return _NOT_FOUND
        try:
            return _json(200, self.dispatcher_view(int(match.group(1))))
        except KeyError:
            return _NOT_FOUND

    # --- The HTTP server ----------------------------------------------------------------------

    def start(self) -> str:
        """Serve on 127.0.0.1 in a thread; gives the base URL."""
        with self._lock:
            if self._server is not None:
                raise RuntimeError("Simulatorn är redan igång.")
            self._stopping.clear()
            server = _Server(self)
            thread = Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.05},
                name="tellurian-sim",
                daemon=True,
            )
            thread.start()
            self._server, self._thread = server, thread
        return self.base_url

    def stop(self) -> None:
        with self._lock:
            server, thread = self._server, self._thread
            self._server = self._thread = None
        if server is None:
            return
        self._stopping.set()
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        server = self._server
        if server is None:
            raise RuntimeError("Simulatorn är inte igång.")
        return f"http://127.0.0.1:{server.server_port}"

    def __enter__(self) -> TellurianSimulator:
        self.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.stop()


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, simulator: TellurianSimulator) -> None:
        self.simulator = simulator
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, format: str, *args: object) -> None:
        """Quiet: tests read `requests` instead."""

    def _serve(self) -> None:
        self.close_connection = True
        simulator = self.server.simulator
        answer = simulator._answer(self.command, self.path)
        if answer is None:
            simulator._stopping.wait(simulator.stall)
            return
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(answer.body)))
        self.send_header("Connection", "close")
        self.send_header(SIMULATOR_HEADER, "trainmeet-test")
        for name, value in answer.headers:
            self.send_header(name, value)
        self.end_headers()
        # The client may stop reading early, as it does for an answer that is too large.
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(answer.body)

    do_GET = _serve
    do_POST = _serve
    do_PUT = _serve
    do_PATCH = _serve
    do_DELETE = _serve


def sections_from(now: Now, *, differ: bool = True) -> list[SimSection]:
    """Drift's open clearances as Tellurian would show them, for the test environment: with
    `differ`, the first one cleared is shown as only requested, so the shadow has something to
    mark."""
    codes = {place.place: place.code for place in now.places}
    found: list[SimSection] = []
    changed = not differ
    for clearance in now.clearances:
        if clearance.status is ClearanceStatus.APPROVED:
            state = "Departed" if clearance.departed else "Accepted"
            if not changed and not clearance.departed:
                state, changed = "Requested", True
        elif clearance.status is ClearanceStatus.WAITING:
            state = "Requested"
        else:
            continue
        found.append(
            SimSection(
                train=f"Tåg {clearance.train_number}",
                from_code=codes.get(clearance.from_place, clearance.from_place),
                to_code=codes.get(clearance.to_place, clearance.to_place),
                state=state,
                train_state="Running" if clearance.departed else "Manned",
            )
        )
    return found
