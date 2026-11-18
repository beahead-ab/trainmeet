"""The hub's web program. Start it with: uv run uvicorn hub.app:app --reload"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from typing import Any, Final
from uuid import UUID

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from contracts import hub
from contracts.screen import ScreenShare
from contracts.sync import Hello
from drift.store import MissingRun, PreviewStore
from hub import (
    build_info,
    clock_source,
    deltagare,
    drift_api,
    driver_api,
    hubben,
    id_login,
    id_roles,
    id_tokens,
    network_api,
    pi_login,
    planering_api,
    provbanan,
    rights,
    screen_web,
    station_api,
    synk_api,
    tellurian_shadow,
    tmbox_mqtt,
    tmbox_web,
    update_api,
    web,
)
from hub.local import LocalLogin
from hub.pin import take_pin_file
from hub.push import Pusher, Senders
from hub.running import Running
from hub.stores import AnyRun
from integrationer.fastclock import ExternalClock
from integrationer.tellurian import TellurianClient
from planering.store import Planning, PlanningError
from synk.follower import Call, Follower, urllib_call
from synk.home import Homes
from synk.link import Links
from synk.push import ApnsPush, ApnsSettings, CloudPush, FakePush
from synk.relay import Relay
from synk.stations import NoOwners, Owners, Stations
from synk.store import Versions

# The automation takes a step about once a second while the hub runs (F14).
TICK_SECONDS: Final = 1.0
LOGGER = logging.getLogger("hub.automatik")


def tick_once(running: Running) -> None:
    """One round of the automation for the hub's meet, if one is started, and a new version
    with only små rättelser taken at once (F5)."""
    store = running.store
    try:
        store.tick(store.current())
        running.take_small_corrections()
    except MissingRun:
        return


def _ticker(running: Running, stop: Event, chores: list[tuple[str, Callable[[], object]]]) -> None:
    """The automation, and then the hub's other chores once a second: each on its own, so
    that one that fails never stops the others."""
    while not stop.wait(TICK_SECONDS):
        try:
            tick_once(running)
        except Exception:
            LOGGER.exception("Automatiken kunde inte ta sitt steg")
        for what, chore in chores:
            try:
                chore()
            except Exception:
                LOGGER.exception("%s kunde inte göras", what)


class IdOwners:
    """Stationspaketen (SYNK-06, SYNK-30): the owner is the person TKL's token from TrainMeet ID
    names (TKL18). Only tokens ID gave TKL count."""

    def __init__(self, with_id: id_login.IdLogin) -> None:
        self.with_id = with_id

    def owner(self, authorization: str | None) -> str | None:
        return self.with_id.app_subject(authorization, frozenset({"tkl"}))


def create_app(
    info: build_info.BuildInfo | None = None,
    *,
    preview_db: Path | None = None,
    web_root: Path | None = None,
    sync_call: Call = urllib_call,
    id_settings: id_login.IdSettings | None = None,
    id_http: httpx.Client | None = None,
    external_clock: ExternalClock | None = None,
    tellurian_client: Callable[[str, bool], TellurianClient] | None = None,
) -> FastAPI:
    """id_settings and id_http: the login with TrainMeet ID, for tests; otherwise read from the
    environment (hub/id_login.py). external_clock: FastClock, for tests with a pretend one."""
    info = info if info is not None else build_info.from_env()
    preview_path = provbanan.database_path(preview_db)
    data_dir = preview_path.parent
    login = LocalLogin(data_dir / "hubben.sqlite3", info.hub_name)
    package = provbanan.package()
    # Provbanan's runs per browser: the automation starts off, since only the hub's meet
    # is ticked (F14).
    preview = PreviewStore(
        preview_path,
        package,
        package_key=provbanan.package_key(),
        automation=False,
        preview=True,
    )
    plans = Planning(data_dir / "planering.sqlite3")
    # Synk keeps the versions, in Planering's file (SYNK-20).
    versions = Versions(data_dir / "planering.sqlite3")
    links = Links(data_dir / "planering.sqlite3")
    homes = Homes(data_dir / "planering.sqlite3")
    # Stationspaketen (SYNK-06): the owners' private versions. Who owns comes from TrainMeet
    # ID, which the hub gets in #78; until then no one does here (SYNK-30).
    stations = Stations(data_dir / "planering.sqlite3")
    owners: Owners = NoOwners()
    # The hub's own meet: Provbanan or a published version, each in a file of its own.
    # A USB stick for the copy of the drift events (DRIFT-21), where the Pi mounts it.
    usb = os.environ.get("TRAINMEET_USB_DIR", "").strip()
    running = Running(
        data_dir,
        package,
        provbanan.package_key(),
        plans,
        versions,
        hub_version=info.version,
        usb=Path(usb) if usb else None,
    )

    def current() -> build_info.BuildInfo:
        return replace(info, hub_name=login.state().name)

    def hello() -> Hello:
        return Hello(hub_id=links.hub_id(), hub_name=login.state().name, software=info.version)

    runs = AnyRun(lambda: running.store, lambda: preview)

    def relay_address() -> str | None:
        """Where a station client reaches this hub outside the meet's network: the relay of
        the cloud it is linked to (SYNK-11)."""
        reach = next(iter(links.reaches()), None)
        return None if reach is None else f"{reach.address}/relay/{links.hub_id()}"

    # The Pi follows its meets in the cloud (SYNK-10), sends the run it leads up (DRIFT-12)
    # and answers the calls that come through the cloud's relay: it always calls out (SYNK-13).
    follower = Follower(
        links,
        versions,
        hello,
        sync_call,
        runs=running,
        homes=homes,
        station=lambda call: station_api.relayed(runs, call, relay_address),
    )
    relay = Relay()
    # Push (F20): with Apple's key here, otherwise through the cloud, otherwise pretend.
    pushes = Senders(
        (lambda found: ApnsPush(found) if found else None)(ApnsSettings.from_env()),
        CloudPush(follower.send, lambda: running.meet),
        FakePush(),
        lambda: any(reach.meet == running.meet for reach in links.reaches()),
    )
    pusher = Pusher(running, pushes)
    running.followed_answers = links.answers

    def me() -> tuple[str, str]:
        return links.hub_id(), login.state().name

    running.home_here = lambda meet: homes.home(meet, *me()).here

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = Event()
        chores: list[tuple[str, Callable[[], object]]] = [("Notiserna", pusher.round)]
        if usb:
            # A forgotten PIN, with a file on the USB stick (H46).
            chores.append(("PIN-filen", lambda: take_pin_file(Path(usb), login)))
        thread = Thread(
            target=_ticker, args=(running, stop, chores), name="automatiken", daemon=True
        )
        thread.start()
        synk = Thread(target=follower.run, args=(stop,), name="synken", daemon=True)
        synk.start()
        # FastClock, when it is the meet's clock (F12): read in a thread of its own, so that a
        # slow answer never holds up the automation.
        Thread(target=clock.run, args=(stop,), name="klockan", daemon=True).start()
        # In the test environment Tellurian's simulator runs here, fed from Drift (IMPORT-36).
        feed = (
            tellurian_shadow.SimulatorFeed(shadowing) if tellurian_shadow.simulator_from() else None
        )
        Thread(target=shadowing.run, args=(stop, feed), name="tellurian", daemon=True).start()
        # The physical TMBoxes over MQTT, on a Pi with Mosquitto (BOX-10, DRIFT-22).
        boxes = tmbox_mqtt.from_environment(running, links.hub_id)
        if boxes is not None:
            boxes.start()
        try:
            yield
        finally:
            stop.set()
            if boxes is not None:
                boxes.stop()
            thread.join(timeout=5)

    # The interactive API pages are off: they load scripts from another site. The contracts
    # get their own readable pages in step 1, part 2.
    app = FastAPI(
        title=build_info.PRODUCT,
        version=info.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.running = running
    app.state.follower = follower
    app.state.relay = relay
    app.state.owners = owners
    app.state.pusher = pusher

    def current_run() -> str | None:
        """The meet that runs: a role let in with a one-time code holds only there (H56)."""
        try:
            return running.store.current()
        except MissingRun:
            return None

    # Logga in med TrainMeet ID (#78), when the hub is set up for it (hub/id_login.py).
    id_settings = id_settings if id_settings is not None else id_login.settings_from()
    with_id = roles_from_id = None
    if id_settings is not None:
        id_client = id_http if id_http is not None else httpx.Client(timeout=10.0)
        with_id = id_login.IdLogin(login, id_settings, http=id_client)
        # Stationspaketen (SYNK-30, TKL18): the owner is the one TKL's token from ID names.
        owners = IdOwners(with_id)
        app.state.owners = owners
        # The roles at a meet, asked of ID's API at every call (ID10, KONTO-34).
        if id_settings.api is not None:
            roles_from_id = id_roles.IdRoles(id_settings, id_client)
    may = rights.Rights(login, roles_from_id)

    def may_run(token: str | None, run: str | None) -> bool:
        return may.may_run(token, run, running.store.package.meet.id_meet)

    # Biljetten för Pi:n (KONTO-11, KONTO-37, hub/pi_login.py): in the cloud, attempts from the
    # Pis that follow it; on a meet's Pi, the login through the cloud and again without internet.
    pi_finish = None
    if with_id is not None and roles_from_id is not None:

        def id_meet_of(meet: str) -> UUID | None:
            try:
                return plans.draft(meet).meet.id_meet
            except PlanningError:
                return None

        pi_tickets = pi_login.PiTickets(login, roles_from_id, id_meet_of)
        pi_finish = pi_tickets.finish
        app.include_router(pi_login.cloud_router(login, links, with_id, pi_tickets))
    if with_id is None:
        app.include_router(pi_login.pi_router(login, links, lambda: running.meet, sync_call))
    # Saldot och mätaren i ID (#79): where the hub has ID's API, that is in the cloud.
    tokens = id_tokens.IdTokens(roles_from_id) if roles_from_id is not None else None
    app.include_router(
        hubben.router(
            login,
            current_run,
            with_id,
            may_run,
            pi_offers=lambda: with_id is None and bool(links.reaches()),
            pi_finish=pi_finish,
            ticket_name=pi_login.ticket_name(login, links),
            tokens_of=tokens.shown if tokens is not None else None,
        )
    )

    def meet_link() -> str | None:
        """The meet over the internet: the cloud hub this hub is linked to for the meet."""
        return next((r.address for r in links.reaches() if r.meet == running.meet), None)

    # Deltagarna (DELT-01–DELT-20): träffens Wi-Fi, and what the participant page may show (S8).
    app.include_router(deltagare.router(login, meet_link, current_run))
    # Pi:ns nät (SYNK-26): through the helper on the Pi; elsewhere it says it is not there.
    app.include_router(network_api.router(login))
    # Ny version finns, och uppdateringen på knapptryck (SYNK-19, SYNK-23): on a Pi installed
    # with deploy/pi.
    app.state.latest = latest = update_api.Latest()
    app.include_router(update_api.router(login, running, current, latest=latest))
    app.include_router(provbanan.router(preview))
    # Träffens klocka (F12, IMPORT-35): FastClock, when chosen for the meet that runs.
    app.state.clock = clock = clock_source.ClockSource(running, login, external_clock)
    # Tellurian Dispatch i skugga (IMPORT-34): read beside Drift, never sent to.
    app.state.tellurian = shadowing = tellurian_shadow.Shadow(running, login, tellurian_client)
    app.include_router(drift_api.router(running, login, may, clock, shadowing))
    # Förarnas API (trainmeet.driver/1): Lokföraren, and Förare in Drift (LOK-08, TRAFIK-33).
    # A driver's paper is read with the meter in ID where the hub has it (LOK-33).
    app.include_router(driver_api.router(running, login, may, tokens))
    app.include_router(clock_source.router(clock, login, may))
    app.include_router(tellurian_shadow.router(shadowing, login, may))
    app.include_router(
        planering_api.router(
            plans,
            versions,
            links,
            homes,
            me,
            login,
            published=follower.nudge,
            rights=may,
            tokens=tokens,
        )
    )
    app.include_router(
        synk_api.router(
            plans,
            versions,
            links,
            follower,
            running,
            homes,
            login,
            hello,
            relay,
            pushes,
            stations,
            owners,
        )
    )
    app.include_router(tmbox_web.router(runs))
    app.include_router(station_api.router(runs, relay_address, meet=lambda: running.store))
    app.include_router(station_api.relay_router(relay))

    def screen_share(request: Request) -> ScreenShare:
        """The clock's QR codes (SKARM-18): the Wi-Fi only on the meet's network (S8)."""
        wifi = login.meet_wifi()
        here = f"{request.headers.get('x-forwarded-proto') or request.url.scheme}://"
        here += request.headers.get("host") or request.url.netloc
        return ScreenShare(
            wifi=bool(wifi and wifi.name) and deltagare.on_meet_network(request),
            link=meet_link() or f"{here}/",
        )

    app.include_router(screen_web.router(runs, screen_share))

    # The pages, built in React under apps/ (H62, GRUND-36).
    app.include_router(web.router(web_root))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/api/version")
    def api_version(response: Response) -> dict[str, Any]:
        """What runs, with the name the hub was given at first start."""
        response.headers["Cache-Control"] = "no-store"
        return hub.Version.model_validate(current().as_dict()).model_dump(mode="json")

    return app


app = create_app()
