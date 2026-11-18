"""Förarnas API (trainmeet.driver/1, contracts/driver.py) for the hub's own meet: Lokföraren on
the driver's phone, and Förare in Drift for Trafikledningen and the lokledare (TRAFIK-33).

A driver comes in with the meet's QR code, a name and a level, and gets a device key: a random
secret kept on the phone, in an HttpOnly cookie or sent as X-Driver-Key. The hub keeps only its
hash and never writes it out. Logged in with TrainMeet ID, the driver is linked to the person
(LOK-16). The driver stays as long as the meet runs (LOK-41).

Names and photos follow the participants' rule (S8, LOK-37, hub/deltagare.py): on the meet's
network or logged in to the hub they are shown; over the internet without logging in they are
not. A driver always sees their own.

The updates: Nu is read every other second by the pages, and Drift's events are written as they
happen; a driver's phone waits for the next event on /wait (a long poll) and reads again.
"""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Final, NoReturn, TypeVar

import segno
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from contracts import drift as events
from contracts import driver as contract
from contracts.meet import AttachmentKind
from contracts.reasons import TEXT_SV, Reason
from drift import drivers
from drift.engine import Drift, Refused, now_utc
from drift.store import (
    PHOTO_MAX_BYTES,
    DriverRecord,
    MissingRun,
    PreviewStore,
    RunLimit,
    UnknownDriver,
)
from hub.deltagare import on_meet_network
from hub.hubben import Authorization, SessionCookie, _secure, session_of
from hub.local import PERSON, LocalLogin
from hub.network_api import _same_site
from hub.rights import Rights
from hub.running import Running

COOKIE: Final = "trainmeet_forare"
KeyCookie = Annotated[str | None, Cookie(alias=COOKIE, max_length=120)]
KeyHeader = Annotated[str | None, Header(alias=contract.KEY_HEADER, max_length=120)]
WAIT_SECONDS: Final = 25.0
WAIT_INTERVAL: Final = 0.5
KEY_LIFETIME: Final = 7 * 24 * 3600
NOT_IN: Final = "Kom in med QR-koden på träffen först."
NO_MEET: Final = "Ingen träff är startad."
PHOTO_TYPES: Final = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
T = TypeVar("T")


