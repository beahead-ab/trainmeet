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
from typing import Any, Final, NoReturn
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from contracts import planning
from hub.hubben import Authorization, SessionCookie, require_admin
from hub.local import LocalLogin
from integrationer import planning_json
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
        """Lägg till underlag: the file's bytes in the body, its name in the address."""
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
        if not (lower.endswith((".json", ".json.gz", ".gz")) or data[:2] == b"\x1f\x8b"):
            raise HTTPException(
                415, "Den filtypen läses inte än. Lägg till Stefans planeringsfil (JSON)."
            )
        try:
            current = store.draft(meet)
        except PlanningError as error:
            _fail(error)
        digest = hashlib.sha256(data).hexdigest()
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
        try:
            return store.add_source(meet, source, data, result).model_dump(mode="json")
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

    @routes.post("/meets/{meet}/places")
    def change_place(
        meet: str,
        change: planning.PlaceChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            draft = store.change(meet, change)
        except PlanningError as error:
            _fail(error)
        places = draft.package.places if draft.package else []
        place = next(p for p in places if p.id == change.place)
        return place.model_dump(mode="json")

    @routes.post("/meets/{meet}/sections")
    def change_section(
        meet: str,
        change: planning.SectionChange,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        admin(session, authorization)
        try:
            draft = store.change(meet, change)
        except PlanningError as error:
            _fail(error)
        sections = draft.package.sections if draft.package else []
        section = next(s for s in sections if s.id == change.section)
        return section.model_dump(mode="json")

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
