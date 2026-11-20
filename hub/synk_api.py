"""Synkprotokollet i hubben (trainmeet.sync/1, steg 5 del 2).

In the cloud: Koppla en Pi gives a code for a meet (SYNK-02); the Pi links with it and then
follows the meet's versions with long-poll, with its own key (SYNK-10, SYNK-13). On the Pi:
Den här hubben → Molnet, where the administrator gives the cloud's address and the code, and
sees the meets the Pi follows. The key is never shown or logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from contracts import drift
from contracts import id as id_contract
from contracts.reasons import Reason
from contracts.sync import (
    HEADER,
    PROTOCOL,
    CloudLinkChange,
    Hello,
    Home,
    HomeBundle,
    Link,
    LinkRequest,
    PushBatch,
    RelayAnswer,
    RelayCalls,
    RelayMeet,
    RelayMeets,
    RelayWay,
    RunAck,
    RunEvents,
    RunFeed,
    SentVersion,
    SourceFile,
    StationList,
    StationPackage,
    StationVersions,
    VersionList,
)
from contracts.sync import Follower as FollowerInfo
from drift.engine import Refused
from drift.store import MissingRun
from hub.hubben import Authorization, SessionCookie, require_admin
from hub.local import LocalLogin
from hub.push import Senders
from hub.running import Running
from planering.store import Planning, PlanningError
from synk.follower import Follower
from synk.home import Homes
from synk.link import LinkError, Links
from synk.relay import Relay
from synk.stations import Behind, NoOwners, Owners, StationError, Stations
from synk.store import SyncError, Versions

MAX_WAIT = 25.0
POLL = 0.5

SyncHeader = Annotated[str | None, Header(alias=HEADER, max_length=60)]


def _fail(error: LinkError | SyncError | PlanningError) -> NoReturn:
    raise HTTPException(error.status, str(error)) from error


def _protocol(spoken: str | None) -> None:
    if spoken is not None and spoken != PROTOCOL:
        raise HTTPException(426, f"Hubben talar {PROTOCOL}.")


def _key(authorization: str | None) -> str:
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not key:
        raise HTTPException(401, "Pi:ns nyckel saknas.")
    return key


def mark(listed: list[dict[str, Any]]) -> str:
    """The version list's mark: changes when a version is published or withdrawn."""
    return hashlib.sha256(repr(listed).encode()).hexdigest()[:24]


