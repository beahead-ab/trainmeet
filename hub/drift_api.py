"""Driftens API (5.4) for the hub's own meet: start the meet, run the clock, see Nu, handle the
clients, read the log and follow the events. Steg 3.

Everyone may read Nu (S1); everything else needs the local administrator's session, as a
cookie from the pages or as Authorization: Bearer. The meet lives in a file of its own, apart
from Provbanan's runs per browser (H51).
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from typing import Any, NoReturn

import segno
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from contracts import drift, hub, screen
from contracts.common import Id
from contracts.id import MeetRole
from contracts.reasons import TEXT_SV, Reason
from drift.engine import Refused, now_utc
from drift.now import now
from drift.store import (
    ExitAnswered,
    MissingRun,
    RunLimit,
    UnknownBox,
    UnknownClient,
    UnknownExit,
)
from hub.clock_source import ClockSource
from hub.hubben import Authorization, SessionCookie, session_of
from hub.id_roles import PLANS, RUNS
from hub.local import DISPATCHER, PERSON, LocalLogin
from hub.rights import NO_ROLE, NOT_LOGGED_IN, Rights
from hub.running import PROVBANAN, NeedsNewerHub, Running, UnknownMeet, WithdrawnVersion
from synk.store import SyncError

STREAM_SECONDS = 300
STREAM_INTERVAL = 0.5
HEARTBEAT_SECONDS = 15


def _error(error: Exception) -> NoReturn:
    if isinstance(error, Refused):
        raise HTTPException(409, TEXT_SV[error.reason]) from error
    if isinstance(error, RunLimit):
        raise HTTPException(429, "Träffen har nått sin gräns.") from error
    if isinstance(error, (UnknownBox, UnknownClient)):
        raise HTTPException(404, "Klienten finns inte i träffen.") from error
    if isinstance(error, ExitAnswered):
        raise HTTPException(409, str(error)) from error
    if isinstance(error, UnknownExit):
        raise HTTPException(404, "Utfarten eller sträckan finns inte här.") from error
    raise HTTPException(404, "Ingen träff är startad.") from error


def _latest(history: list[drift.DriftEvent], kind: drift.EventKind | None) -> drift.DriftEvent:
    """The latest event of a kind, or the latest of all."""
    if kind is None:
        return history[-1]
    return next(event for event in reversed(history) if event.kind == kind)


def router(
    running: Running,
    login: LocalLogin,
    rights: Rights | None = None,
    clock_source: ClockSource | None = None,
) -> APIRouter:
    """rights: who may run the meet: the hub's PIN, someone let in with a one-time code (H56),
    or Administratör and Trafikledare at the meet in TrainMeet ID (ID3, #78). clock_source:
    FastClock as the meet's clock, when it is chosen (F12, hub/clock_source.py)."""
    routes = APIRouter(prefix="/api/drift/1")
    failures = (MissingRun, RunLimit, Refused, UnknownBox, UnknownClient, ExitAnswered, UnknownExit)
    may = rights if rights is not None else Rights(login)

    def dispatching(session: str | None, authorization: str | None) -> str:
        """The meet that runs, for whoever may run it."""
        token = session_of(session, authorization)
        try:
            run_id = running.store.current()
        except MissingRun as error:
            if login.role(token) is None:
                raise HTTPException(401, NOT_LOGGED_IN) from error
            _error(error)
        may.require_runner(token, run_id, running.store.package.meet.id_meet)
        return run_id

    def may_start(token: str | None, meet: str, version: int) -> None:
        """Byt träff: the PIN, or at the meet in TrainMeet ID Administratör, Arrangör or
        Trafikledare (ID3, PLAN-19). Provbanan only with the PIN."""
        if login.valid(token):
            return
        if login.role(token) != PERSON:
            raise HTTPException(401, NOT_LOGGED_IN)
        id_meet = None
        if meet != PROVBANAN:
            try:
                id_meet = running.versions.package(meet, version).meet.id_meet
            except SyncError as error:
                raise HTTPException(409, "Den versionen av träffen finns inte i hubben.") from error
        if not may.id_roles(token, id_meet) & (PLANS | RUNS):
            raise HTTPException(403, NO_ROLE)

    @routes.post("/start", status_code=201)
    def start(
        request: drift.StartMeet,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Start a meet and version, or a new run in its place: the old one is kept, archived."""
        response.headers["Cache-Control"] = "no-store"
        may_start(session_of(session, authorization), request.meet, request.version)
        try:
            store, run_id = running.start(
                request.meet, request.version, request.traffic_day, request.game_day
            )
            return store.state(run_id).history[0].model_dump(mode="json")
        except WithdrawnVersion as error:
            raise HTTPException(
                409, "Versionen är tillbakadragen i Planering och kan inte startas."
            ) from error
        except NeedsNewerHub as error:
            raise HTTPException(409, str(error)) from error
        except UnknownMeet as error:
            raise HTTPException(409, "Den versionen av träffen finns inte i hubben.") from error
        except failures as error:
            _error(error)

    @routes.post("/takeover")
    def take_over(
        request: drift.TakeOver,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Ta över i molnet (TRAFIK-08, H8, H9): the run another hub led is led from here, with
        a higher epoch, and the clock stopped. Only by hand, with the meet's name written."""
        response.headers["Cache-Control"] = "no-store"
        token = session_of(session, authorization)
        if not login.valid(token) and login.role(token) != PERSON:
            # Not with a one-time code: that holds in the meet's own hub only (H56).
            raise HTTPException(401, NOT_LOGGED_IN)
        run_id = dispatching(session, authorization)
        name = running.store.package.meet.name
        if request.confirm.strip().casefold() != name.casefold():
            raise HTTPException(422, f"Skriv träffens namn, {name}, för att ta över.")
        try:
            state = running.store.take_over(run_id, login.state().name)
        except failures as error:
            _error(error)
        return state.history[-1].model_dump(mode="json")

    @routes.post("/clock")
    def clock(
        control: drift.ClockControl,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        if clock_source is not None and clock_source.control(control.action):
            # FastClock is the clock: start and stop went there, and Drift followed (F12).
            return _latest(running.store.state(run_id).history, None).model_dump(mode="json")
        try:
            state = running.store.clock(run_id, control)
        except failures as error:
            _error(error)
        # A jump and Ångra are written between begun and done (DRIFT-47): the answer is the
        # event itself.
        kind = {
            drift.ClockAction.JUMP: drift.EventKind.TIME_JUMP,
            drift.ClockAction.UNDO_JUMP: drift.EventKind.TIME_JUMP_UNDONE,
        }.get(control.action)
        return _latest(state.history, kind).model_dump(mode="json")

    @routes.post("/day")
    def new_day(
        request: drift.NewDay,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Starta ny dag (F7): the next game day with its traffic day."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            state = running.store.new_day(run_id, request)
        except failures as error:
            _error(error)
        return _latest(state.history, drift.EventKind.DAY_CHANGED).model_dump(mode="json")

    @routes.post("/day/settings")
    def day_settings(
        settings: drift.DaySettings,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Dygnsskiftet by hand (förval) or automatic, and its time (F7)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.set_day(run_id, settings).model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.post("/changes")
    def make_change(
        request: drift.MakeChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Ny driftändring (TRAFIK-02, DRIFT-41): it applies at once, or waits for the train."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            state = running.store.make_change(run_id, request)
        except failures as error:
            _error(error)
        event = next(e for e in reversed(state.history) if e.kind == drift.EventKind.CHANGE_MADE)
        made = drift.ChangeMade.model_validate(event.data)
        if running.meet != PROVBANAN and running.home_here(running.meet):
            # Every driftändring is a proposal for the next version (4.4). Synk carries it when
            # Planering is elsewhere; on the meet's home it is handed over here.
            running.planning.propose(
                running.meet, state.version, made.change_id, made.change, made.train_number
            )
        return event.model_dump(mode="json")

    @routes.post("/changes/{change_id}/drop")
    def drop_change(
        change_id: Id,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Släpp a driftändring."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            event = running.store.drop_change(run_id, change_id).history[-1]
        except failures as error:
            _error(error)
        if running.meet != PROVBANAN and running.home_here(running.meet):
            running.planning.withdraw(running.meet, change_id)
        return event.model_dump(mode="json")

    @routes.post("/changes/{change_id}/force")
    def force_change(
        change_id: Id,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Tvinga igenom a waiting driftändring, with Nu's warning (H38)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.force_change(run_id, change_id).history[-1].model_dump(mode="json")
        except failures as error:
            _error(error)

    # --- Versionsbyte (TRAFIK-03, DRIFT-29) and påbörjat och klart (DRIFT-47) -----------------

    def switchable(version: int) -> None:
        """A version withdrawn in Planering is no version to switch to (PLAN-18)."""
        if running.withdrawn(running.meet, version):
            _error(Refused(Reason.UNKNOWN_VERSION))

    @routes.get("/switch/{version}")
    def switch_preview(
        version: int,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """What a switch to the version would do: the driftändringar that fall away and the
        trains it waits for (H4, H38)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        switchable(version)
        try:
            state = running.store.state(run_id)
            waits = state.switch_waits_for(version)
        except failures as error:
            _error(error)
        taken = set(running.included(version))
        return drift.SwitchPreview(
            version=version,
            changes=[
                drift.SwitchChange(change_id=change_id, included=change_id in taken)
                for change_id, change in state.changes.items()
                if change.status != drift.ChangeStatus.DROPPED
            ],
            waits_for=waits,
        ).model_dump(mode="json")

    @routes.post("/switch")
    def switch(
        request: drift.SwitchVersion,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Byt till en ny version (TRAFIK-03): made, or waiting for the trains that are out."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        switchable(request.version)
        try:
            state = running.store.switch(run_id, request, running.included(request.version))
        except failures as error:
            _error(error)
        kinds = (drift.EventKind.VERSION_SWITCHED, drift.EventKind.VERSION_WAITING)
        return next(e for e in reversed(state.history) if e.kind in kinds).model_dump(mode="json")

    @routes.post("/switch/force")
    def force_switch(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Tvinga igenom the switch that waits (H38)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            state = running.store.force_switch(run_id)
        except failures as error:
            _error(error)
        return _latest(state.history, drift.EventKind.VERSION_SWITCHED).model_dump(mode="json")

    @routes.post("/switch/call-off")
    def call_off(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Avbryt bytet that waits."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.call_off_switch(run_id).history[-1].model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.post("/unlock")
    def unlock(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Lås upp Drift that started locked (DRIFT-47)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.unlock(run_id).history[-1].model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.get("/package")
    def package(response: Response) -> dict[str, Any]:
        """The package Drift goes by: the version with the driftändringar on top. The
        timetable is no secret, so anyone who looks may read it, like Nu."""
        response.headers["Cache-Control"] = "no-store"
        try:
            return running.store.state(running.store.current()).package.model_dump(mode="json")
        except MissingRun as error:
            _error(error)

    @routes.get("/phones")
    def phones(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """Every place's game number (H30). Only for the dispatcher: Nu shows no numbers (B13)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return [phone.model_dump(mode="json") for phone in running.store.phones(run_id)]
        except failures as error:
            _error(error)

    @routes.post("/phones")
    def change_phone(
        change: drift.PlacePhone,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """A place's number changed during the meet (TRAFIK-06); TKL and the app read it."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return [
                phone.model_dump(mode="json") for phone in running.store.set_phone(run_id, change)
            ]
        except failures as error:
            _error(error)

    @routes.get("/now")
    def nu(response: Response) -> dict[str, Any]:
        """Nu, open to everyone who looks (S1), with Planering's answer to each driftändring
        (4.4)."""
        response.headers["Cache-Control"] = "no-store"
        try:
            seen = now(running.store.state(running.store.current()), now_utc())
        except MissingRun as error:
            _error(error)
        if running.withdrawn(running.meet, seen.version):
            seen = seen.model_copy(update={"withdrawn": True})
        led = running.store.leader(running.store.current())
        if led is not None:
            hub_name, heard = led
            silent = max(0, int((now_utc() - heard).total_seconds()))
            seen = seen.model_copy(
                update={"leader": drift.Leader(hub_name=hub_name, heard=heard, silent=silent)}
            )
        if clock_source is not None:
            seen = seen.model_copy(update={"external_clock": clock_source.now()})
        if seen.changes and running.meet != PROVBANAN:
            answers = running.answers(running.meet)
            seen = seen.model_copy(
                update={
                    "changes": [
                        c.model_copy(update={"proposal": answers.get(c.change_id)})
                        for c in seen.changes
                    ]
                }
            )
        return seen.model_dump(mode="json")

    @routes.get("/clients")
    def clients(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return running.store.clients(dispatching(session, authorization))

    def changed(listed: list[dict[str, Any]], client_id: str) -> dict[str, Any]:
        return next(client for client in listed if client["client_id"] == client_id)

    @routes.post("/clients/assign")
    def assign(
        change: drift.Assign,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return changed(running.store.assign(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.post("/clients/approve")
    def approve(
        change: drift.Approve,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return changed(running.store.approve(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.post("/clients/exit")
    def couple_exit(
        change: drift.CoupleExit,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Trafikledningen svarar på Hubbens fråga om en utfart (TRAFIK-05)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return changed(running.store.couple_exit(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.post("/clients/revoke")
    def revoke(
        change: drift.Revoke,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return changed(running.store.revoke(run_id, change), change.client_id)
        except failures as error:
            _error(error)

    @routes.post("/clients/view")
    def show_view(
        change: screen.ShowView,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """A screen gets its view (S3); none sends it back to Väntar."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        view = change.view.value if change.view else None
        try:
            return changed(
                running.store.show_view(run_id, change.client_id, view), change.client_id
            )
        except failures as error:
            _error(error)

    @routes.get("/automation")
    def automation(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Who works which place, the automation's settings and the trains it waits with
        (F14)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.automation(run_id).model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.post("/automation")
    def automation_settings(
        settings: drift.AutomationSettings,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.set_automation(run_id, settings).model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.post("/automation/place")
    def automation_place(
        change: drift.AutomationPlace,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Lämna en plats till automatiken, eller ge den tillbaka till en klient där."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        try:
            return running.store.automation_place(run_id, change).model_dump(mode="json")
        except failures as error:
            _error(error)

    @routes.get("/log")
    def log(
        response: Response,
        place: Id | None = None,
        train: Id | None = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        return [event.model_dump(mode="json") for event in running.store.log(run_id, place, train)]

    @routes.get("/refusals")
    def refusals(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """What clients were told no, newest first (B15)."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        return [refusal.model_dump(mode="json") for refusal in running.store.refusals(run_id)]

    @routes.get("/connect")
    def connect(
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Anslut (S2): the meet's code, and the address a box opens with it."""
        response.headers["Cache-Control"] = "no-store"
        code = running.store.join_code(dispatching(session, authorization))
        url = f"{_origin(request)}/box#kod={code}"
        return drift.Joining(code=code, url=url).model_dump(mode="json")

    @routes.get("/connect.svg")
    def connect_qr(
        request: Request, session: SessionCookie = None, authorization: Authorization = None
    ) -> Response:
        code = running.store.join_code(dispatching(session, authorization))
        picture = io.BytesIO()
        segno.make(f"{_origin(request)}/box#kod={code}", error="m").save(
            picture, kind="svg", scale=6, border=2, dark="#0e1114", light="#ffffff"
        )
        return Response(
            picture.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"}
        )

    @routes.get("/events")
    async def events(
        request: Request, session: SessionCookie = None, authorization: Authorization = None
    ) -> StreamingResponse:
        """The meet's Drift events as they happen, from now on."""
        run_id = await run_in_threadpool(dispatching, session, authorization)
        store = running.store
        start = len((await run_in_threadpool(store.state, run_id)).history)

        async def stream() -> AsyncIterator[str]:
            seen, quiet, waited = start, 0.0, 0.0
            yield ": hubben lyssnar\n\n"
            while waited < STREAM_SECONDS:
                await asyncio.sleep(STREAM_INTERVAL)
                waited += STREAM_INTERVAL
                quiet += STREAM_INTERVAL
                if await request.is_disconnected():
                    return
                if store is not running.store:
                    yield "event: gone\ndata: {}\n\n"
                    return
                try:
                    found = await run_in_threadpool(store.events_after, run_id, seen)
                except MissingRun:
                    yield "event: gone\ndata: {}\n\n"
                    return
                for event in found:
                    quiet = 0.0
                    seen = event.seq
                    yield f"event: drift\ndata: {event.model_dump_json()}\n\n"
                if quiet >= HEARTBEAT_SECONDS:
                    quiet = 0.0
                    yield ": vänta\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # --- Släpp in med engångskod (H56, KONTO-19, F18) --------------------------------------

    @routes.post("/codes", status_code=201)
    def give_code(
        request: hub.OneTimeCodeRequest,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Six digits, once, for 15 minutes, for this meet. The administrator and a dispatcher
        both give Trafikledare: at most the giver's own role on the meet."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        code, expires = login.issue_code(run_id, DISPATCHER, request.name)
        return hub.OneTimeCode(code=code, role=MeetRole.DISPATCHER, expires=expires).model_dump(
            mode="json"
        )

    @routes.get("/let-in")
    def let_in(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """Vem som är inne med en engångskod, och tills när. Never the code or the key."""
        response.headers["Cache-Control"] = "no-store"
        run_id = dispatching(session, authorization)
        return [
            hub.LetIn(
                person=found.person,
                name=found.name,
                role=MeetRole(found.role),
                since=found.since,
                until=found.until,
            ).model_dump(mode="json")
            for found in login.let_in(run_id)
        ]

    @routes.post("/let-in/{person}/remove", status_code=204)
    def take_away(
        person: str, session: SessionCookie = None, authorization: Authorization = None
    ) -> None:
        """Ta bort: the role ends at once (H56)."""
        run_id = dispatching(session, authorization)
        if not login.take_away(run_id, person):
            raise HTTPException(404, "Den inloggningen finns inte i träffen.")

    return routes


def _origin(request: Request) -> str:
    """The address boxes reach the hub at, as the browser that asked sees it."""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"
