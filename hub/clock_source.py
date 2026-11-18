"""Träffens klocka (F12, IMPORT-35): Drifts egen, eller FastClock som Drift följer.

The hub reads FastClock (integrationer/fastclock.py) about every other second for the meet that
runs, and lays its time on Drift's clock, so screens, boxes and TKL read the time from Drift
as before. Without an answer the clock stands at what it shows, with a warning in Nu; no other
clock takes over. After a restart the clock waits for FastClock's first answer. A switch back
to Drift's clock keeps the time and leaves the clock stopped. Only the hub that leads the meet
reads FastClock; a hub that follows another gets the time with Drift's events (SYNK-14).

GET  /api/hub/clock-source   ClockSourceSettings, for the one who runs the meet
POST /api/hub/clock-source   ClockSourceChange: FastClock is read before it is saved
"""

from __future__ import annotations

import contextlib
import logging
from threading import Event
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Response

from contracts import drift as events
from contracts import hub
from contracts.common import Weekday
from drift.engine import Refused
from drift.store import MissingRun
from hub.hubben import Authorization, SessionCookie, session_of
from hub.local import LocalLogin
from hub.rights import NOT_LOGGED_IN, Rights
from hub.running import Running
from integrationer import fastclock
from integrationer.fastclock import ExternalClock, FastClockError

LOGGER = logging.getLogger("hub.klockan")
ROUND_SECONDS: Final = 1.0
DRIFT_MAX_SPEED: Final = 60.0
TOO_FAST: Final = "FastClock går fortare än Drift kan följa, högst 60 gånger."


class ClockSource:
    """FastClock for the meet that runs, and Drift's clock laid on it."""

    def __init__(self, running: Running, login: LocalLogin, clock: ExternalClock | None = None):
        self.running = running
        self.login = login
        self.clock = clock if clock is not None else ExternalClock()

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

    def round(self) -> None:
        """One round: read FastClock if it is time, and let Drift follow it."""
        found = self.leading()
        if found is None:
            self.clock.configure("", fastclock.Settings())
            return
        run_id, meet = found
        settings = self.login.clock_source(meet)
        self.clock.configure(meet, settings)
        if settings.source != "fastclock":
            return
        self.clock.poll()
        status = self.clock.status()
        if status is None:
            return
        follows = status.available and status.seconds is not None and status.speed <= 60
        try:
            if follows:
                assert status.seconds is not None
                self.running.store.follow_clock(
                    run_id, status.seconds, status.speed, status.running
                )
            else:
                self.running.store.follow_clock(run_id, None, 1.0, False)
        except (Refused, MissingRun):
            return  # Drift is locked, or the meet just changed: the next round tries again.

    def now(self) -> events.ExternalClockNow | None:
        """FastClock in Nu, if it is the meet's clock."""
        if self.leading() is None:
            return None
        status = self.clock.status()
        if status is None:
            return None
        warning = None if status.available else status.stopped_reason
        if status.available and status.speed > DRIFT_MAX_SPEED:
            warning = TOO_FAST
        return events.ExternalClockNow(
            name=status.name or "FastClock",
            available=status.available and warning is None,
            can_control=status.can_control,
            warning=warning,
            reason=status.stopped_reason if status.available and status.stopped_reason else None,
            message=status.message,
            completed=status.completed,
            weekday=Weekday(status.weekday) if status.weekday else None,
        )

    def control(self, action: events.ClockAction) -> bool:
        """Start and stop go to FastClock when it is the clock; the time and the speed are set
        there. False when Drift's own clock is the meet's."""
        if self.clock.status() is None:
            return False
        if action not in (events.ClockAction.START, events.ClockAction.STOP):
            raise HTTPException(409, "Tiden och hastigheten ändras i FastClock när den är klockan.")
        try:
            self.clock.control(action.value)
        except FastClockError as error:
            raise HTTPException(409, str(error)) from None
        self.round()
        return True

    def run(self, stop: Event) -> None:
        while not stop.wait(ROUND_SECONDS):
            try:
                self.round()
            except Exception:
                LOGGER.exception("Klockan kunde inte följa FastClock")


def _view(meet: str, settings: fastclock.Settings) -> hub.ClockSourceSettings:
    return hub.ClockSourceSettings(
        meet=meet,
        source=hub.ClockSource(settings.source),
        clock_name=settings.clock_name,
        url=settings.url,
        user=settings.user,
        has_password=bool(settings.password),
        poll_interval=settings.poll_interval,
    )


def router(source: ClockSource, login: LocalLogin, rights: Rights) -> APIRouter:
    """rights: who may run the meet, as in Drift (hub/drift_api.py)."""
    routes = APIRouter(prefix="/api/hub")

    def leading(session: str | None, authorization: str | None) -> tuple[str, str]:
        """The run and its meet, for whoever may run it, in the hub that leads it."""
        token = session_of(session, authorization)
        if login.role(token) is None:
            raise HTTPException(401, NOT_LOGGED_IN)
        found = source.leading()
        if found is None:
            raise HTTPException(409, "Klockan ställs in i hubben som leder träffen som kör.")
        rights.require_runner(token, found[0], source.running.store.package.meet.id_meet)
        return found

    @routes.get("/clock-source")
    def read(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        _, meet = leading(session, authorization)
        return _view(meet, login.clock_source(meet)).model_dump(mode="json")

    @routes.post("/clock-source")
    def change(
        given: hub.ClockSourceChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id, meet = leading(session, authorization)
        previous = login.clock_source(meet)
        try:
            settings = fastclock.changed(given.model_dump(), previous)
            if settings.source == "fastclock":
                # FastClock must answer before it becomes the meet's clock.
                source.clock.probe(settings)
        except FastClockError as error:
            raise HTTPException(422, str(error)) from None
        login.set_clock_source(meet, settings)
        if previous.source == "fastclock" and settings.source == "drift":
            # Back to Drift's clock: the time stays, and the clock stands until started.
            with contextlib.suppress(Refused):
                source.running.store.follow_clock(run_id, None, 1.0, False)
        source.round()
        return _view(meet, settings).model_dump(mode="json")

    return routes