def router(
    plans: Planning,
    versions: Versions,
    links: Links,
    follower: Follower,
    running: Running,
    homes: Homes,
    login: LocalLogin,
    hello: Callable[[], Hello],
    relay: Relay | None = None,
    pushes: Senders | None = None,
    stations: Stations | None = None,
    owners: Owners | None = None,
    meets_of: Callable[[str], list[id_contract.Meet]] | None = None,
) -> APIRouter:
    """meets_of: the meets of a person's clubs in TrainMeet ID, with the person's roles (ID10),
    where the hub has ID's API; the meets molnets TKL may join (TKLMOLN-03)."""
    routes = APIRouter()
    relay = relay if relay is not None else Relay()

    def home(meet: str) -> Home:
        me = hello()
        return homes.home(meet, me.hub_id, me.hub_name)

    def bundle(meet: str, generation: int) -> HomeBundle:
        """What moves with the home: the draft, the sources and the proposals (H35)."""
        created, draft, files, proposals = plans.export(meet)
        return HomeBundle(
            meet=meet,
            generation=generation,
            created=created,
            draft=draft,
            sources=[SourceFile(id=s, data=base64.b64encode(b).decode()) for s, b in files],
            proposals=proposals,
        )

    def adopt(given: HomeBundle) -> None:
        try:
            files = [(f.id, base64.b64decode(f.data, validate=True)) for f in given.sources]
        except (binascii.Error, ValueError) as error:
            raise HTTPException(422, "Underlagen i flytten gick inte att läsa.") from error
        plans.adopt(given.created, given.draft, files, given.proposals)

    def admin(session: str | None, authorization: str | None) -> None:
        require_admin(login, session, authorization)

    def known(meet: str, key: str) -> None:
        if links.follower(meet, key, datetime.now(UTC)) is None:
            raise HTTPException(401, "Molnhubben känner inte den här Pi:n.")

    # --- In the cloud: Koppla en Pi (SYNK-02) ------------------------------------------------

    @routes.post("/api/sync/1/meets/{meet}/code", status_code=201)
    def code(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Koppla en Pi: a six-digit code for the meet, for 15 minutes."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            plans.draft(meet)
        except PlanningError as error:
            _fail(error)
        if not home(meet).here:
            raise HTTPException(409, f"Träffens hem är {home(meet).hub_name}. Koppla Pi:n där.")
        return links.new_code(meet, datetime.now(UTC)).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/followers")
    def followers(meet: str, response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return [f.model_dump(mode="json") for f in links.followers(meet)]

    @routes.post("/api/sync/1/meets/{meet}/followers/{hub_id}/revoke", status_code=204)
    def revoke(
        meet: str, hub_id: str, session: SessionCookie = None, authorization: Authorization = None
    ) -> None:
        """Koppla bort en Pi: its key no longer works here."""
        admin(session, authorization)
        if not links.revoke(meet, hub_id):
            raise HTTPException(404, "Pi:n följer inte träffen.")

    @routes.post("/api/sync/1/link")
    def link(request: LinkRequest, response: Response) -> dict[str, Any]:
        """A Pi gives its code and gets the meet and a key of its own."""
        response.headers["Cache-Control"] = "no-store"
        if PROTOCOL not in request.hello.protocols:
            raise HTTPException(426, f"Hubben talar {PROTOCOL}.")
        try:
            meet, key = links.redeem(request.code, request.hello, datetime.now(UTC))
            name = plans.draft(meet).meet.name
        except (LinkError, PlanningError) as error:
            _fail(error)
        return Link(meet=meet, meet_name=name, key=key, hello=hello()).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/versions")
    async def listed(
        meet: str,
        response: Response,
        known_mark: Annotated[str, Query(alias="known", max_length=64)] = "",
        wait: Annotated[float, Query(ge=0, le=MAX_WAIT)] = 0,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """The meet's versions, as soon as they differ from what the Pi knows (long-poll)."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        await run_in_threadpool(known, meet, _key(authorization))
        until = time.monotonic() + wait
        while True:
            found = [
                v.model_dump(mode="json") for v in await run_in_threadpool(versions.versions, meet)
            ]
            now_mark = mark(found)
            if now_mark != known_mark or time.monotonic() >= until:
                break
            await asyncio.sleep(POLL)
        try:
            name = (await run_in_threadpool(plans.draft, meet)).meet.name
        except PlanningError as error:
            _fail(error)
        return VersionList.model_validate(
            {
                "meet": meet,
                "meet_name": name,
                "versions": found,
                "mark": now_mark,
                "home": await run_in_threadpool(home, meet),
            }
        ).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/versions/{number}")
    def version(
        meet: str,
        number: int,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> Response:
        """A version as the bytes it was published as: the follower checks the checksum."""
        _protocol(spoken)
        known(meet, _key(authorization))
        try:
            kept, data = versions.stored(meet, number)
        except SyncError as error:
            _fail(error)
        return Response(
            data,
            media_type="application/json",
            headers={"Cache-Control": "no-store", "X-Checksum": kept.checksum},
        )

    @routes.get("/api/sync/1/meets/{meet}/files/{sha256}")
    def version_file(
        meet: str,
        sha256: str,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> Response:
        """A file one of the meet's versions carries beside its package (an attachment, such as
        CAD's assembly with its modules, CAD-12, or the instructions as PDF), by its checksum:
        only to a Pi that follows the meet, and only a file a version names."""
        _protocol(spoken)
        known(meet, _key(authorization))
        named = {
            a.sha256: a.media_type
            for v in versions.versions(meet)
            for a in versions.package(meet, v.number).attachments
        }
        kept = plans.file(sha256) if sha256 in named else None
        if kept is None:
            raise HTTPException(404, "Filen finns inte i träffens versioner.")
        return Response(
            kept[1],
            media_type="application/octet-stream",
            headers={"Cache-Control": "no-store", "X-Media-Type": kept[0]},
        )

    # --- Under träffen: molnet följer Pi:n live (SYNK-04, SYNK-14, DRIFT-12) -------------------

    @routes.post("/api/sync/1/meets/{meet}/runs")
    def runs(
        meet: str,
        sent: RunEvents,
        response: Response,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """The Pi's drift events for the run it leads, kept as they came. A driftändring
        becomes a proposal in Planering here, and the answers go back down (4.4)."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        pi = links.follower(meet, _key(authorization), datetime.now(UTC))
        if pi is None:
            raise HTTPException(401, "Molnhubben känner inte den här Pi:n.")
        try:
            kept, _ = versions.stored(meet, sent.version)
        except SyncError as error:
            _fail(error)
        if kept.checksum != sent.package:
            raise HTTPException(409, "Pi:n kör en annan version än den molnhubben har.")
        store = running.mirror(meet, sent.version)
        try:
            ack, taken = store.receive(sent.run, pi.hub_name, sent.events)
        except Refused as error:
            if error.reason == Reason.ALREADY_LEADER:
                # Ta över i molnet (H9): the Pi follows from here.
                raise HTTPException(410, "Molnhubben har tagit över träffen.") from error
            raise HTTPException(409, "Molnhubben kör själv den körningen.") from error
        for event in taken if home(meet).here else []:
            if event.kind == drift.EventKind.CHANGE_MADE:
                made = drift.ChangeMade.model_validate(event.data)
                plans.propose(meet, sent.version, made.change_id, made.change, made.train_number)
            elif event.kind == drift.EventKind.CHANGE_DROPPED:
                plans.withdraw(meet, drift.ChangeRef.model_validate(event.data).change_id)
        if running.meet == meet:
            running.follow(meet, sent.version)
        return RunAck(run=sent.run, ack=ack, answers=plans.answers(meet)).model_dump(mode="json")

    @routes.get("/api/sync/1/meets/{meet}/runs/{run}/events")
    def feed(
        meet: str,
        run: str,
        response: Response,
        version: Annotated[int, Query(ge=1)],
        after: Annotated[int, Query(ge=0)] = 0,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """The run this hub leads after taking over, for the Pi that follows from here (H9)."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        pi(meet, authorization)
        store = running.mirror(meet, version)
        try:
            found = store.events_after(run, after)[:500]
        except MissingRun as error:
            raise HTTPException(404, "Körningen finns inte här.") from error
        return RunFeed(leader=hello().hub_name, events=found).model_dump(mode="json")

    # --- Reläet (SYNK-11): the Pi fetches the calls for it and answers them -------------------

    @routes.get("/api/sync/1/meets/{meet}/relay")
    async def relay_calls(
        meet: str,
        response: Response,
        wait: Annotated[float, Query(ge=0, le=MAX_WAIT)] = 0.0,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """The calls from phones and the cloud's TKL to this Pi, with long-poll."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        found = await run_in_threadpool(pi, meet, authorization)
        calls = await relay.take(found.hub_id, wait)
        return RelayCalls(calls=calls).model_dump(mode="json")

    @routes.post("/api/sync/1/meets/{meet}/relay", status_code=204)
    async def relay_answer(
        meet: str,
        answer: RelayAnswer,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> Response:
        """The Pi's answer to one call, for the client that waits for it."""
        _protocol(spoken)
        found = await run_in_threadpool(pi, meet, authorization)
        if not relay.answer(found.hub_id, answer):
            raise HTTPException(410, "Ingen väntar på svaret längre.")
        return Response(status_code=204)

    # --- The meets molnets TKL may join, and how (TKLMOLN-03, TKLMOLN-06) --------------------

    def way_to(meet: str) -> tuple[RelayWay, str | None, str | None]:
        """Directly when this hub leads the meet; through the relay to the Pi that leads it,
        on the connection the Pi already has open; otherwise not now."""
        if running.meet == meet and running.leading() is not None:
            return RelayWay.HERE, hello().hub_name, None
        led: str | None = None
        followed = running.following()
        if followed is not None and followed.meet == meet:
            leader = running.mirror(followed.meet, followed.version).leader(followed.run)
            led = leader[0] if leader is not None else None
        live = [f for f in links.followers(meet) if relay.connected(f.hub_id)]
        live.sort(key=lambda f: f.heard or f.linked, reverse=True)
        pick = next((f for f in live if f.hub_name == led), live[0] if live else None)
        if pick is None:
            return RelayWay.NONE, None, None
        return RelayWay.RELAY, pick.hub_name, f"/relay/{pick.hub_id}"

    @routes.get("/api/sync/1/relay/meets")
    def relay_meets(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        """The meets the one TKL's token from ID names may join (#78 del b): the meets of the
        person's clubs in ID that this hub has, each with the way there. Asked of ID at every
        call; nothing is kept."""
        response.headers["Cache-Control"] = "no-store"
        who = owner_of(authorization)
        if meets_of is None:
            return RelayMeets().model_dump(mode="json")
        in_id = {str(m.id): m for m in meets_of(who)}
        found = []
        for summary in plans.meets():
            meet = summary.meet
            joined = in_id.get(str(meet.id_meet)) if meet.id_meet else None
            if joined is None:
                continue
            way, hub_name, path = way_to(meet.id)
            found.append(
                RelayMeet(
                    meet=meet.id,
                    meet_name=meet.name,
                    club_name=joined.club_name,
                    starts_on=joined.starts_on,
                    ends_on=joined.ends_on,
                    way=way,
                    hub_name=hub_name,
                    relay=path,
                )
            )
        return RelayMeets(meets=found[:200]).model_dump(mode="json")

    # --- Push (F20): the Pi's notices go out from here ---------------------------------------

    @routes.post("/api/sync/1/meets/{meet}/push", status_code=204)
    def push(
        meet: str,
        batch: PushBatch,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> Response:
        """The Pi has no key to Apple's service: it sends its notices here, and they go out the
        way this hub's own do (SYNK-11). Nothing is kept."""
        _protocol(spoken)
        pi(meet, authorization)
        if pushes is not None:
            pushes.own.send(batch.pushes)
        return Response(status_code=204)

    @routes.get("/api/hub/push")
    def push_status(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Which way the notices go, and the last ones the pretend service took."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        if pushes is None:
            return {"service": "none", "recent": []}
        return {"service": pushes.name, "recent": pushes.fake.recent()}

    # --- Stationspaketen (SYNK-06, SYNK-18, H71): the owner's private versions ----------------

    def owner_of(authorization: str | None) -> str:
        asked = owners or NoOwners()
        found = asked.owner(authorization)
        if found is None and isinstance(asked, NoOwners):
            raise HTTPException(
                403,
                "Synken av stationspaket kräver inloggning med TrainMeet ID, och den här hubben "
                "har ingen (SYNK-30).",
            )
        if found is None:
            raise HTTPException(401, "Logga in med TrainMeet ID i TKL för att spara i molnet.")
        return found

    def kept() -> Stations:
        if stations is None:
            raise HTTPException(404, "Den här hubben har inga stationspaket.")
        return stations

    @routes.post("/api/sync/1/stations/{station}/versions", status_code=201)
    async def save_station(
        station: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")],
        request: Request,
        response: Response,
        base: Annotated[int, Query(ge=0)],
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """A new version of the whole package, on top of base (the latest). The body is the
        package as TKL wrote it; it is kept as it came."""
        response.headers["Cache-Control"] = "no-store"
        who = owner_of(authorization)
        data = await request.body()
        try:
            package = StationPackage.model_validate_json(data)
        except ValidationError as error:
            raise HTTPException(422, "Stationspaketet gick inte att läsa.") from error
        if package.station_id != station:
            raise HTTPException(422, "Paketet hör till en annan station.")
        try:
            saved = await run_in_threadpool(kept().save, who, base, data)
        except Behind as error:
            raise HTTPException(
                409, str(error), headers={"TrainMeet-Latest": str(error.latest)}
            ) from error
        except StationError as error:
            raise HTTPException(error.status, str(error)) from error
        return saved.model_dump(mode="json")

    @routes.get("/api/sync/1/stations")
    def owned_stations(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        """Dina stationer (TKL5, TKLMOLN-02): the latest version of each of the owner's
        stations, for TKL in the cloud. Only the owner's own."""
        response.headers["Cache-Control"] = "no-store"
        who = owner_of(authorization)
        return StationList(stations=kept().owned(who)).model_dump(mode="json")

    @routes.get("/api/sync/1/stations/{station}/versions")
    def station_versions(
        station: str, response: Response, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        who = owner_of(authorization)
        try:
            found = kept().versions(who, station)
        except StationError as error:
            raise HTTPException(error.status, str(error)) from error
        return StationVersions(station_id=station, versions=found).model_dump(mode="json")

    @routes.get("/api/sync/1/stations/{station}/versions/{number}")
    def station_package(
        station: str,
        number: Annotated[int, Path(ge=1)],
        authorization: Authorization = None,
    ) -> Response:
        """The whole package, as it came: only to its owner."""
        who = owner_of(authorization)
        try:
            data = kept().package(who, station, number)
        except StationError as error:
            raise HTTPException(error.status, str(error)) from error
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-store"})

    # --- Träffens hem (H35, SYNK-03, SYNK-16) -------------------------------------------------

    def pi(meet: str, authorization: str | None) -> FollowerInfo:
        found = links.follower(meet, _key(authorization), datetime.now(UTC))
        if found is None:
            raise HTTPException(401, "Molnhubben känner inte den här Pi:n.")
        return found

    @routes.get("/api/sync/1/meets/{meet}/home")
    def where(meet: str, response: Response) -> dict[str, Any]:
        """Var träffens hem är, för den som tittar."""
        response.headers["Cache-Control"] = "no-store"
        return home(meet).model_dump(mode="json")

    @routes.post("/api/sync/1/meets/{meet}/home/take")
    def take(
        meet: str,
        response: Response,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """Ta hem träffen till Pi:n: the home moves at once, and the Pi gets what moves with it.
        Asked again by the same Pi, it gets the same, so a move cut off half way is done again."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        asking = pi(meet, authorization)
        now = home(meet)
        if not now.here and now.hub_id != asking.hub_id:
            raise HTTPException(409, f"Träffens hem är {now.hub_name}.")
        generation = now.generation if now.hub_id == asking.hub_id else now.generation + 1
        try:
            moving = bundle(meet, generation)
        except PlanningError as error:
            _fail(error)
        homes.move(meet, asking.hub_id, asking.hub_name, generation)
        return moving.model_dump(mode="json")

    @routes.post("/api/sync/1/meets/{meet}/home/back")
    def back(
        meet: str,
        given: HomeBundle,
        response: Response,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """Lämna tillbaka: the Pi hands the meet back, with what it changed."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        asking = pi(meet, authorization)
        now = home(meet)
        if now.hub_id != asking.hub_id or given.generation != now.generation:
            raise HTTPException(409, f"Träffens hem är {now.hub_name}.")
        adopt(given)
        me = hello()
        homes.move(meet, me.hub_id, me.hub_name, now.generation + 1)
        return home(meet).model_dump(mode="json")

    @routes.post("/api/sync/1/meets/{meet}/versions")
    def sent(
        meet: str,
        given: SentVersion,
        response: Response,
        authorization: Authorization = None,
        spoken: SyncHeader = None,
    ) -> dict[str, Any]:
        """A version the home published, here to be followed (SYNK-10). Only from the home."""
        response.headers["Cache-Control"] = "no-store"
        _protocol(spoken)
        asking = pi(meet, authorization)
        now = home(meet)
        if now.hub_id != asking.hub_id or given.generation != now.generation:
            raise HTTPException(409, f"Träffens hem är {now.hub_name}.")
        if given.version.meet != meet:
            raise HTTPException(409, "Versionen hör till en annan träff.")
        try:
            versions.receive(given.version, given.package.encode())
        except SyncError as error:
            _fail(error)
        return given.version.model_dump(mode="json")

    @routes.post("/api/sync/1/meets/{meet}/home/reclaim")
    def reclaim(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Ta tillbaka hem hit, when the Pi that has it is gone: what it changed and never
        handed back stays there."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        now = home(meet)
        if now.here:
            raise HTTPException(409, "Träffens hem är redan här.")
        me = hello()
        homes.move(meet, me.hub_id, me.hub_name, now.generation + 1)
        return home(meet).model_dump(mode="json")

    # --- On the Pi: Den här hubben → Molnet ---------------------------------------------------

    def clouds() -> list[dict[str, Any]]:
        counts = {meet: len(found) for meet, found in versions.meets().items()}
        return [
            c.model_copy(
                update={"home_here": home(c.meet).here and home(c.meet).generation > 0}
            ).model_dump(mode="json")
            for c in links.clouds(counts)
        ]

    @routes.get("/api/hub/cloud")
    def cloud(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """The meets the Pi follows in the cloud, and how the synk goes."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        return clouds()

    @routes.post("/api/hub/cloud")
    def connect(
        change: CloudLinkChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """Koppla till molnet: the cloud's address and the code from it."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            follower.link(change.address, change.code)
        except LinkError as error:
            _fail(error)
        return clouds()

    @routes.post("/api/hub/cloud/{meet}/disconnect")
    def disconnect(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """Koppla bort: the Pi no longer follows the meet. Its versions stay."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        if not links.forget(meet):
            raise HTTPException(404, "Pi:n följer inte den träffen.")
        return clouds()

    @routes.post("/api/hub/cloud/{meet}/take")
    def take_home(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """Ta hem träffen hit (H35): the Pi becomes the meet's home before the meet."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            status, answer = follower.send(meet, f"/api/sync/1/meets/{meet}/home/take", b"{}")
        except LinkError as error:
            _fail(error)
        if status != 200:
            raise HTTPException(409, _said(answer) or "Molnhubben lämnade inte över träffen.")
        given = HomeBundle.model_validate_json(answer)
        adopt(given)
        me = hello()
        homes.move(meet, me.hub_id, me.hub_name, given.generation)
        return clouds()

    @routes.post("/api/hub/cloud/{meet}/back")
    def hand_back(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> list[dict[str, Any]]:
        """Lämna tillbaka till molnet: after the meet, with what was changed here."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        now = home(meet)
        if not now.here or now.generation == 0:
            raise HTTPException(409, "Träffens hem är inte här.")
        # The versions published here go up first, so nothing is left behind.
        reach = next((r for r in links.reaches() if r.meet == meet), None)
        if reach is not None:
            try:
                follower.follow(reach, wait=0)
            except Exception as error:
                raise HTTPException(409, "Molnhubben svarar inte. Försök igen.") from error
        try:
            body = bundle(meet, now.generation).model_dump_json().encode()
            status, answer = follower.send(meet, f"/api/sync/1/meets/{meet}/home/back", body)
        except (LinkError, PlanningError) as error:
            _fail(error)
        if status != 200:
            raise HTTPException(409, _said(answer) or "Molnhubben tog inte emot träffen.")
        moved = Home.model_validate_json(answer)
        homes.move(meet, moved.hub_id, moved.hub_name, moved.generation)
        return clouds()

    return routes


def _said(answer: bytes) -> str | None:
    try:
        detail = json.loads(answer).get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) else None
