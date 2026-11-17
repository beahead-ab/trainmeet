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

from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse

from contracts import hub
from contracts.sync import Hello
from drift.store import MissingRun, PreviewStore
from hub import (
    build_info,
    drift_api,
    hubben,
    network_api,
    planering_api,
    provbanan,
    screen_web,
    station_api,
    synk_api,
    tmbox_web,
    update_api,
    web,
)
from hub.local import LocalLogin
from hub.pin import take_pin_file
from hub.push import Pusher, Senders
from hub.running import Running
from hub.stores import AnyRun
from planering.store import Planning
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


def create_app(
    info: build_info.BuildInfo | None = None,
    *,
    preview_db: Path | None = None,
    web_root: Path | None = None,
    sync_call: Call = urllib_call,
) -> FastAPI:
    info = info if info is not None else build_info.from_env()
    preview_path = provbanan.database_path(preview_db)
    data_dir = preview_path.parent
    login = LocalLogin(data_dir / "hubben.sqlite3", info.hub_name)
    package = provbanan.package()
    # Provbanan's runs per browser: the automation starts off, since only the hub's meet
    # is ticked (F14).
    preview = PreviewStore(
        preview_path, package, package_key=provbanan.package_key(), automation=False
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
        try:
            yield
        finally:
            stop.set()
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
    app.include_router(hubben.router(login))
    # Pi:ns nät (SYNK-26): through the helper on the Pi; elsewhere it says it is not there.
    app.include_router(network_api.router(login))
    # Ny version finns, och uppdateringen på knapptryck (SYNK-19, SYNK-23): on a Pi installed
    # with deploy/pi.
    app.state.latest = latest = update_api.Latest()
    app.include_router(update_api.router(login, running, current, latest=latest))
    app.include_router(provbanan.router(preview))
    app.include_router(drift_api.router(running, login))
    app.include_router(
        planering_api.router(plans, versions, links, homes, me, login, published=follower.nudge)
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
    app.include_router(station_api.router(runs, relay_address))
    app.include_router(station_api.relay_router(relay))
    app.include_router(screen_web.router(runs))

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
