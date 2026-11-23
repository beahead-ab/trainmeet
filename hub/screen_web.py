"""Träffens skärmar in the browser: a TV joins with the meet's code, waits under Väntar, and
shows the view the dispatcher gives it in Klienter, drawn for 1920 × 1080. The clock needs only
the time; the views that draw the line get the meet as it runs with the picture, and the
package once from /api/screen/package (SKARM-09).

The page is the app apps/skarmar, served at /skarm by hub/web.py (SKARM-14). It keeps its key in
sessionStorage and sends it as Authorization: Bearer; it is never in an address or a log.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, Response

from contracts import screen, station
from contracts.meet import AttachmentKind
from core.clock_pack import ClockPackError, chosen_face, read_pack
from drift.engine import Drift, model_time, now_utc
from drift.now import now
from drift.store import MissingRun, RunLimit, UnknownClient
from hub.stores import AnyRun

Authorization = Annotated[str | None, Header(max_length=200)]
CLOCKS = {screen.ScreenView.CLOCK.value, screen.ScreenView.CLOCK_DIGITAL.value}
LAYER = re.compile(r"^(?:dark-)?(?:dial|hour|minute|second|top)$")
SANDBOX = "sandbox; default-src 'none'"


def package_key(drift: Drift) -> str:
    """Which package a screen draws on: the version and where each driftändring stands."""
    changes = ",".join(f"{c.id}:{c.status}" for c in drift.changes.values())
    return hashlib.sha256(f"{drift.version}|{changes}".encode()).hexdigest()[:16]


def _show(
    drift: Drift, files: Callable[[str], tuple[str, bytes] | None] | None
) -> screen.ClockFaceShow:
    """The analog clock's face: the built-in one, or the meet's custom:<id>."""
    faces = {a.id: a for a in drift.package.attachments if a.kind == AttachmentKind.CLOCK_FACE}
    face = chosen_face(list(drift.package.clock.styles), set(faces))
    if face is None or files is None:
        return screen.ClockFaceShow(style="analog")
    kept = files(faces[face].sha256)
    if kept is None:
        return screen.ClockFaceShow(style="analog")
    try:
        pack = read_pack(kept[1])
    except ClockPackError:
        return screen.ClockFaceShow(style="analog")
    motion = screen.ClockMotion.model_validate(pack.motion)
    return screen.ClockFaceShow(
        style=f"custom:{pack.id}",
        id=pack.id,
        name=pack.name,
        sha256=faces[face].sha256,
        motion=motion,
        layers=list(pack.layers),
        dark=list(pack.dark),
    )


def router(
    runs: AnyRun,
    share: Callable[[Request], screen.ScreenShare] | None = None,
    files: Callable[[str], tuple[str, bytes] | None] | None = None,
) -> APIRouter:
    """`share` gives the clock its QR codes: träffens Wi-Fi and the link to the meet.
    `files` reads an attachment by its checksum, so the clock pack follows the version."""
    routes = APIRouter()

    @routes.post("/api/screen/session", status_code=201)
    def login(request: screen.ScreenLogin, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            client_id, key = runs.screen_login(request.name, request.code)
        except MissingRun as error:
            raise HTTPException(404, "Koden finns inte, eller träffen har bytts.") from error
        except RunLimit as error:
            raise HTTPException(429, "Träffen har redan sina skärmar.") from error
        return screen.ScreenSession(client_id=client_id, session_key=key).model_dump(mode="json")

    def shown(authorization: str | None) -> tuple[str, str | None, Drift]:
        scheme, _, key = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not 20 <= len(key) <= 120:
            raise HTTPException(401, "Nyckeln saknas.")
        try:
            return runs.screen_picture(key)
        except UnknownClient as error:
            raise HTTPException(401, "Skärmen finns inte längre. Anslut igen.") from error

    @routes.get("/api/screen/picture")
    def picture(
        request: Request, response: Response, authorization: Authorization = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        name, view, drift = shown(authorization)
        at = now_utc()
        drawn = view is not None and view not in CLOCKS
        seconds = drift.clock.at(at)
        return screen.ScreenPicture(
            name=name,
            view=screen.ScreenView(view) if view else None,
            meet=drift.package.meet.name,
            traffic_day=drift.traffic_day,
            clock=station.Clock(
                time=model_time(seconds),
                seconds=int(seconds),
                running=drift.clock.running,
                speed=drift.clock.speed,
                game_day=drift.game_day,
            ),
            now=now(drift, at) if drawn else None,
            package=package_key(drift) if drawn else None,
            share=share(request) if share is not None and view in CLOCKS else None,
        ).model_dump(mode="json")

    @routes.get("/api/screen/package")
    def package(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        """The package the views draw on: the version with the driftändringar on top. Fetched
        once, and again when the picture's key changes."""
        response.headers["Cache-Control"] = "no-store"
        _, _, drift = shown(authorization)
        return drift.package.model_dump(mode="json")

    @routes.get("/api/screen/clock")
    def clock_face(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        """The face the analog clock draws. custom:<id> when the meet has chosen one."""
        response.headers["Cache-Control"] = "no-store"
        _, _, drift = shown(authorization)
        return _show(drift, files).model_dump(mode="json")

    @routes.get("/api/screen/clock/{face}/{layer}")
    def clock_layer(face: str, layer: str, authorization: Authorization = None) -> Response:
        """One layer of the chosen face, as an image. A script in it cannot run."""
        _, _, drift = shown(authorization)
        shown_face = _show(drift, files)
        if shown_face.id != face or not LAYER.fullmatch(layer) or files is None:
            raise HTTPException(404, "Lagret finns inte.")
        attachment = next((a for a in drift.package.attachments if a.id == face), None)
        kept = files(attachment.sha256) if attachment is not None else None
        try:
            pack = read_pack(kept[1]) if kept is not None else None
        except ClockPackError:
            pack = None
        found = pack.layer(layer) if pack is not None else None
        if found is None:
            raise HTTPException(404, "Lagret finns inte.")
        return Response(
            found.data,
            media_type=found.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Security-Policy": SANDBOX,
                "X-Content-Type-Options": "nosniff",
            },
        )

    return routes
