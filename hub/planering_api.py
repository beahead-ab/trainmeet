"""Planeringens API (steg 4a): meets, sources, the draft, the check and the versions.

Everyone may look (S1, PLAN-37); everything that changes something needs the hub's PIN or a
role at the meet in TrainMeet ID (PLAN-19, hub/rights.py): Arrangör plans, the Arrangör with Får
publicera publishes, and only Administratör withdraws a version (PLAN-24).

A source is sent as the file's bytes with its name in the address, so no form library is needed.
The file is read by Integrationer and kept as it came.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Final, Literal, NoReturn
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from contracts import planning
from contracts.meet import MapPoint, Meet
from contracts.station_outside import StationOutside
from contracts.tokens import TOKENS_PER_PAGE, TokenOwner, TokenOwnerKind
from hub.hubben import Authorization, SessionCookie, service_of, session_of
from hub.id_roles import PLANS, publishes, roles_of, withdraws
from hub.id_tokens import IdTokens
from hub.local import PERSON, LocalLogin
from hub.rights import NOT_LOGGED_IN, Rights
from integrationer import (
    ai,
    derive,
    graph_picture,
    planning_json,
    scanned,
    station_lists,
    track_picture,
)
from planering import export
from planering.store import Planning, PlanningError
from synk.home import Homes
from synk.link import Links
from synk.store import SyncError, Versions

MAX_UPLOAD: Final = planning_json.MAX_BYTES
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _fail(error: PlanningError | SyncError) -> NoReturn:
    raise HTTPException(error.status, str(error)) from error


def filename(name: str) -> str:
    """The file's own name, without folders or control characters."""
    base = PureWindowsPath(PurePosixPath(name).name).name
    return _CONTROL.sub("", base).strip()[:200] or "underlag"


