"""Tellurian Dispatch i skugga (H79, IMPORT-06, IMPORT-34, T10): Hubben läser Tellurians
klareringar och visar dem bredvid Drifts i Nu och Logg, med det som skiljer markerat.

Nothing is ever sent to Tellurian, and Drift is never touched (regel 1): the hub reads every
five seconds while the meet that runs has the shadow on, and keeps what it read beside Drift.
Off is the default, per meet, and the setting never goes to the cloud. How Tellurian could
decide is open (T222) and not here. Only the hub that leads the meet reads Tellurian.

GET  /api/hub/tellurian       TellurianSettings, for the one who runs the meet
POST /api/hub/tellurian       TellurianChange: Tellurian is read once before it is saved
GET  /api/hub/tellurian/log   what Tellurian changed, newest first, for Logg

In the test environment TRAINMEET_TELLURIAN_SIMULATOR=1 starts the simulator on this machine,
fed from Drift's own clearances with one deliberate difference, so the shadow can be tried
without Tellurian (integrationer/tellurian_sim.py).
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from threading import Event
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Response

from contracts import drift as events
from contracts import hub
from drift.engine import now_utc
from drift.now import now as now_of
from drift.store import MissingRun
from hub.hubben import Authorization, SessionCookie, session_of
from hub.local import LocalLogin
from hub.rights import NOT_LOGGED_IN, Rights
from hub.running import Running
from integrationer.tellurian import (
    AddressRejected,
    DispatcherView,
    TellurianClient,
    TellurianError,
    change_text,
    check_address,
    problem_text,
    shadow,
)
from integrationer.tellurian_sim import TellurianSimulator, sections_from

LOGGER = logging.getLogger("hub.tellurian")
ROUND_SECONDS: Final = 5.0
LOG_SIZE: Final = 200

ADDRESS_PROBLEMS: Final = {
    "address_required": "Skriv Tellurians adress.",
    "address_invalid": "Adressen går inte att läsa.",
    "address_scheme": "Adressen ska börja med http:// eller https://.",
    "address_credentials": "Adressen får inte ha inloggning i sig.",
    "address_path": "Skriv bara schema, värd och port, utan sökväg eller frågor.",
    "address_trainmeet_cloud": "TrainMeets egna adresser kan inte vara Tellurian.",
    "address_not_local": (
        "Adressen är inte på träffens nät. Kryssa i Testinstans för en publik adress eller den "
        "här datorn."
    ),
}


class Shadow:
    """What Tellurian last said for the meet that runs, and what changed there."""

    def __init__(
        self,
        running: Running,
        login: LocalLogin,
        client_for: Callable[[str, bool], TellurianClient] | None = None,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self.running = running
        self.login = login
        self.client_for = client_for or (
            lambda address, test: TellurianClient(check_address(address, test_instance=test))
        )
        self.clock = clock
        self.lock = threading.Lock()
        self.meet: str | None = None
        self.views: list[DispatcherView] = []
        self.simulated = False
        self.heard: datetime | None = None
        self.problem: str | None = None
        self.log: deque[events.TellurianLogEntry] = deque(maxlen=LOG_SIZE)
        self.seen: dict[str, tuple[str, bool]] = {}
        self.simulator: str | None = None

    def leading(self) -> tuple[str, str] | None:
        """The run this hub leads, and its meet; None without one, or while following."""
        store = self.running.store
        try:
            run_id = store.current()
        except MissingRun:
            return None
        if store.leader(run_id) is not None:
            return None
        return run_id, store.package.meet.id

    def _forget(self, meet: str | None) -> None:
        self.meet, self.views, self.simulated = meet, [], False
        self.heard, self.problem = None, None
        self.log.clear()
        self.seen.clear()

    def round(self) -> None:
        """Read Tellurian once, if the shadow is on for the meet that runs."""
        found = self.leading()
        meet = found[1] if found is not None else None
        mode, address, test = self.login.tellurian(meet) if meet else ("off", "", False)
        with self.lock:
            if meet != self.meet or mode != "shadow":
                self._forget(meet if mode == "shadow" else None)
        if found is None or mode != "shadow":
            return
        try:
            client = self.client_for(address, test)
            views = client.views()
        except (TellurianError, AddressRejected) as error:
            with self.lock:
                self.problem = error.code
            return
        with self.lock:
            self.views, self.simulated = views, client.simulated
            self.heard, self.problem = self.clock(), None
        self._note_changes(found[0])

    def now(self, seen: events.Now) -> events.TellurianShadow | None:
        """The shadow beside Drift in Nu; None when it is off."""
        with self.lock:
            if self.meet is None or self.leading() is None:
                return None
            views, simulated = list(self.views), self.simulated
            heard, problem = self.heard, self.problem
        return shadow(
            self.running.store.package,
            seen,
            views,
            simulated=simulated,
            heard=heard,
            problem=problem,  # a code; shadow() says it in Swedish
            at=self.clock(),
        )

    def _note_changes(self, run_id: str) -> None:
        """What Tellurian changed since the last reading, for Logg."""
        try:
            seen = now_of(self.running.store.state(run_id), self.clock())
        except MissingRun:
            return
        found = self.now(seen)
        if found is None:
            return
        with self.lock:
            for section in found.sections:
                key = f"{section.train}|{section.from_code}|{section.to_code}"
                state = (section.state.value, section.differs)
                if self.seen.get(key) == state:
                    continue
                first = key not in self.seen
                self.seen[key] = state
                if first and section.state is events.TellurianState.NONE:
                    continue
                self.log.appendleft(
                    events.TellurianLogEntry(
                        at=self.clock(),
                        clock=seen.clock.time,
                        text=change_text(section),
                        differs=section.differs,
                    )
                )

    def entries(self) -> list[events.TellurianLogEntry]:
        with self.lock:
            return list(self.log)

    def run(self, stop: Event, feed: SimulatorFeed | None = None) -> None:
        while not stop.wait(ROUND_SECONDS):
            try:
                if feed is not None:
                    feed.round()
                self.round()
            except Exception:
                LOGGER.exception("Tellurian kunde inte läsas i skugga")
        if feed is not None:
            feed.stop()


class SimulatorFeed:
    """Test environment only: Tellurian's simulator on this machine, showing Drift's own open
    clearances, but the first one cleared as only requested, so that the shadow has something
    to mark. A new meet gets a simulator of its own, with its places as dispatchers."""

    def __init__(self, shadowing: Shadow) -> None:
        self.shadowing = shadowing
        self.meet: str | None = None
        self.simulator: TellurianSimulator | None = None

    def round(self) -> None:
        found = self.shadowing.leading()
        if found is None:
            return
        run_id, meet = found
        store = self.shadowing.running.store
        if meet != self.meet:
            self.stop()
            self.simulator = TellurianSimulator.from_package(store.package)
            self.shadowing.simulator = self.simulator.start()
            self.meet = meet
        assert self.simulator is not None
        try:
            seen = now_of(store.state(run_id), now_utc())
        except MissingRun:
            return
        self.simulator.set_sections(sections_from(seen))

    def stop(self) -> None:
        if self.simulator is not None:
            self.simulator.stop()
        self.simulator, self.meet = None, None
        self.shadowing.simulator = None


def simulator_from(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get("TRAINMEET_TELLURIAN_SIMULATOR", "").strip() == "1"


def router(shadowing: Shadow, login: LocalLogin, rights: Rights) -> APIRouter:
    routes = APIRouter(prefix="/api/hub")

    def leading(session: str | None, authorization: str | None) -> tuple[str, str]:
        token = session_of(session, authorization)
        if login.role(token) is None:
            raise HTTPException(401, NOT_LOGGED_IN)
        found = shadowing.leading()
        if found is None:
            raise HTTPException(409, "Tellurian ställs in i hubben som leder träffen som kör.")
        rights.require_runner(token, found[0], shadowing.running.store.package.meet.id_meet)
        return found

    def view(meet: str) -> hub.TellurianSettings:
        mode, address, test = login.tellurian(meet)
        return hub.TellurianSettings(
            meet=meet,
            mode=hub.TellurianMode(mode),
            address=address,
            test_instance=test,
            simulator=shadowing.simulator,
        )

    @routes.get("/tellurian")
    def read(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        _, meet = leading(session, authorization)
        return view(meet).model_dump(mode="json")

    @routes.post("/tellurian")
    def change(
        given: hub.TellurianChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        _, meet = leading(session, authorization)
        address = given.address.strip()
        if given.mode == hub.TellurianMode.SHADOW:
            try:
                endpoint = check_address(address, test_instance=given.test_instance)
                # Tellurian must answer before the shadow is on: one reading, nothing sent.
                shadowing.client_for(endpoint.origin, given.test_instance).dispatchers()
            except AddressRejected as error:
                raise HTTPException(
                    422, ADDRESS_PROBLEMS.get(error.code, "Adressen går inte att använda.")
                ) from None
            except TellurianError as error:
                raise HTTPException(422, problem_text(error.code)) from None
            address = endpoint.origin
        login.set_tellurian(meet, given.mode.value, address, given.test_instance)
        shadowing.round()
        return view(meet).model_dump(mode="json")

    @routes.get("/tellurian/log")
    def log(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        leading(session, authorization)
        return [entry.model_dump(mode="json") for entry in shadowing.entries()]

    return routes
