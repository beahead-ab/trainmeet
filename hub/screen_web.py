"""Träffens skärmar in the browser: a TV joins with the meet's code, waits under Väntar, and
shows the view the dispatcher gives it in Klienter. Steg 3 has the clock (1920 × 1080).

The screen keeps its key in sessionStorage and sends it as Authorization: Bearer; it is never
in an address or a log.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import HTMLResponse

from contracts import screen, station
from drift.engine import model_time, now_utc
from drift.store import MissingRun, RunLimit, UnknownClient
from hub.stores import AnyRun

Authorization = Annotated[str | None, Header(max_length=200)]

PAGE = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrainMeet · Skärm</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/skarm.css">
<script src="/static/skarm.js" defer></script>
</head>
<body>
<section id="login" class="anslut">
  <img class="skylt" src="/static/skylt.svg" alt="TrainMeet">
  <h1>Anslut skärmen</h1>
  <p>Skriv träffens kod. Trafikledningen väljer sedan vad skärmen visar.</p>
  <form id="login-form">
    <label>Skärmens namn <input id="name" maxlength="40" required value="Skärm"
      autocomplete="off"></label>
    <label>Kod <input id="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required
      autocomplete="off"></label>
    <button type="submit">Anslut</button>
  </form>
  <p id="message" role="alert"></p>
</section>
<section id="waiting" class="vantar" hidden>
  <img class="skylt" src="/static/skylt.svg" alt="TrainMeet">
  <h1>Väntar på en vy</h1>
  <p><b id="screen-name"></b> är ansluten. Välj vad den ska visa under Klienter.</p>
</section>
<section id="clock-view" class="klocka" hidden>
  <p id="meet" class="traff"></p>
  <p id="time" class="tid">--:--</p>
  <p id="state" class="lage"></p>
</section>
</body>
</html>
"""


def router(runs: AnyRun) -> APIRouter:
    routes = APIRouter()

    @routes.get("/skarm", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

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

    @routes.get("/api/screen/picture")
    def picture(response: Response, authorization: Authorization = None) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        scheme, _, key = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not 20 <= len(key) <= 120:
            raise HTTPException(401, "Nyckeln saknas.")
        try:
            name, view, drift = runs.screen_picture(key)
        except UnknownClient as error:
            raise HTTPException(401, "Skärmen finns inte längre. Anslut igen.") from error
        seconds = drift.clock.at(now_utc())
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
        ).model_dump(mode="json")

    return routes