def initials(name: str) -> str:
    """Two letters for the icon: the first name's and the last name's, as the old Server."""
    parts = [part for part in re.split(r"[\s\-]+", name.strip()) if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def photo_type(data: bytes) -> str | None:
    """The picture's type from its first bytes: PNG, JPEG or WebP, nothing else. The hub reads
    nothing more out of it; the phone has already drawn it anew, without the camera's data."""
    for start, kind in PHOTO_TYPES.items():
        if data.startswith(start):
            return kind
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _refused(error: Refused) -> NoReturn:
    raise HTTPException(409, TEXT_SV[error.reason], headers={"X-Reason": error.reason.value}) from (
        error
    )


def router(running: Running, login: LocalLogin, rights: Rights | None = None) -> APIRouter:
    routes = APIRouter(prefix="/api/drift/1/drivers")
    may = rights if rights is not None else Rights(login)

    def store() -> PreviewStore:
        return running.store

    def current(found: PreviewStore) -> str:
        try:
            return found.current()
        except MissingRun as error:
            raise HTTPException(404, NO_MEET) from error

    def logged_in(session: str | None, authorization: str | None) -> bool:
        token = session_of(session, authorization)
        try:
            run = running.store.current()
        except MissingRun:
            run = None
        return login.role(token, run) is not None

    def names_shown(request: Request, session: str | None, authorization: str | None) -> bool:
        """LOK-37, S8: on the meet's network, or logged in."""
        return on_meet_network(request) or logged_in(session, authorization)

    def same_site(request: Request) -> None:
        if not _same_site(request):
            raise HTTPException(403, "Skicka från Lokföraren på hubbens egen adress.")

    def me(cookie: str | None, header: str | None) -> tuple[PreviewStore, DriverRecord]:
        found = store()
        try:
            return found, found.driver_by_key(header or cookie or "")
        except UnknownDriver as error:
            raise HTTPException(401, NOT_IN) from error

    def view(record: DriverRecord, shown: bool) -> contract.Driver:
        photo = (
            f"/api/drift/1/drivers/photos/{record.id}?v={record.photo_version}"
            if record.photo_type and shown
            else None
        )
        return contract.Driver(
            id=record.id,
            name=record.name if shown else None,
            initials=initials(record.name) if shown else None,
            level=record.level,
            state=contract.DriverState(record.state) if record.state else None,
            photo=photo,
            linked=record.person is not None,
            joined=record.joined,
        )

    def act(found: PreviewStore, run_id: str, action: Callable[[Drift, datetime], T]) -> Drift:
        try:
            drift, _ = found.drive(run_id, action)
        except Refused as error:
            _refused(error)
        except RunLimit as error:
            raise HTTPException(429, "Träffen har nått sin gräns.") from error
        except MissingRun as error:
            raise HTTPException(404, NO_MEET) from error
        return drift

    def state(found: PreviewStore, run_id: str) -> Drift:
        try:
            return found.state(run_id)
        except MissingRun as error:
            raise HTTPException(404, NO_MEET) from error

    def me_view(drift: Drift, record: DriverRecord) -> dict[str, Any]:
        now = now_utc()
        held = drift.drivers.service_of(record.id)
        service = drivers.find(drift, held.service) if held is not None else None
        return contract.DriverMe(
            driver=view(record, True),
            service=drivers.offer(
                drift, service, level=record.level, names={record.id: record.name}
            )
            if service is not None
            else None,
            start=drivers.start(drift, service, now) if service is not None else None,
            checkin=drivers.checked_in(drift, drift.drivers.checkins.get(record.id), now),
            clock=drivers.clock(drift, now),
            settings=drift.drivers.settings,
            revision=len(drift.history),
        ).model_dump(mode="json")

    def person_of(session: str | None, authorization: str | None) -> str | None:
        """TrainMeet ID, when the phone is logged in with it: the driver is linked to the
        person (LOK-16)."""
        token = session_of(session, authorization)
        if login.role(token) != PERSON:
            return None
        person = login.person(token)
        return person.id if person else None

    # --- Coming in and the driver's own --------------------------------------------------

    @routes.post("/join", status_code=201)
    def join(
        given: contract.DriverJoin,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Kom in (LOK-01, LOK-16): the meet's QR code, a name and a level. On the meet's
        network the code may be left out: the driver comes to the meet that runs."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found = store()
        run_id = current(found)
        if given.code:
            try:
                if found.driver_run(given.code) != run_id:
                    raise MissingRun()
            except MissingRun as error:
                raise HTTPException(404, "Koden gäller ingen träff som kör nu.") from error
        elif not on_meet_network(request):
            raise HTTPException(422, "Skanna QR-koden på träffen, eller skriv koden.")
        try:
            record, key = found.join_driver(
                run_id, given.name, given.level, person_of(session, authorization)
            )
        except RunLimit as error:
            raise HTTPException(429, "Träffen har nått sin gräns för förare.") from error
        except MissingRun as error:
            raise HTTPException(404, NO_MEET) from error
        response.set_cookie(
            COOKIE,
            key,
            max_age=KEY_LIFETIME,
            httponly=True,
            secure=_secure(request),
            samesite="strict",
            path="/api/drift/1/drivers",
        )
        return contract.DriverSession(driver=view(record, True), key=key).model_dump(mode="json")

    @routes.get("/me")
    def mine(response: Response, cookie: KeyCookie = None, header: KeyHeader = None) -> Any:
        response.headers["Cache-Control"] = "no-store"
        found, record = me(cookie, header)
        return me_view(state(found, record.run_id), record)

    @routes.post("/me")
    def change_me(
        given: contract.DriverProfile,
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """The name, the level, and Paus or Inväntar start (LOK-27)."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        record = found.change_driver(
            record.run_id,
            record.id,
            name=given.name,
            level=given.level,
            state=given.state.value if given.state else None,
            clear_state=given.clear_state,
            person=person_of(session, authorization),
        )
        return me_view(state(found, record.run_id), record)

    @routes.post("/me/photo")
    async def photo(
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
    ) -> Any:
        """The driver's own photo icon (LOK-27): a small PNG, JPEG or WebP the phone has cut and
        scaled. Anything else, or anything bigger, is refused."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = await run_in_threadpool(me, cookie, header)
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > PHOTO_MAX_BYTES:
                raise HTTPException(413, "Fotot är för stort. Välj det igen så görs det mindre.")
        kind = photo_type(data)
        if kind is None:
            raise HTTPException(415, "Fotot ska vara en PNG-, JPEG- eller WebP-bild.")
        record = await run_in_threadpool(
            found.set_driver_photo, record.run_id, record.id, (data, kind)
        )
        drift = await run_in_threadpool(state, found, record.run_id)
        return me_view(drift, record)

    @routes.post("/me/photo/remove")
    def remove_photo(
        request: Request, response: Response, cookie: KeyCookie = None, header: KeyHeader = None
    ) -> Any:
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        record = found.set_driver_photo(record.run_id, record.id, None)
        return me_view(state(found, record.run_id), record)

    @routes.get("/photos/{driver_id}")
    def photo_of(
        driver_id: str,
        request: Request,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Response:
        """A driver's photo, under the same rule as the names (LOK-37); one's own always."""
        found = store()
        run_id = current(found)
        own = None
        if header or cookie:
            try:
                own = found.driver_by_key(header or cookie or "").id
            except UnknownDriver:
                own = None
        if own != driver_id and not names_shown(request, session, authorization):
            raise HTTPException(404, "Fotot visas på träffens nät eller inloggad.")
        kept = found.driver_photo(run_id, driver_id)
        if kept is None:
            raise HTTPException(404, "Föraren har inget foto.")
        return Response(
            kept[0],
            media_type=kept[1],
            headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
        )

    # --- The services, the körplan, check-in, Framme and the messages -----------------------

    @routes.get("/services")
    def services(
        request: Request,
        response: Response,
        q: str | None = Query(default=None, max_length=20),
        cookie: KeyCookie = None,
        header: KeyHeader = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """Tjänsterna, or the trains on a meet without duties (LOK-17, LOK-31): released on the
        line first, then the driver's level, in start order. A search on the paper's number."""
        response.headers["Cache-Control"] = "no-store"
        found, record = me(cookie, header)
        drift = state(found, record.run_id)
        shown = names_shown(request, session, authorization)
        names = {r.id: r.name for r in found.drivers(record.run_id)} if shown else {}
        return drivers.service_list(drift, level=record.level, query=q, names=names).model_dump(
            mode="json"
        )

    @routes.post("/claim")
    def claim(
        given: events.ServiceRef,
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
    ) -> Any:
        """Ta tjänsten: the first one gets it; the other is told it is taken (LOK-40)."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        drift = act(found, record.run_id, lambda d, now: drivers.claim(d, given, record.id, now))
        return me_view(drift, record)

    @routes.post("/release")
    def release(
        request: Request, response: Response, cookie: KeyCookie = None, header: KeyHeader = None
    ) -> Any:
        """Släpp tjänsten, var som helst (LOK-25). On the line, Trafikledningen gets an alarm."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        drift = act(found, record.run_id, lambda d, now: drivers.release(d, record.id, now))
        return me_view(drift, record)

    @routes.get("/korplan")
    def korplan(response: Response, cookie: KeyCookie = None, header: KeyHeader = None) -> Any:
        """The körplan of my service, with the reality and the clearances' word when the game
        has chosen them (LOK-20, LOK-21), and my check-in beside the train's place (LOK-22)."""
        response.headers["Cache-Control"] = "no-store"
        found, record = me(cookie, header)
        drift = state(found, record.run_id)
        held = drift.drivers.service_of(record.id)
        service = drivers.find(drift, held.service) if held is not None else None
        if service is None:
            raise HTTPException(404, TEXT_SV[Reason.NO_SERVICE])
        now = now_utc()
        made = drivers.korplan(drift, service, now, len(drift.history))
        checkin = drivers.checked_in(drift, drift.drivers.checkins.get(record.id), now)
        return made.model_copy(update={"checkin": checkin}).model_dump(mode="json")

    @routes.post("/checkin")
    def check_in(
        given: contract.CheckIn,
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
    ) -> Any:
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        drift = act(
            found,
            record.run_id,
            lambda d, now: drivers.check_in(d, record.id, given.place, given.track, now),
        )
        return me_view(drift, record)

    @routes.post("/framme")
    def framme(
        given: contract.Framme,
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
    ) -> Any:
        """Framme (LOK-04, LOK-39): counts as the arrival only when chosen, at a place nobody
        works. At the service's last call the service is done."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        drift = act(
            found, record.run_id, lambda d, now: drivers.framme(d, record.id, given.call, now)
        )
        return me_view(drift, record)

    @routes.post("/messages", status_code=201)
    def send(
        given: contract.DriverMessageSend,
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
    ) -> Any:
        """Försenad, Står på linjen, Behöver hjälp or Loket krånglar (LOK-23, DRIFT-38)."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, record = me(cookie, header)
        drift = act(
            found, record.run_id, lambda d, now: drivers.message(d, record.id, given.kind, now)
        )
        sent = drift.drivers.messages[-1]
        return drivers.message_of(drift, sent, {record.id: record.name}).model_dump(mode="json")

    # --- Open like Nu: the clock, the trains and the drivers -----------------------------------

    @routes.get("/clock")
    def clock(response: Response) -> Any:
        """Drift's clock (LOK-12): the phone counts on from it, never from its own."""
        response.headers["Cache-Control"] = "no-store"
        found = store()
        drift = state(found, current(found))
        now = now_utc()
        return contract.DriverClock(
            clock=drivers.clock(drift, now), traffic_day=drift.traffic_day, read=now
        ).model_dump(mode="json")

    @routes.get("/trains")
    def trains(response: Response) -> Any:
        """Where each train of the day is according to the stations (LOK-08)."""
        response.headers["Cache-Control"] = "no-store"
        found = store()
        drift = state(found, current(found))
        return [p.model_dump(mode="json") for p in drivers.positions(drift, now_utc())]

    @routes.get("/list")
    def listed(
        request: Request,
        response: Response,
        cookie: KeyCookie = None,
        header: KeyHeader = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """Förare, and the drivers on the maps (LOK-27): names and photos only under the rule."""
        response.headers["Cache-Control"] = "no-store"
        found = store()
        run_id = current(found)
        drift = state(found, run_id)
        own = None
        if header or cookie:
            try:
                own = found.driver_by_key(header or cookie or "").id
            except UnknownDriver:
                own = None
        shown = names_shown(request, session, authorization)
        now = now_utc()
        rows: list[dict[str, Any]] = []
        for record in found.drivers(run_id):
            held = drift.drivers.service_of(record.id)
            service = drivers.find(drift, held.service) if held is not None else None
            part = drivers.current_part(drift, service) if service is not None else None
            rows.append(
                contract.DriverPresence(
                    driver=view(record, shown or record.id == own),
                    service_number=service.number if service else None,
                    train_number=part.train.number if part else None,
                    checkin=drivers.checked_in(drift, drift.drivers.checkins.get(record.id), now),
                    me=record.id == own,
                ).model_dump(mode="json")
            )
        return rows

    @routes.get("/wait")
    async def wait(
        response: Response,
        after: int = Query(ge=0),
        seconds: float = Query(default=WAIT_SECONDS, ge=0, le=30),
    ) -> Any:
        """Vänta på nästa drifthändelse efter after, högst seconds: then read again."""
        response.headers["Cache-Control"] = "no-store"
        found = store()
        run_id = await run_in_threadpool(current, found)
        waited = 0.0
        while True:
            try:
                fresh = await run_in_threadpool(found.events_after, run_id, after)
            except MissingRun as error:
                raise HTTPException(404, NO_MEET) from error
            if fresh:
                return contract.DriverWait(revision=fresh[-1].seq, changed=True).model_dump(
                    mode="json"
                )
            if waited >= seconds or found is not running.store:
                return contract.DriverWait(revision=after, changed=False).model_dump(mode="json")
            await asyncio.sleep(WAIT_INTERVAL)
            waited += WAIT_INTERVAL

    @routes.get("/instructions")
    def instructions(response: Response) -> Any:
        """De allmänna instruktionerna ur träffpaketet (LOK-34): the text, and the PDF if the
        package has one."""
        response.headers["Cache-Control"] = "no-store"
        found = store()
        package = state(found, current(found)).package
        pdf = next((a for a in package.attachments if a.kind == AttachmentKind.INSTRUCTIONS), None)
        return contract.Instructions(
            text={
                language.value: about.instructions
                for language, about in package.about.items()
                if about.instructions
            },
            pdf="/api/drift/1/drivers/instructions.pdf" if pdf is not None else None,
            filename=pdf.filename if pdf is not None else None,
        ).model_dump(mode="json")

    @routes.get("/instructions.pdf")
    def instructions_pdf() -> Response:
        found = store()
        package = state(found, current(found)).package
        pdf = next((a for a in package.attachments if a.kind == AttachmentKind.INSTRUCTIONS), None)
        kept = running.planning.file(pdf.sha256) if pdf is not None else None
        if pdf is None or kept is None:
            raise HTTPException(404, "Instruktionerna som PDF finns inte på den här hubben.")
        return Response(
            kept[1],
            media_type="application/pdf",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    # --- Förare in Drift (TRAFIK-33): Trafikledningen and the lokledare ------------------------

    def leading(session: str | None, authorization: str | None) -> tuple[PreviewStore, str, bool]:
        """The meet that runs, for whoever leads the drivers: and whether they also run it."""
        token = session_of(session, authorization)
        found = store()
        try:
            run_id = found.current()
        except MissingRun as error:
            if login.role(token) is None:
                raise HTTPException(401, "Logga in som trafikledare eller lokledare.") from error
            raise HTTPException(404, NO_MEET) from error
        id_meet = found.package.meet.id_meet
        may.require_driver_lead(token, run_id, id_meet)
        return found, run_id, may.may_run(token, run_id, id_meet)

    def overview(found: PreviewStore, run_id: str, runs: bool) -> dict[str, Any]:
        drift = state(found, run_id)
        records = found.drivers(run_id)
        names: dict[str, str | None] = {r.id: r.name for r in records}
        now = now_utc()
        latest = {m.driver: m for m in drift.drivers.messages}
        rows: list[contract.DriverRow] = []
        for record in records:
            held = drift.drivers.service_of(record.id)
            service = drivers.find(drift, held.service) if held is not None else None
            part = drivers.current_part(drift, service) if service is not None else None
            said = latest.get(record.id)
            rows.append(
                contract.DriverRow(
                    driver=view(record, True),
                    service=drivers.offer(drift, service, names=names) if service else None,
                    checkin=drivers.checked_in(drift, drift.drivers.checkins.get(record.id), now),
                    position=drivers.position(drift, part.train, now) if part else None,
                    message=drivers.message_of(drift, said, names) if said else None,
                )
            )
        return contract.DriverOverview(
            drivers=rows,
            services=drivers.service_list(drift, names=names),
            messages=[
                drivers.message_of(drift, m, names) for m in reversed(drift.drivers.messages)
            ][:50],
            alarms=drivers.alarms(drift),
            settings=drift.drivers.settings,
            may_hand_out=True,
            may_set=runs,
            names_shown=True,
        ).model_dump(mode="json")

    def by(runs: bool) -> events.ClaimedBy:
        """Who hands out: Trafikledningen, or the lokledare (LOK-30)."""
        return "dispatcher" if runs else "loco_lead"

    @routes.get("/overview")
    def look(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> Any:
        response.headers["Cache-Control"] = "no-store"
        found, run_id, runs = leading(session, authorization)
        return overview(found, run_id, runs)

    def known(found: PreviewStore, run_id: str, driver_id: str) -> None:
        try:
            found.driver(run_id, driver_id)
        except UnknownDriver as error:
            raise HTTPException(404, "Föraren finns inte i träffen.") from error

    @routes.post("/hand-out")
    def hand_out(
        given: contract.HandOut,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """Dela ut en tjänst (LOK-30): taken from whoever had it; the driver's own goes back.
        Also when the driver has changed phone (LOK-40)."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, run_id, runs = leading(session, authorization)
        known(found, run_id, given.driver)
        who = by(runs)
        act(
            found, run_id, lambda d, now: drivers.claim(d, given.service, given.driver, now, by=who)
        )
        return overview(found, run_id, runs)

    @routes.post("/take-back")
    def take_back(
        given: contract.TakeBack,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, run_id, runs = leading(session, authorization)
        known(found, run_id, given.driver)
        who = by(runs)
        act(found, run_id, lambda d, now: drivers.take_back(d, given.driver, now, by=who))
        return overview(found, run_id, runs)

    def running_it(runs: bool) -> None:
        if not runs:
            raise HTTPException(403, "Bara trafikledningen ändrar trafikspelets val.")

    @routes.post("/settings")
    def settings(
        given: events.DriverSettings,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """Förarna ser verkligheten, förarna ser tågklareringens besked, och Framme räknas som
        ankomst: per game, off by default, the dispatcher's (LOK-20, LOK-21, LOK-39)."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, run_id, runs = leading(session, authorization)
        running_it(runs)
        act(found, run_id, lambda d, now: drivers.set_settings(d, given, now))
        return overview(found, run_id, runs)

    @routes.post("/alarms/clear")
    def clear(
        given: events.ServiceRef,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """Trafikledningen has taken care of the train without a driver (LOK-35)."""
        response.headers["Cache-Control"] = "no-store"
        same_site(request)
        found, run_id, runs = leading(session, authorization)
        running_it(runs)
        act(found, run_id, lambda d, now: drivers.clear_alarm(d, given, now))
        return overview(found, run_id, runs)

    def address(request: Request, code: str) -> str:
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("host") or request.url.netloc
        return f"{scheme}://{host}/lokforaren/#kod={code}"

    @routes.get("/connect")
    def connect(
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Any:
        """The QR code to put up at the meet: the drivers' code and the address (LOK-01)."""
        response.headers["Cache-Control"] = "no-store"
        found, run_id, _ = leading(session, authorization)
        code = found.driver_code(run_id)
        return events.Joining(code=code, url=address(request, code)).model_dump(mode="json")

    @routes.get("/connect.svg")
    def connect_qr(
        request: Request, session: SessionCookie = None, authorization: Authorization = None
    ) -> Response:
        found, run_id, _ = leading(session, authorization)
        picture = io.BytesIO()
        segno.make(address(request, found.driver_code(run_id)), error="m").save(
            picture, kind="svg", scale=6, border=2, dark="#0e1114", light="#ffffff"
        )
        return Response(
            picture.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"}
        )

    return routes