def router(
    store: Planning,
    kept: Versions,
    links: Links,
    homes: Homes,
    me: Callable[[], tuple[str, str]],
    login: LocalLogin,
    published: Callable[[str], None] = lambda meet: None,
    rights: Rights | None = None,
    tokens: IdTokens | None = None,
) -> APIRouter:
    """rights: who may plan which meet: the hub's PIN, or Administratör and Arrangör at the
    meet in TrainMeet ID (PLAN-19, #78). tokens: TrainMeets AI through the meter in ID, in a
    cloud hub with ID's API (#79)."""
    may = rights if rights is not None else Rights(login)

    def at_home(request: Request) -> None:
        """Träffens hem (H35, SYNK-16): a meet is changed only where its home is. Elsewhere it
        is looked at, and its versions come from the home."""
        meet = request.path_params.get("meet")
        if request.method != "POST" or not meet:
            return
        hub_id, hub_name = me()
        home = homes.home(meet, hub_id, hub_name)
        if not home.here:
            raise HTTPException(
                409, f"Träffens hem är {home.hub_name}. Planera där, eller ta hem träffen hit."
            )

    routes = APIRouter(prefix="/api/planering/1", dependencies=[Depends(at_home)])

    def id_meet_of(meet: str) -> UUID | None:
        try:
            return store.draft(meet).meet.id_meet
        except PlanningError:
            return None

    def planner(meet: str, session: str | None, authorization: str | None) -> None:
        """The PIN, or Administratör or Arrangör at the meet in TrainMeet ID (PLAN-19)."""
        may.require_planner(session_of(session, authorization), id_meet_of(meet))

    def roles_by_meet(token: str | None) -> dict[str, set[str]] | None:
        """The roles at each ID meet of the one logged in with ID, or None for the hub's PIN."""
        if login.valid(token):
            return None
        person = login.person(token) if login.role(token) == PERSON else None
        if person is None or may.roles is None:
            return {}
        try:
            found = may.roles.meets(person.id)
        except HTTPException:
            return {}
        return {str(m.id): roles_of(m) for m in found}

    @routes.get("/meets")
    def meets(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """The meets with their versions, which Synk keeps (SYNK-08), and the meets this hub
        follows in the cloud (SYNK-02): those are planned there, and run here. may_plan,
        may_publish and may_withdraw say what the one asking may do at each (PLAN-19,
        PLAN-24)."""
        response.headers["Cache-Control"] = "no-store"
        published = kept.meets()
        away = homes.elsewhere(me()[0])
        held = roles_by_meet(session_of(session, authorization))

        def rights(meet: Meet) -> dict[str, bool]:
            if held is None:
                return {"may_plan": True, "may_publish": True, "may_withdraw": True}
            roles = held.get(str(meet.id_meet), set()) if meet.id_meet else set()
            return {
                "may_plan": bool(roles & PLANS),
                "may_publish": publishes(roles),
                "may_withdraw": withdraws(roles),
            }

        planned = [
            summary.model_copy(
                update={
                    "versions": published.get(summary.meet.id, []),
                    "home": away.get(summary.meet.id),
                    **rights(summary.meet),
                }
            )
            for summary in store.meets()
        ]
        mine = {summary.meet.id for summary in planned}
        followed = []
        for cloud in links.clouds({}):
            found = published.get(cloud.meet, [])
            if cloud.meet in mine or not found:
                continue
            meet = kept.package(cloud.meet, found[-1].number).meet
            followed.append(planning.MeetSummary(meet=meet, versions=found, home=cloud.cloud_name))
        return [summary.model_dump(mode="json") for summary in [*followed, *planned]]

    @routes.post("/meets", status_code=201)
    def create(
        new: planning.NewMeet,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        token = session_of(session, authorization)
        if not login.valid(token):
            # Someone logged in with TrainMeet ID makes the meet from a meet in ID they plan
            # (ID10, PLAN-19); the hub's meet is linked to it, once.
            if login.role(token) != PERSON:
                raise HTTPException(401, NOT_LOGGED_IN)
            if new.id_meet is None:
                raise HTTPException(422, "Välj träffen i TrainMeet ID som träffen hör till.")
            may.require_planner(token, new.id_meet)
            if any(s.meet.id_meet == new.id_meet for s in store.meets()):
                raise HTTPException(409, "Den träffen i TrainMeet ID finns redan i hubben.")
        try:
            return store.create(new).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/id-meets")
    def id_meets(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> list[dict[str, Any]]:
        """Ny träff for someone logged in with TrainMeet ID: the meets in ID they plan, as the
        club's admin or the organizer (ID10, PLAN-19), and the hub's meet made from each."""
        response.headers["Cache-Control"] = "no-store"
        token = session_of(session, authorization)
        person = login.person(token) if login.role(token) == PERSON else None
        if person is None or may.roles is None:
            return []
        made = {str(s.meet.id_meet): s.meet.id for s in store.meets() if s.meet.id_meet}
        return [
            planning.IdMeetChoice(
                id=m.id,
                name=m.name,
                club_name=m.club_name,
                starts_on=m.starts_on,
                ends_on=m.ends_on,
                hub_meet=made.get(str(m.id)),
            ).model_dump(mode="json")
            for m in may.roles.meets(person.id)
            if roles_of(m) & PLANS
        ]

    @routes.get("/meets/{meet}")
    def draft(meet: str, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.draft(meet).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/sources", status_code=201)
    async def add_source(
        meet: str,
        request: Request,
        response: Response,
        name: str = Query(min_length=1, max_length=300),
        transcribe: Literal["lists", "picture", "graph"] | None = Query(default=None),
        ai_by: Literal["own", "trainmeet"] = Query(default="own", alias="ai"),
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Lägg till underlag: the file's bytes in the body, its name in the address. The file
        is read and what it would change is shown; nothing changes until it is laid in. A
        scanned file first answers 202 with the pages to transcribe (IMPORT-05); sent again with
        transcribe, the hub's own AI writes them down: as station lists, or as the track
        picture. With ai=trainmeet TrainMeets AI writes them down through the meter in ID
        instead, which the planner chose after being told where and who pays (TK12, #79)."""
        response.headers["Cache-Control"] = "no-store"
        await run_in_threadpool(planner, meet, session, authorization)
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, f"Filen är större än {MAX_UPLOAD // (1024 * 1024)} MB.")
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            raise HTTPException(422, "Filen är tom.")
        if scanned.needs_ai(data, filename(name)):
            token = session_of(session, authorization)
            asked = await run_in_threadpool(
                _scanned, meet, filename(name), data, transcribe, token, ai_by
            )
            if isinstance(asked, planning.AiPages):
                response.status_code = 202
                return asked.model_dump(mode="json")
            return asked
        return await run_in_threadpool(_read, meet, filename(name), data)

    def _read(meet: str, name: str, data: bytes) -> dict[str, Any]:
        lower = name.casefold()
        lists = station_lists.is_lists(name)
        drawn = lower.endswith(".pdf")
        if not (
            lists
            or drawn
            or lower.endswith((".json", ".json.gz", ".gz"))
            or data[:2] == b"\x1f\x8b"
        ):
            raise HTTPException(
                415,
                "Den filtypen läses inte än. Lägg till Tellurians planeringsfil (JSON), "
                "stationslistorna (ODT, ZIP, Excel, CSV eller PDF) eller banbilden (PDF).",
            )
        try:
            current = store.draft(meet)
        except PlanningError as error:
            _fail(error)
        digest = hashlib.sha256(data).hexdigest()
        if _is_outside(data):
            return _station(meet, name, data, current, digest)
        if drawn and track_picture.is_picture(data):
            return _picture(meet, name, data, current, digest)
        if lists or drawn:
            return _lists(meet, name, data, current, digest)
        source = planning.Source(
            id=f"u-{digest[:12]}",
            kind=planning.SourceKind.PLANNING_JSON,
            filename=name,
            size=len(data),
            sha256=digest,
            level=planning_json.LEVEL,
            added=datetime.now(UTC),
        )
        try:
            result = planning_json.read(data, meet=current.meet, source=source)
        except planning_json.PlanError as error:
            raise HTTPException(422, str(error)) from error
        added = next(
            (s for s in current.sources if s.kind == planning.SourceKind.STATION_LISTS), None
        )
        try:
            if added is not None and (found := _stored_lists(meet, added)) is not None:
                result = station_lists.judged_anew(found, result)
            return store.preview(meet, source, data, result).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    def _station(
        meet: str, name: str, data: bytes, current: planning.Draft, digest: str
    ) -> dict[str, Any]:
        """Stationens utsida från TKL (IMPORT-10): its tracks and exits, to couple to a place
        in Data. The plan's track names that differ become questions (IMPORT-18)."""
        try:
            outside = StationOutside.model_validate_json(data)
        except ValueError as error:
            raise HTTPException(422, "Stationens utsida gick inte att läsa.") from error
        source = planning.Source(
            id=f"u-{digest[:12]}",
            kind=planning.SourceKind.STATION_OUTSIDE,
            filename=name,
            size=len(data),
            sha256=digest,
            level=current.report.level if current.report else 4,
            added=datetime.now(UTC),
        )
        try:
            store.stage_station(meet, source, data)
        except PlanningError as error:
            _fail(error)
        before = next(
            (s for s in current.stations if s.outside.station_id == outside.station_id), None
        )
        told = (
            "Samma utsida som redan finns; inget ändras."
            if before is not None and before.outside == outside
            else f"Version {before.version + 1} av stationen ersätter version {before.version}."
            if before is not None
            else "Koppla stationen till en driftplats i Data."
        )
        report = planning.ImportReport(
            source=source.id,
            level=source.level,
            notes=[
                f"Stationen {outside.name}: {len(outside.tracks)} spår och "
                f"{len(outside.exits)} utfarter. {told}"
            ],
        )
        return planning.ImportPreview(source=source, report=report, first=False).model_dump(
            mode="json"
        )

    def _stored_lists(meet: str, source: planning.Source) -> station_lists.Lists | None:
        """Lists already among the sources, read again from the file as it came: with code, or
        from the saved transcriptions of a scanned file."""
        _, body = store.source_file(meet, source.id)
        try:
            if scanned.needs_ai(body, source.filename):
                pages = scanned.pages(body, source.filename)
                saved = {p.digest: store.transcript(p.digest) for p in pages}
                if any(text is None for text in saved.values()):
                    return None
                return scanned.lists(source.filename, pages, lambda p: saved[p.digest] or "")
            return station_lists.read(body, source.filename)
        except station_lists.ListError:
            return None

    def _photo(page: scanned.Page) -> str:
        """The key a photo's transcription as the track picture is kept by."""
        return hashlib.sha256(
            track_picture.PHOTO_VERSION.encode() + b"\0" + page.image.data
        ).hexdigest()

    def _graph_key(page: scanned.Page) -> str:
        """The key a page's transcription as the graph is kept by."""
        version = graph_picture.VERSION.encode()
        return hashlib.sha256(version + b"\0" + page.image.data).hexdigest()

    def _graphed(
        meet: str, current: planning.Draft
    ) -> tuple[list[graph_picture.Line] | None, planning.Source | None]:
        """The graph already among the sources, from its saved transcription."""
        graphed = next(
            (s for s in current.sources if s.kind == planning.SourceKind.GRAPH_PICTURE), None
        )
        if graphed is None:
            return None, None
        _, body = store.source_file(meet, graphed.id)
        try:
            texts = [store.transcript(_graph_key(p)) for p in scanned.pages(body, graphed.filename)]
            if any(text is None for text in texts):
                return None, None
            return [line for text in texts for line in graph_picture.lines(text or "")], graphed
        except (graph_picture.GraphError, station_lists.ListError):
            return None, None

    def _scanned(
        meet: str,
        name: str,
        data: bytes,
        transcribe: Literal["lists", "picture", "graph"] | None,
        token: str | None = None,
        ai_by: Literal["own", "trainmeet"] = "own",
    ) -> planning.AiPages | dict[str, Any]:
        """Skannade stationslistor (4c2): the pages to write down first, then, asked to, the
        hub's own AI writes down the pages not already written, and code reads the rows. Each
        page's transcription is kept, so the same file never costs twice (IMPORT-15)."""
        try:
            current = store.draft(meet)
            pages = scanned.pages(data, name)
        except station_lists.ListError as error:
            raise HTTPException(422, str(error)) from error
        except PlanningError as error:
            _fail(error)
        if transcribe == "picture":
            pages = pages[:1]
            pages = [scanned.Page(p.number, p.image, _photo(p)) for p in pages]
        elif transcribe == "graph":
            pages = [scanned.Page(p.number, p.image, _graph_key(p)) for p in pages]
        saved = {p.digest: text for p in pages if (text := store.transcript(p.digest))}
        setting = login.ai()
        left = len([p for p in pages if p.digest not in saved])
        offered = _trainmeet_ai(meet, token, left)
        if transcribe is None:
            return planning.AiPages(
                filename=name,
                pages=len(pages),
                saved=len(saved),
                model=setting.model if setting else None,
                tokens=scanned.tokens([p for p in pages if p.digest not in saved]),
                trainmeet_ai=offered[0] if offered else None,
            )
        metered = ai_by == "trainmeet" and left > 0
        if metered and offered is None:
            raise HTTPException(
                422,
                "TrainMeets AI finns i molnhubben för den som är inloggad med TrainMeet ID.",
            )
        if metered and offered is not None and offered[0].available < offered[0].price:
            raise HTTPException(
                402,
                f"Saldot räcker inte: {offered[0].available} tokens kvar, {offered[0].price} "
                "behövs. Köp fler eller använd egen AI.",
            )
        if left and not metered and setting is None:
            raise HTTPException(
                422,
                "Den här filen behöver AI. Koppla in egen AI under Inställningar → Den här "
                "hubben → AI först.",
            )

        def transcript(page: scanned.Page) -> str:
            if page.digest in saved:
                return saved[page.digest]
            prompt = (
                track_picture.PHOTO_PROMPT
                if transcribe == "picture"
                else graph_picture.PROMPT
                if transcribe == "graph"
                else scanned.PROMPT
            )
            if metered:
                assert offered is not None and tokens is not None
                person, owner = offered[1], offered[2]
                read = tokens.read(
                    person, owner, prompt, page.image, f"En sida i importen: {name}", 8192
                )
                store.keep_transcript(page.digest, read.model, read.text)
                return read.text
            assert setting is not None
            text = ai.ask(service_of(setting), prompt, [page.image], max_tokens=8192)
            store.keep_transcript(page.digest, setting.model, text)
            return text

        digest = hashlib.sha256(data).hexdigest()
        if transcribe == "picture":
            try:
                picture = track_picture.from_photo(
                    transcript(pages[0]), *scanned.dimensions(pages[0].image)
                )
            except ai.AiError as error:
                raise HTTPException(502, f"Avskriften stannade: {error}") from None
            except (track_picture.PictureError, station_lists.ListError) as error:
                raise HTTPException(422, str(error)) from error
            return _picture(meet, name, data, current, digest, picture)
        if transcribe == "graph":
            try:
                found_lines = [
                    line for page in pages for line in graph_picture.lines(transcript(page))
                ]
            except ai.AiError as error:
                raise HTTPException(502, f"Avskriften stannade: {error}") from None
            except graph_picture.GraphError as error:
                raise HTTPException(422, str(error)) from error
            return _graph(meet, name, data, current, digest, found_lines)
        try:
            found = scanned.lists(name, pages, transcript)
        except ai.AiError as error:
            raise HTTPException(502, f"Avskriften stannade: {error}") from None
        except station_lists.ListError as error:
            raise HTTPException(422, str(error)) from error
        return _lists(meet, name, data, current, digest, found)

    def _trainmeet_ai(
        meet: str, token: str | None, pages: int
    ) -> tuple[planning.TrainMeetAi, str, TokenOwner] | None:
        """TrainMeets AI for the one who asks (#79): in the cloud hub with ID's API, to someone
        logged in with TrainMeet ID. The meet's owner pays (TK16): the club of the meet in ID,
        or else the person. None where it is not offered."""
        if tokens is None or may.roles is None or login.role(token) != PERSON:
            return None
        person = login.person(token)
        if person is None:
            return None
        owner = TokenOwner(kind=TokenOwnerKind.PERSON, id=UUID(person.id))
        id_meet = id_meet_of(meet)
        if id_meet is not None:
            club = next((m for m in may.roles.meets(person.id) if m.id == id_meet), None)
            if club is not None:
                owner = TokenOwner(kind=TokenOwnerKind.CLUB, id=club.club)
        balance = tokens.balance(person.id, owner)
        offer = planning.TrainMeetAi(
            payer=balance.title, available=balance.available, price=TOKENS_PER_PAGE * pages
        )
        return offer, person.id, owner

    def _lists(
        meet: str,
        name: str,
        data: bytes,
        current: planning.Draft,
        digest: str,
        given: station_lists.Lists | None = None,
    ) -> dict[str, Any]:
        """Stationslistorna (4c1): with the planning file in the draft, each list is judged
        against it, row by row (IMPORT-27). Without it, the lists build the draft: trains,
        places, sections and place kinds derived, marked osäkra (IMPORT-17)."""
        planned = current.package is not None and any(
            s.kind == planning.SourceKind.PLANNING_JSON for s in current.sources
        )
        source = planning.Source(
            id=f"u-{digest[:12]}",
            kind=planning.SourceKind.STATION_LISTS,
            filename=name,
            size=len(data),
            sha256=digest,
            level=station_lists.LEVEL,
            added=datetime.now(UTC),
        )
        try:
            found = given or station_lists.read(data, name)
            if planned and current.package is not None:
                result = station_lists.judge(found, plan=current.package, source=source)
            else:
                picture, drawn = _drawn(meet, current)
                graph, graphed = _graphed(meet, current)
                result = derive.draft(
                    found,
                    meet=current.meet,
                    source=source,
                    picture=picture,
                    drawn=drawn,
                    graph=graph,
                    graphed=graphed,
                )
        except station_lists.ListError as error:
            raise HTTPException(422, str(error)) from error
        try:
            return store.preview(meet, source, data, result).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    def _drawn(
        meet: str, current: planning.Draft
    ) -> tuple[track_picture.Picture | None, planning.Source | None]:
        """The track picture already among the sources, read again from the file as it came."""
        drawn = next(
            (s for s in current.sources if s.kind == planning.SourceKind.TRACK_PICTURE), None
        )
        if drawn is None:
            return None, None
        _, body = store.source_file(meet, drawn.id)
        try:
            if scanned.needs_ai(body, drawn.filename):
                page = scanned.pages(body, drawn.filename)[0]
                text = store.transcript(_photo(page))
                if text is None:
                    return None, None
                size = scanned.dimensions(page.image)
                return track_picture.from_photo(text, *size), drawn
            return track_picture.read(body), drawn
        except (track_picture.PictureError, station_lists.ListError):
            return None, None

    def _picture(
        meet: str,
        name: str,
        data: bytes,
        current: planning.Draft,
        digest: str,
        given: track_picture.Picture | None = None,
    ) -> dict[str, Any]:
        """Banbilden (4c1, level 2): with the station lists and no planning file, the draft is
        derived again with the picture: the places in between, the sections it shows and
        double track, and the map in Bana. With the planning file it is kept as a source."""
        source = planning.Source(
            id=f"u-{digest[:12]}",
            kind=planning.SourceKind.TRACK_PICTURE,
            filename=name,
            size=len(data),
            sha256=digest,
            level=track_picture.LEVEL,
            added=datetime.now(UTC),
        )
        try:
            picture = given or track_picture.read(data)
        except track_picture.PictureError as error:
            raise HTTPException(422, str(error)) from error
        kinds = {s.kind: s for s in current.sources}
        try:
            if planning.SourceKind.PLANNING_JSON in kinds and current.package is not None:
                note = "Planeringsfilen har redan banan; banbilden sparas som underlag."
                result = planning.ImportResult(
                    package=current.package,
                    report=planning.ImportReport(
                        source=source.id, level=track_picture.LEVEL, notes=[note]
                    ),
                    checks_only=True,
                )
            elif (lists := kinds.get(planning.SourceKind.STATION_LISTS)) is not None and (
                found := _stored_lists(meet, lists)
            ) is not None:
                graph, graphed = _graphed(meet, current)
                result = derive.draft(
                    found,
                    meet=current.meet,
                    source=lists,
                    picture=picture,
                    drawn=source,
                    graph=graph,
                    graphed=graphed,
                )
                report = result.report.model_copy(update={"source": source.id})
                result = result.model_copy(update={"report": report})
            else:
                raise HTTPException(
                    422, "Lägg till stationslistorna först. Banbilden bygger vidare på dem."
                )
            return store.preview(meet, source, data, result).model_dump(mode="json")
        except station_lists.ListError as error:
            raise HTTPException(422, str(error)) from error
        except PlanningError as error:
            _fail(error)

    def _graph(
        meet: str,
        name: str,
        data: bytes,
        current: planning.Draft,
        digest: str,
        lines: list[graph_picture.Line],
    ) -> dict[str, Any]:
        """Grafen (4c2, level 3): with the station lists and no planning file, the draft is
        derived again with the graph's lines: the order along each line, the lines in Graf, and
        the sections it confirms. With the planning file it is kept as a source."""
        source = planning.Source(
            id=f"u-{digest[:12]}",
            kind=planning.SourceKind.GRAPH_PICTURE,
            filename=name,
            size=len(data),
            sha256=digest,
            level=graph_picture.LEVEL,
            added=datetime.now(UTC),
        )
        kinds = {s.kind: s for s in current.sources}
        try:
            if planning.SourceKind.PLANNING_JSON in kinds and current.package is not None:
                note = "Planeringsfilen har redan grafen; grafen sparas som underlag."
                result = planning.ImportResult(
                    package=current.package,
                    report=planning.ImportReport(
                        source=source.id, level=graph_picture.LEVEL, notes=[note]
                    ),
                    checks_only=True,
                )
            elif (lists := kinds.get(planning.SourceKind.STATION_LISTS)) is not None and (
                found := _stored_lists(meet, lists)
            ) is not None:
                picture, drawn = _drawn(meet, current)
                result = derive.draft(
                    found,
                    meet=current.meet,
                    source=lists,
                    picture=picture,
                    drawn=drawn,
                    graph=lines,
                    graphed=source,
                )
                report = result.report.model_copy(update={"source": source.id})
                result = result.model_copy(update={"report": report})
            else:
                raise HTTPException(
                    422, "Lägg till stationslistorna först. Grafen bygger vidare på dem."
                )
            return store.preview(meet, source, data, result).model_dump(mode="json")
        except station_lists.ListError as error:
            raise HTTPException(422, str(error)) from error
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/sources/{source}/apply")
    def apply(
        meet: str,
        source: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Lägg in i utkastet: the source that waits comes into the draft."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.apply(meet, source).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/meets/{meet}/sources/{source}")
    def source_file(
        meet: str, source: str, session: SessionCookie = None, authorization: Authorization = None
    ) -> Response:
        """The source as it came. Only for the administrator: a file may hold more than the
        meet needs."""
        planner(meet, session, authorization)
        try:
            found, body = store.source_file(meet, source)
        except PlanningError as error:
            _fail(error)
        quoted = found.filename.replace('"', "")
        return Response(
            body,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{_encode(quoted)}",
            },
        )

    @routes.get("/meets/{meet}/export/{what}")
    def export_file(
        meet: str,
        what: Literal["stationstidtabeller", "tidtabell", "koruppdrag", "paket", "underlag"],
        version: int | None = None,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> Response:
        """Exportera (PLAN-07): the draft, or a published version. The timetable is for anyone
        who may look; the sources only for the administrator, like the files themselves."""
        try:
            draft = store.draft(meet)
            if what == "underlag":
                planner(meet, session, authorization)
                files = [(found.filename, body) for found, body in store.sources(meet)]
                if not files:
                    raise PlanningError("Träffen har inget underlag än.")
                body, kind = export.sources_zip(files), "application/zip"
            else:
                if version is not None:
                    package = kept.package(meet, version)
                    told = f"Version {version}"
                elif draft.package is not None:
                    package = draft.package.model_copy(update={"meet": draft.meet})
                    told = "Utkastet, inte publicerat"
                else:
                    raise PlanningError("Lägg till underlag först.")
                if what == "stationstidtabeller":
                    title = f"{draft.meet.name} · Stationstidtabeller"
                    body = export.station_timetables(package, title, told)
                    kind = "text/html; charset=utf-8"
                elif what == "tidtabell":
                    body, kind = export.timetable_csv(package), "text/csv; charset=utf-8"
                elif what == "koruppdrag":
                    body, kind = export.duties_csv(package), "text/csv; charset=utf-8"
                else:
                    body = package.model_dump_json(indent=2).encode("utf-8")
                    kind = "application/json"
        except (PlanningError, SyncError) as error:
            _fail(error)
        suffix = {"stationstidtabeller": "html", "paket": "json", "underlag": "zip"}.get(
            what, "csv"
        )
        name = export.filename(
            draft.meet.name, what, suffix, None if what == "underlag" else version
        )
        return Response(
            body,
            media_type=kind,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @routes.post("/meets/{meet}/changes")
    def change(
        meet: str,
        given: planning.Changes,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Spara: the planner's changes from Data, in order, against the draft's revision
        (PLAN-38). Someone else's save in between gives 412, and the client reads the draft
        anew."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.change(meet, *given.changes, revision=given.revision).model_dump(
                mode="json"
            )
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/answers")
    def answer(
        meet: str,
        given: planning.Answer,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.answer(meet, given).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/meets/{meet}/check")
    def check(meet: str, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.check(meet).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/meets/{meet}/picture")
    def picture(meet: str, response: Response) -> dict[str, Any]:
        """Banbilden som bakgrund i Bana (PLAN-02): the track picture among the sources, read
        again from the file as it came."""
        response.headers["Cache-Control"] = "no-store"
        try:
            current = store.draft(meet)
            read, drawn = _drawn(meet, current)
        except PlanningError as error:
            _fail(error)
        if read is None or drawn is None:
            raise HTTPException(404, "Träffen har ingen banbild.")
        photo = _photo_of(meet, drawn)
        size = None
        if photo is not None:
            width, height = scanned.dimensions(photo)
            tall = track_picture.PHOTO_WIDTH * height / max(width, 1)
            size = MapPoint(x=track_picture.PHOTO_WIDTH, y=round(tall, 1))
        return planning.TrackPicture(
            source=drawn.id,
            page=read.page,
            photo=size,
            points={code: MapPoint(x=x, y=y) for code, (x, y) in read.places.items()},
            links=[
                planning.PictureLink(a=a, b=b, double=double)
                for pair, double in sorted(read.links.items(), key=lambda i: sorted(i[0]))
                for a, b in [sorted(pair)]
            ],
        ).model_dump(mode="json")

    def _photo_of(meet: str, drawn: planning.Source) -> ai.Image | None:
        _, body = store.source_file(meet, drawn.id)
        if not scanned.needs_ai(body, drawn.filename):
            return None
        try:
            return scanned.pages(body, drawn.filename)[0].image
        except station_lists.ListError:
            return None

    @routes.get("/meets/{meet}/picture/photo")
    def picture_photo(meet: str) -> Response:
        """The photographed track picture itself, the background in Bana (IMPORT-17)."""
        try:
            current = store.draft(meet)
        except PlanningError as error:
            _fail(error)
        drawn = next(
            (s for s in current.sources if s.kind == planning.SourceKind.TRACK_PICTURE), None
        )
        photo = _photo_of(meet, drawn) if drawn else None
        if photo is None:
            raise HTTPException(404, "Träffen har ingen fotograferad banbild.")
        return Response(
            photo.data, media_type=photo.media_type, headers={"Cache-Control": "no-store"}
        )

    @routes.post("/meets/{meet}/double-track/{section}")
    def double_track(
        meet: str,
        section: str,
        given: planning.DoubleTrackAnswer,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Dubbelspårsfrågan (PLAN-35): Ja or Nej for a single-track section."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.double_track(meet, section, given).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/deviations/{deviation}/let-stand")
    def let_stand(
        meet: str,
        deviation: str,
        given: planning.LetStand,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Låt stå in the reasonableness check (PLAN-36)."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.let_stand(meet, deviation, given).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/deviations/{deviation}/take-back")
    def take_back(
        meet: str,
        deviation: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Ta tillbaka a Låt stå."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.take_back(meet, deviation).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/meets/{meet}/versions")
    def versions(meet: str, response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        try:
            found = kept.versions(meet)
            if not found:
                store.draft(meet)  # a meet Planering does not know is not there
            return [version.model_dump(mode="json") for version in found]
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/versions", status_code=201)
    def publish(
        meet: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        may.require_publisher(session_of(session, authorization), id_meet_of(meet))
        try:
            package = store.freeze(meet)
            version = kept.publish(meet, package.model_dump_json().encode())
        except (PlanningError, SyncError) as error:
            _fail(error)
        published(meet)  # a hub that follows the meet gets it at once (SYNK-10)
        return version.model_dump(mode="json")

    # Förslag från Drift (4.4, PLAN-03): Ta med or Avslå.

    @routes.get("/meets/{meet}/proposals")
    def proposals(meet: str, response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return [proposal.model_dump(mode="json") for proposal in store.proposals(meet)]
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/proposals/{proposal}/take")
    def take(
        meet: str,
        proposal: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Ta med: the driftändring into the draft for the next version."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.take(meet, proposal).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/proposals/{proposal}/reject")
    def reject(
        meet: str,
        proposal: str,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Avslå: the next version is made without it."""
        response.headers["Cache-Control"] = "no-store"
        planner(meet, session, authorization)
        try:
            return store.reject(meet, proposal).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.post("/meets/{meet}/versions/{number}/withdraw")
    def withdraw(
        meet: str,
        number: int,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Dra tillbaka en version (PLAN-18): only Administratör, as in the old Cloud (PLAN-24)."""
        response.headers["Cache-Control"] = "no-store"
        may.require_withdrawer(session_of(session, authorization), id_meet_of(meet))
        try:
            withdrawn = kept.withdraw(meet, number)
        except SyncError as error:
            _fail(error)
        published(meet)
        return withdrawn.model_dump(mode="json")

    @routes.get("/meets/{meet}/versions/{number}")
    def version(meet: str, number: int, response: Response) -> dict[str, Any]:
        """A published version as the meet package Drift runs."""
        response.headers["Cache-Control"] = "no-store"
        try:
            return kept.package(meet, number).model_dump(mode="json")
        except SyncError as error:
            _fail(error)

    return routes


def _encode(name: str) -> str:
    return quote(name, safe="")


def _is_outside(data: bytes) -> bool:
    """A station's outside, trainmeet.station-outside/1, as TKL Studio writes it."""
    head = data[:400].lstrip()
    return head.startswith(b"{") and b'"trainmeet.station-outside/1"' in data[:2000]
