"""Planeringens API (steg 4a): meets, sources, the draft, the check and the versions.

Everyone may look (S1); everything that changes something needs the local administrator's
session. A source is sent as the file's bytes with its name in the address, so no form
library is needed. The file is read by Integrationer and kept as it came.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Final, Literal, NoReturn
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from contracts import planning
from hub.hubben import Authorization, SessionCookie, require_admin
from hub.local import LocalLogin
from integrationer import derive, planning_json, station_lists
from planering import export
from planering.store import Planning, PlanningError

MAX_UPLOAD: Final = planning_json.MAX_BYTES
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _fail(error: PlanningError) -> NoReturn:
    raise HTTPException(error.status, str(error)) from error


def filename(name: str) -> str:
    """The file's own name, without folders or control characters."""
    base = PureWindowsPath(PurePosixPath(name).name).name
    return _CONTROL.sub("", base).strip()[:200] or "underlag"


def router(store: Planning, login: LocalLogin) -> APIRouter:
    routes = APIRouter(prefix="/api/planering/1")

    def admin(session: str | None, authorization: str | None) -> None:
        require_admin(login, session, authorization)

    @routes.get("/meets")
    def meets(response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return [summary.model_dump(mode="json") for summary in store.meets()]

    @routes.post("/meets", status_code=201)
    def create(
        new: planning.NewMeet,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            return store.create(new).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

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
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """Lägg till underlag: the file's bytes in the body, its name in the address. The file
        is read and what it would change is shown; nothing changes until it is laid in."""
        response.headers["Cache-Control"] = "no-store"
        await run_in_threadpool(admin, session, authorization)
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
        return await run_in_threadpool(_read, meet, filename(name), data)

    def _read(meet: str, name: str, data: bytes) -> dict[str, Any]:
        lower = name.casefold()
        lists = station_lists.is_lists(name)
        if not (lists or lower.endswith((".json", ".json.gz", ".gz")) or data[:2] == b"\x1f\x8b"):
            raise HTTPException(
                415,
                "Den filtypen läses inte än. Lägg till Tellurians planeringsfil (JSON) eller "
                "stationslistorna (ODT, ZIP, Excel eller CSV).",
            )
        try:
            current = store.draft(meet)
        except PlanningError as error:
            _fail(error)
        digest = hashlib.sha256(data).hexdigest()
        if lists:
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
            if added is not None:
                _, body = store.source_file(meet, added.id)
                result = station_lists.judged_anew(body, added.filename, result)
            return store.preview(meet, source, data, result).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    def _lists(
        meet: str, name: str, data: bytes, current: planning.Draft, digest: str
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
            if planned and current.package is not None:
                result = station_lists.check(data, name, plan=current.package, source=source)
            else:
                found = station_lists.read(data, name)
                result = derive.draft(found, meet=current.meet, source=source)
        except station_lists.ListError as error:
            raise HTTPException(422, str(error)) from error
        try:
            return store.preview(meet, source, data, result).model_dump(mode="json")
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
        admin(session, authorization)
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
        admin(session, authorization)
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
                admin(session, authorization)
                files = [(found.filename, body) for found, body in store.sources(meet)]
                if not files:
                    raise PlanningError("Träffen har inget underlag än.")
                body, kind = export.sources_zip(files), "application/zip"
            else:
                if version is not None:
                    package = store.package(meet, version)
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
        except PlanningError as error:
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
        admin(session, authorization)
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
        admin(session, authorization)
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
        admin(session, authorization)
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
        admin(session, authorization)
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
        admin(session, authorization)
        try:
            return store.take_back(meet, deviation).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/meets/{meet}/versions")
    def versions(meet: str, response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return [version.model_dump(mode="json") for version in store.versions(meet)]
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
        admin(session, authorization)
        try:
            return store.publish(meet).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

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
        admin(session, authorization)
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
        admin(session, authorization)
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
        """Dra tillbaka en version (PLAN-18)."""
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            return store.withdraw_version(meet, number).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    @routes.get("/meets/{meet}/versions/{number}")
    def version(meet: str, number: int, response: Response) -> dict[str, Any]:
        """A published version as the meet package Drift runs."""
        response.headers["Cache-Control"] = "no-store"
        try:
            return store.package(meet, number).model_dump(mode="json")
        except PlanningError as error:
            _fail(error)

    return routes


def _encode(name: str) -> str:
    return quote(name, safe="")
