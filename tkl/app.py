"""TKL's server: its own API for the web app (contracts/tkl.py) and the web app itself.

    GET  /api/tkl/1/state                 TklState
    POST /api/tkl/1/setup                 TklSetUp -> TklState (första start)
    POST /api/tkl/1/unlock | /lock        TklUnlock -> TklState
    POST /api/tkl/1/pin                   TklPinChange
    GET  /api/tkl/1/studio                TklStudio
    PUT  /api/tkl/1/studio                StationOutside -> TklStudio (sparad; 409 med modell)
    POST /api/tkl/1/studio/version        TklStudio (Ny version av utsidan, med stationsmodellen)
    GET  /api/tkl/1/studio/model          TklTrackPlan: stationens modell som Spårplan visar den
    PUT  /api/tkl/1/studio/model          StationModel -> TklTrackPlan (importera, nivå 1–2)
    DELETE /api/tkl/1/studio/model        TklStudio (tillbaka till nivå 0, med listan)
    GET  /api/tkl/1/referens              [TklReference] (referensstationerna, TKL40)
    GET  /api/tkl/1/referens/{id}         TklTrackPlan (att titta på)
    POST /api/tkl/1/referens/{id}/use     TklTrackPlan (Använd som min station)
    GET  /api/tkl/1/studio/manover        TklManover: Manövers inställningar (STV-46)
    PUT  /api/tkl/1/studio/manover        TklManover -> TklManover (sparas med modellen)
    GET  /api/tkl/1/hubs                  [FoundHub]
    GET  /api/tkl/1/connection            TklConnection
    POST /api/tkl/1/connection            TklConnect -> TklConnection
    DELETE /api/tkl/1/connection          TklConnection (Koppla från)
    GET  /api/tkl/1/places/{place}        TklView
    POST /api/tkl/1/commands              TklCommand -> station.Reply
    POST /api/tkl/1/places/{place}/exits  station.ExitAnswer -> TklView
    GET  /api/tkl/1/places/{place}/events the hub's hints, passed on (text/event-stream)

Ställverket at level 1–2 (#84), for a station with a model; every answer is TklAnswer, yes or
no with the reason, and the state:

    GET  /api/tkl/1/stallverk                     TklInterlocking: the state, for the panel
    GET  /api/tkl/1/stallverk/wait?after=&seconds= TklWait: a long poll for the next change
    GET  /api/tkl/1/stallverk/targets?start=      TklTargets: the goals from a start
    POST /api/tkl/1/stallverk/route               TklRouteAsk: lägg en väg (STV-01, STV-03)
    POST /api/tkl/1/stallverk/release             TklRouteRef: lös ut
    POST /api/tkl/1/stallverk/emergency-release   TklEmergencyRelease: nödutlös, bekräftat
    POST /api/tkl/1/stallverk/lever               TklLeverAsk: lägg hela spaken (STV-52)
    POST /api/tkl/1/stallverk/step                TklRouteRef: Kör, en sektion fram (STV-06)
    POST /api/tkl/1/stallverk/arrive              TklRouteRef: Ankommit (STV-16)
    POST /api/tkl/1/stallverk/depart              TklRouteRef: Avgått, ut på linjen
    POST /api/tkl/1/stallverk/train               TklTrainPut: sätt ut ett tågnummer
    POST /api/tkl/1/stallverk/train/remove        TklTrainRef: ta bort ett tågnummer
    POST /api/tkl/1/stallverk/reset               TklReset: nollställ, bekräftat
    POST /api/tkl/1/stallverk/function            TklFunctionAsk: en panelfunktion (STV-04)

What the interlocking reports goes up to the hub as station commands when TKL is connected and
approved for one place (tkl/hub_reports.py, STV-10).

While the station has a model, Studio's list is its outside derived from the model (STD-08,
TKL92): it is shown but not written, and a new version is made as before (TKL25).

Everything but the state, first start and unlocking needs the PIN: a session in an HttpOnly
cookie (TKL18). TKL in the cloud also keeps which station is the browser's in a cookie, and
reaches only the hubs it is set up for, never an address someone types (TKL5).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated, Any, NoReturn
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import ValidationError

from contracts import station
from contracts.hub import Version
from contracts.station_model import StationModel, dump
from contracts.station_outside import StationOutside
from contracts.sync import StationPackage
from contracts.tkl import (
    TklAnswer,
    TklCommand,
    TklConnect,
    TklConnection,
    TklEmergencyRelease,
    TklFunctionAsk,
    TklIdState,
    TklInterlocking,
    TklLeverAsk,
    TklManover,
    TklMode,
    TklPinChange,
    TklReport,
    TklReportKind,
    TklReset,
    TklRouteAsk,
    TklRouteRef,
    TklSave,
    TklSaved,
    TklSetUp,
    TklState,
    TklTrainPut,
    TklTrainRef,
    TklUnlock,
    TklView,
    TklWait,
)
from tkl import VERSION, hub_reports, id_login, manover, track_plan
from tkl.hub_client import TIMEOUT, HubClient, HubError, Unreachable, browse, find_hubs
from tkl.id_login import TklIdLogin, TklIdSettings
from tkl.stallverk import Interlocking, Outcome, UnknownStart, load, plant_of
from tkl.standard import RouteKind, problems
from tkl.store import (
    LOCAL,
    SESSION_LIFETIME,
    SLOT_LIFETIME,
    AlreadySetUp,
    Connection,
    Full,
    HasModel,
    InterlockingBusy,
    NoModel,
    NotSetUp,
    TklStore,
    TooManyAttempts,
    WrongPin,
    token_hash,
)

SESSION = "tkl_session"
SLOT = "tkl_station"
REPO = Path(__file__).resolve().parent.parent
SessionCookie = Annotated[str | None, Cookie(alias=SESSION, max_length=120)]
SlotCookie = Annotated[str | None, Cookie(alias=SLOT, max_length=120)]
IdLoginCookie = Annotated[str | None, Cookie(alias="tkl_id_login", max_length=120)]
LOGGER = logging.getLogger("tkl")
ADDRESS = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]{1,120}$")
NOT_CONNECTED = "TKL är inte ansluten till en träff."
NO_CONTACT = "Ingen kontakt med hubben."
MODEL_LIMIT = 8 * 1024 * 1024
"""The largest model file TKL takes, in bytes."""
NO_MODEL = (
    "Stationen har ingen spårplan. Ställverket på nivå 1–2 behöver en stationsmodell "
    "(Spårplan i Studio)."
)
BUSY = (
    "Ställverket har lagda vägar eller tågnummer. Lös ut vägarna och ta bort tågnumren i "
    "Ställverket, eller nollställ det med tågnumren, innan stationsmodellen byts."
)
WAIT_SECONDS = 25.0
WAIT_STEP = 0.2


def web_dir() -> Path:
    found = os.environ.get("TKL_WEB_DIR", "").strip()
    return Path(found) if found else REPO / "apps" / "tkl" / "dist"


def create_app(
    data_dir: Path,
    *,
    mode: TklMode = TklMode.LOCAL,
    over_internet: list[str] | None = None,
    http: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=TIMEOUT),
    stream: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=None),
    discover: Callable[[], list[str]] = browse,
    id_settings: TklIdSettings | None = None,
) -> FastAPI:
    """mode: one station on the station's computer, or one per browser in the cloud.
    over_internet: the hubs TKL may reach over the internet; in the cloud, the only ones.
    id_settings: the login with TrainMeet ID and the cloud hub for the station packages (#78)."""
    store = TklStore(data_dir / "tkl.sqlite3")
    internet = [a.rstrip("/") for a in (over_internet or [])]
    cloud = mode == TklMode.CLOUD
    app = FastAPI(title="TrainMeet TKL", version=VERSION, docs_url=None, redoc_url=None)
    app.state.store = store
    routes = APIRouter(prefix="/api/tkl/1")
    client = http()

    def slot_of(slot: str | None) -> str | None:
        if not cloud:
            return LOCAL
        return token_hash(slot) if slot else None

    def same_site(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(403, "Ändra TKL från TKL:s egen sida.")

    def secure(request: Request) -> bool:
        return request.url.scheme == "https" or (
            request.headers.get("x-forwarded-proto") == "https"
        )

    def state(slot: str | None, session: str | None) -> dict[str, Any]:
        found = store.station_of(slot)
        return TklState(
            mode=mode,
            software=f"TKL {VERSION}",
            set_up=found is not None,
            unlocked=found is not None and store.unlocked(slot, session),
            station=found,
        ).model_dump(mode="json")

    def opened(request: Request, response: Response, token: str) -> None:
        response.set_cookie(
            SESSION,
            token,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            httponly=True,
            samesite="strict",
            secure=secure(request),
        )

    def unlocked(slot: str | None, session: str | None) -> str:
        found = slot_of(slot)
        if found is None or not store.unlocked(found, session):
            raise HTTPException(401, "Lås upp TKL med PIN-koden.")
        return found

    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"

    @routes.get("/state")
    def get_state(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        return state(slot_of(slot), session)

    @routes.post("/setup", status_code=201)
    def set_up(change: TklSetUp, request: Request, response: Response) -> dict[str, Any]:
        """Första start: Gör den här datorn till stationens ställverk. In the cloud each
        browser gets a station of its own."""
        same_site(request)
        no_store(response)
        given = token_urlsafe(32) if cloud else None
        slot = token_hash(given) if given else LOCAL
        try:
            token = store.set_up(slot, change.station_id, change.name, change.pin)
        except AlreadySetUp as error:
            raise HTTPException(409, "TKL har redan en station.") from error
        except Full as error:
            raise HTTPException(429, "TKL i molnet har inte plats för fler stationer.") from error
        if given:
            response.set_cookie(
                SLOT,
                given,
                max_age=int(SLOT_LIFETIME.total_seconds()),
                httponly=True,
                samesite="strict",
                secure=secure(request),
            )
        opened(request, response, token)
        return state(slot, token)

    @routes.post("/unlock")
    def unlock(
        given: TklUnlock, request: Request, response: Response, slot: SlotCookie = None
    ) -> dict[str, Any]:
        same_site(request)
        no_store(response)
        found = slot_of(slot)
        if found is None:
            raise HTTPException(404, "Ingen station i den här webbläsaren.")
        try:
            token = store.unlock(found, given.pin)
        except NotSetUp as error:
            raise HTTPException(404, "Ingen station i den här webbläsaren.") from error
        except TooManyAttempts as error:
            raise HTTPException(429, "För många fel. Vänta några minuter.") from error
        except WrongPin as error:
            raise HTTPException(401, "Fel PIN-kod.") from error
        opened(request, response, token)
        return state(found, token)

    @routes.post("/lock")
    def lock(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        same_site(request)
        no_store(response)
        store.lock(session)
        response.delete_cookie(SESSION)
        return state(slot_of(slot), None)

    @routes.post("/pin", status_code=204)
    def change_pin(
        change: TklPinChange,
        request: Request,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Response:
        same_site(request)
        found = unlocked(slot, session)
        try:
            store.change_pin(found, change.old, change.new, session or "")
        except TooManyAttempts as error:
            raise HTTPException(429, "För många fel. Vänta några minuter.") from error
        except WrongPin as error:
            raise HTTPException(401, "Fel PIN-kod.") from error
        return Response(status_code=204)

    # --- Studio at level 0 ---------------------------------------------------------------------

    @routes.get("/studio")
    def studio(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        return store.studio(unlocked(slot, session)).model_dump(mode="json")

    @routes.put("/studio")
    def save(
        outside: StationOutside,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        same_site(request)
        no_store(response)
        try:
            return store.save_draft(unlocked(slot, session), outside).model_dump(mode="json")
        except HasModel as error:
            raise HTTPException(
                409,
                "Utsidan räknas fram ur stationens spårplan. Ta bort stationsmodellen i Spårplan "
                "för att skriva listan själv.",
            ) from error

    @routes.post("/studio/version")
    def new_version(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        same_site(request)
        no_store(response)
        return store.new_version(unlocked(slot, session)).model_dump(mode="json")

    # --- The station's model and the reference stations (#83) -------------------------------

    def refuse_model(message: str, found: list[str]) -> NoReturn:
        raise HTTPException(422, {"message": message, "problems": found})

    def keep_model(found: str, model: StationModel) -> dict[str, Any]:
        """Kept with the station only when it may run: no problems, notes are fine. The
        checks include that the outside can be derived, which the station then gets."""
        wrong = problems(model)
        if wrong:
            refuse_model("Stationsmodellen kan inte köras. Rätta den och importera igen.", wrong)
        try:
            kept = store.save_model(found, model)
        except InterlockingBusy as error:
            raise HTTPException(409, BUSY) from error
        return track_plan.view(kept).model_dump(mode="json")

    @routes.get("/studio/model")
    def station_model(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        model = store.station_model(unlocked(slot, session))
        if model is None:
            raise HTTPException(404, "Stationen har ingen stationsmodell än.")
        return track_plan.view(model).model_dump(mode="json")

    @routes.put("/studio/model")
    async def import_model(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Importera en stationsmodell (<station>.tkl.json): checked, kept with the station,
        and the station's level follows it."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        body = await request.body()
        if len(body) > MODEL_LIMIT:
            raise HTTPException(413, "Filen är för stor för en stationsmodell.")
        try:
            model = StationModel.model_validate_json(body)
        except ValidationError as error:
            said = [
                f"{'.'.join(str(part) for part in e['loc']) or 'filen'}: {e['msg']}"
                for e in error.errors()[:5]
            ]
            refuse_model("Filen är inte en stationsmodell (trainmeet.station-model/1).", said)
        return keep_model(found, model)

    @routes.delete("/studio/model")
    def forget_model(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        try:
            store.forget_model(found)
        except InterlockingBusy as error:
            raise HTTPException(409, BUSY) from error
        return store.studio(found).model_dump(mode="json")

    @routes.get("/referens")
    def references(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> list[dict[str, Any]]:
        """Referensstationerna (TKL40): to look at, and to try as one's own."""
        unlocked(slot, session)
        return [r.model_dump(mode="json") for r in track_plan.references()]

    @routes.get("/referens/{station_id}")
    def reference(
        station_id: str, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        unlocked(slot, session)
        found = track_plan.reference_view(station_id)
        if found is None:
            raise HTTPException(404, "Ingen referensstation med det id:t.")
        return found.model_dump(mode="json")

    @routes.post("/referens/{station_id}/use")
    def use_reference(
        station_id: str,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Använd som min station: the reference model becomes the station's, so that a friend
        can try it in TKL in the cloud without a file."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        model = track_plan.reference(station_id)
        if model is None:
            raise HTTPException(404, "Ingen referensstation med det id:t.")
        return keep_model(found, model)

    # --- Manöver, the owner's free panel (STV-46) ---------------------------------------------

    @routes.get("/studio/manover")
    def manover_settings(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        """Manöver's settings: the symbols, the owner's labels and what is shown. The same on
        every screen; the defaults until the owner chooses. Labels for what the panel lacks are
        left out."""
        no_store(response)
        found = unlocked(slot, session)
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, "Stationen har ingen stationsmodell än.")
        kept = store.manover(found)
        return manover.shown(track_plan.panel_of(model), kept).model_dump(mode="json")

    @routes.put("/studio/manover")
    def save_manover(
        settings: TklManover,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Manöver's settings, kept with the station's model. Every label must name a track, a
        signal or a switch on the panel, else nothing is kept. Sends no order (STV-18)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, "Stationen har ingen stationsmodell än.")
        wrong = manover.problems(track_plan.panel_of(model), settings)
        if wrong:
            raise HTTPException(
                422, {"message": "Manövers inställningar sparades inte.", "problems": wrong}
            )
        try:
            return store.save_manover(found, settings).model_dump(mode="json")
        except NoModel as error:
            raise HTTPException(404, "Stationen har ingen stationsmodell än.") from error

    # --- TrainMeet ID och molnet (TKL18, SYNK-06, SYNK-30, #78) ------------------------------

    with_id = TklIdLogin(id_settings, client) if id_settings is not None else None

    @routes.get("/id")
    def id_state(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        """Vem som är inloggad med ID, och stationspaketet i molnet."""
        no_store(response)
        found = unlocked(slot, session)
        account = store.account(found) if with_id is not None else None
        versions = store.studio(found).versions
        return TklIdState(
            available=with_id is not None,
            person=account.name if account else None,
            cloud=id_settings.cloud if id_settings else None,
            saved=account.saved if account else None,
            local=versions[0].number if versions else None,
        ).model_dump(mode="json")

    @routes.get("/id/login")
    def id_log_in(
        request: Request, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Response:
        """To ID's login page, and back to TKL."""
        found = unlocked(slot, session)
        if with_id is None:
            raise HTTPException(404, "TKL har ingen inloggning med TrainMeet ID.")
        state, nonce = token_urlsafe(24), token_urlsafe(24)
        verifier = token_urlsafe(48)
        key = store.begin_id_login(found, state, nonce, verifier)
        response = RedirectResponse(with_id.address(state, nonce, verifier), status_code=303)
        response.set_cookie(
            id_login.COOKIE,
            key,
            max_age=id_login.LIFETIME_SECONDS,
            httponly=True,
            samesite="lax",  # ID sends the browser back with a plain link
            secure=secure(request),
            path=id_login.COOKIE_PATH,
        )
        return response

    @routes.get("/id/callback")
    def id_callback(
        attempt: IdLoginCookie = None,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        """Back from ID: the person and ID's tokens are kept with the station."""
        if with_id is None:
            raise HTTPException(404, "TKL har ingen inloggning med TrainMeet ID.")
        taken = store.take_id_login(attempt)
        response = RedirectResponse("/?id=fel", status_code=303)
        response.delete_cookie(id_login.COOKIE, path=id_login.COOKIE_PATH)
        if taken is None or error or not code or not state:
            LOGGER.warning("Inloggningen med ID i TKL gick inte: inget försök eller ett fel.")
            return response
        found, kept_state, nonce, verifier = taken
        if not secrets.compare_digest(state, kept_state):
            LOGGER.warning("Inloggningen med ID i TKL gick inte: fel state.")
            return response
        try:
            tokens = with_id.finish(code, verifier, nonce)
        except id_login.IdFailed as failed:
            LOGGER.warning("Inloggningen med ID i TKL gick inte: %s", failed)
            return response
        store.keep_account(
            found, tokens.person, tokens.name, tokens.access, tokens.refresh, tokens.access_until
        )
        response.headers["location"] = "/"
        return response

    @routes.post("/id/logout")
    def id_log_out(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        same_site(request)
        found = unlocked(slot, session)
        store.forget_account(found)
        return id_state(response, slot, session)

    @routes.post("/id/save")
    def save_in_cloud(
        asked: TklSave,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Spara i molnet: the latest version of the outside as a new version of the station
        package, on top of the one TKL knows, or the one the owner chose (H71)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        account = store.account(found) if with_id is not None else None
        if with_id is None or account is None:
            raise HTTPException(401, "Logga in med TrainMeet ID först.")
        if id_settings is None or not id_settings.cloud:
            raise HTTPException(409, "Ingen molnhubb är inställd för stationspaketen.")
        access = account.access
        if time.time() > account.access_until - 30:
            if account.refresh is None:
                raise HTTPException(401, "Logga in med TrainMeet ID igen.")
            try:
                access, refresh, until = with_id.refreshed(account.refresh)
            except id_login.IdFailed as failed:
                LOGGER.warning("ID:s token förnyades inte: %s", failed)
                raise HTTPException(401, "Logga in med TrainMeet ID igen.") from failed
            store.new_tokens(found, access, refresh, until)
        number, outside, model = store.latest_package(found)
        inside: dict[str, object] = {} if model is None else {"station_model": dump(model)}
        settings = store.manover_of_version(found, number) if model is not None else None
        if settings is not None:
            inside["manover"] = settings.model_dump(mode="json", exclude_defaults=True)
        package = StationPackage(station_id=outside.station_id, outside=outside, inside=inside)
        base = asked.on_top if asked.on_top is not None else (account.saved or 0)
        address = f"{id_settings.cloud}/api/sync/1/stations/{outside.station_id}/versions"
        try:
            answer = client.post(
                address,
                params={"base": base},
                content=package.model_dump_json(),
                headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            )
        except httpx.HTTPError as error:
            raise HTTPException(503, "Molnhubben svarar inte. Försök igen.") from error
        if answer.status_code == 201:
            version = int(answer.json()["version"])
            store.saved_in_cloud(found, version)
            return TklSaved(version=version).model_dump(mode="json")
        if answer.status_code == 409 and answer.headers.get("TrainMeet-Latest", "").isdigit():
            latest = int(answer.headers["TrainMeet-Latest"])
            store.saved_in_cloud(found, latest)
            return TklSaved(
                behind=latest,
                message=f"Molnet har version {latest}, sparad från en annan dator. Spara ovanpå "
                "den om stationen på den här datorn är den som gäller.",
            ).model_dump(mode="json")
        if answer.status_code in (401, 403):
            raise HTTPException(401, "Molnhubben godtog inte inloggningen. Logga in med ID igen.")
        LOGGER.warning("Molnhubben svarade %s på stationspaketet.", answer.status_code)
        raise HTTPException(502, "Molnhubben sparade inte stationspaketet.")

    # --- Connecting to the meet ----------------------------------------------------------------

    @routes.get("/hubs")
    def hubs(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> list[dict[str, Any]]:
        no_store(response)
        unlocked(slot, session)
        found = find_hubs(client, (lambda: []) if cloud else discover, internet)
        return [hub.model_dump(mode="json") for hub in found]

    def hub(made: Connection) -> HubClient:
        return HubClient(client, made.address, made.relay, made.key)

    def shown(made: Connection | None) -> dict[str, Any]:
        if made is None:
            return TklConnection(connected=False).model_dump(mode="json")
        return TklConnection(
            connected=True,
            address=made.address,
            hub_name=made.hub_name,
            status=made.status,
            places=made.places,
            outside_version=made.outside_version,
            message=made.message,
        ).model_dump(mode="json")

    def follow(found: str, made: Connection) -> Connection:
        """Ask the hub how the approval stands while TKL waits; the key comes once."""
        if made.status != station.ApprovalStatus.WAITING and made.key is not None:
            return made
        try:
            reply = hub(made).connection(made.client_id)
        except Unreachable:
            return made
        except HubError as error:
            if error.status == 404:
                store.approval(
                    found,
                    station.ApprovalStatus.REVOKED,
                    [],
                    None,
                    "Hubben känner inte igen TKL längre. Anslut igen.",
                )
                return store.connection(found) or made
            return made
        store.approval(found, reply.status, reply.places, reply.key, reply.message)
        return store.connection(found) or made

    @routes.get("/connection")
    def connection(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        found = unlocked(slot, session)
        made = store.connection(found)
        return shown(follow(found, made) if made else None)

    def checked(address: str) -> str:
        address = address.strip().rstrip("/")
        if cloud and address not in internet:
            raise HTTPException(422, "TKL i molnet når bara de hubbar den är inställd för.")
        if not ADDRESS.match(address):
            raise HTTPException(422, "Skriv hubbens adress, till exempel http://trainmeet.local.")
        return address

    @routes.post("/connection")
    def connect(
        given: TklConnect,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Anslut: TKL says which station it is and brings its outside (KLAR-02, KLAR-12)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        address = checked(given.address)
        own = store.station_of(found)
        assert own is not None
        number, outside = store.latest_outside(found)
        request_ = station.ConnectRequest(
            kind=station.ClientKind.TKL,
            name=f"TKL {own.name}",
            software=f"TKL {VERSION}",
            station_id=own.station_id,
            outside=outside,
            code=(given.code or "").strip() or None,
        )
        reaching = HubClient(client, address)
        try:
            reply = reaching.connect(request_)
        except Unreachable as error:
            raise HTTPException(502, NO_CONTACT) from error
        except HubError as error:
            raise HTTPException(
                error.status if error.status < 500 else 502, error.detail
            ) from error
        described = reaching.describe(nearby=address not in internet)
        store.connected(
            found,
            Connection(
                address=address,
                relay=reply.relay,
                hub_name=described.name if described else None,
                client_id=reply.client_id,
                status=reply.status,
                places=reply.places,
                outside_version=number,
                message=reply.message,
                key=reply.key,
            ),
        )
        return shown(store.connection(found))

    @routes.delete("/connection")
    def disconnect(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        store.disconnect(found)
        return shown(None)

    # --- The place: snapshot, commands, exits and hints ----------------------------------------

    def approved(found: str, place: str) -> Connection:
        made = store.connection(found)
        if made is not None and made.key is None:
            made = follow(found, made)
        if made is None or made.key is None:
            raise HTTPException(409, NOT_CONNECTED)
        if place not in made.places:
            raise HTTPException(403, "TKL är inte godkänd för den driftplatsen.")
        return made

    def refused(found: str, error: HubError) -> NoReturn:
        if error.status == 401:
            store.approval(
                found,
                station.ApprovalStatus.REVOKED,
                [],
                None,
                "Nyckeln gäller inte längre. Anslut igen.",
            )
        raise HTTPException(error.status, error.detail) from error

    def seen(found: str, place: str, message: str) -> dict[str, Any]:
        last = store.last_seen(found, place)
        if last is None:
            return TklView(stale=True, message=message).model_dump(mode="json")
        snapshot, heard = last
        return TklView(snapshot=snapshot, stale=True, heard=heard, message=message).model_dump(
            mode="json"
        )

    @routes.get("/places/{place}")
    def place_view(
        place: str, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        found = unlocked(slot, session)
        made = approved(found, place)
        try:
            snapshot = hub(made).snapshot(place)
        except Unreachable:
            return seen(found, place, NO_CONTACT)
        except HubError as error:
            refused(found, error)
        heard = store.remember(found, snapshot)
        return TklView(snapshot=snapshot, heard=heard).model_dump(mode="json")

    @routes.post("/commands")
    def command(
        given: TklCommand,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """One command, as the web app made it; TKL adds who it is and the key. Never done
        locally: the hub's answer and snapshot are what count (old TKL)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        made = approved(found, given.place)
        sent = station.Command(client_id=made.client_id, **given.model_dump())
        try:
            reply = hub(made).command(sent)
        except Unreachable as error:
            raise HTTPException(502, NO_CONTACT) from error
        except HubError as error:
            refused(found, error)
        store.remember(found, reply.snapshot)
        return reply.model_dump(mode="json")

    @routes.post("/places/{place}/exits")
    def exits(
        place: str,
        answer: station.ExitAnswer,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Hubben frågar om en utfart; stationen svarar här (H26, TRAFIK-05)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        made = approved(found, place)
        try:
            snapshot = hub(made).exit(place, answer)
        except Unreachable as error:
            raise HTTPException(502, NO_CONTACT) from error
        except HubError as error:
            refused(found, error)
        heard = store.remember(found, snapshot)
        return TklView(snapshot=snapshot, heard=heard).model_dump(mode="json")

    @routes.get("/places/{place}/events")
    async def events(
        place: str, request: Request, slot: SlotCookie = None, session: SessionCookie = None
    ) -> StreamingResponse:
        """The hub's hints that the place changed, passed on. The web app fetches the place
        again on each; when the stream ends it asks again after a while."""
        found = unlocked(slot, session)
        made = approved(found, place)

        async def hints() -> AsyncIterator[bytes]:
            async with stream() as passing:
                for base in [made.address, *([made.relay] if made.relay else [])]:
                    try:
                        async with passing.stream(
                            "GET",
                            f"{base}/api/station/1/places/{place}/events",
                            headers={"Authorization": f"Bearer {made.key}"},
                        ) as answer:
                            if answer.status_code != 200:
                                yield b"event: gone\ndata: {}\n\n"
                                return
                            async for chunk in answer.aiter_raw():
                                if await request.is_disconnected():
                                    return
                                yield chunk
                            return
                    except httpx.HTTPError:
                        continue
                yield b"event: gone\ndata: {}\n\n"

        return StreamingResponse(
            hints(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # --- Ställverket at level 1–2 (#84) ---------------------------------------------------------

    def interlocking_of(found: str) -> Interlocking:
        model, revision, body = store.interlocking(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        return load(plant_of(model), revision, body)

    def answered(outcome: Outcome, state: TklInterlocking, reports: list[TklReport]) -> Any:
        return TklAnswer(
            accepted=outcome.accepted,
            message=outcome.message,
            route=outcome.route,
            state=state,
            reports=reports,
        ).model_dump(mode="json")

    def operate(found: str, act: Callable[[Interlocking], Outcome]) -> Any:
        """One operation in one transaction: kept when it changed the state. What it reports
        goes up to the hub afterwards, and how that went is noted in the interlocking."""

        def change(
            model: StationModel | None, revision: int, body: str | None
        ) -> tuple[TklInterlocking | None, tuple[Outcome, TklInterlocking]]:
            if model is None:
                raise HTTPException(404, NO_MODEL)
            made = load(plant_of(model), revision, body)
            outcome = act(made)
            state = made.view()
            return (state if made.revision != revision else None), (outcome, state)

        outcome, state = store.change_interlocking(found, change)
        if outcome.accepted and outcome.reports:
            reports = report(found, list(outcome.reports))
            noted = [hub_reports.said(r) for r in reports if r.kind != TklReportKind.EXIT_SIGNAL]
            if noted:
                state = note(found, noted) or state
        else:
            reports = list(outcome.reports)
        if outcome.accepted and "Nödutlösning" in outcome.message:
            LOGGER.warning("Ställverket: %s", outcome.message)
        return answered(outcome, state, reports)

    def note(found: str, lines: list[str]) -> TklInterlocking | None:
        """How the reports went, in the interlocking's events, for every screen to see."""

        def change(
            model: StationModel | None, revision: int, body: str | None
        ) -> tuple[TklInterlocking | None, TklInterlocking | None]:
            if model is None:
                return None, None
            made = load(plant_of(model), revision, body)
            if made.problem is not None:
                return None, None
            for line in lines:
                made.note(line)
            state = made.view()
            return state, state

        return store.change_interlocking(found, change)

    def one_place(found: str) -> tuple[Connection, str] | str:
        made = store.connection(found)
        if made is not None and made.key is None:
            made = follow(found, made)
        if made is None or made.key is None:
            return NOT_CONNECTED
        if len(made.places) != 1:
            return "TKL är godkänd för flera driftplatser."
        return made, made.places[0]

    def report(found: str, reports: list[TklReport]) -> list[TklReport]:
        """Up to the hub (STV-10), with the place's own snapshot for the calls."""
        reached = one_place(found)
        if isinstance(reached, str):
            said = f"{reached} Inget rapporterades till hubben."
            return [r.model_copy(update={"message": said}) for r in reports]
        made, place = reached
        try:
            snapshot = hub(made).snapshot(place)
        except Unreachable:
            return [r.model_copy(update={"message": NO_CONTACT}) for r in reports]
        except HubError as error:
            return [r.model_copy(update={"message": error.detail}) for r in reports]
        done, last = hub_reports.send(hub(made), made.client_id, place, snapshot, reports)
        store.remember(found, last)
        return done

    @routes.get("/stallverk")
    def interlocking(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Ställverkets läge (STV-08): everything the panel draws."""
        no_store(response)
        return interlocking_of(unlocked(slot, session)).view().model_dump(mode="json")

    @routes.get("/stallverk/wait")
    async def interlocking_wait(
        response: Response,
        after: int = Query(ge=0),
        seconds: float = Query(default=WAIT_SECONDS, ge=0, le=30),
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Vänta på nästa ändring efter after, högst seconds; then read again. A second
        screen follows the first this way (STV-05)."""
        no_store(response)
        found = await run_in_threadpool(unlocked, slot, session)
        waited = 0.0
        while True:
            revision = await run_in_threadpool(store.interlocking_revision, found)
            if revision is None:
                raise HTTPException(404, NO_MODEL)
            if revision != after or waited >= seconds:
                return TklWait(revision=revision, changed=revision != after).model_dump(mode="json")
            await asyncio.sleep(WAIT_STEP)
            waited += WAIT_STEP

    @routes.get("/stallverk/targets")
    def interlocking_targets(
        response: Response,
        start: str = Query(min_length=1, max_length=80),
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Målen från en start, per vägslag, och om de går att lägga nu (STV-01, STV-24)."""
        no_store(response)
        made = interlocking_of(unlocked(slot, session))
        try:
            return made.targets(start).model_dump(mode="json")
        except UnknownStart as error:
            raise HTTPException(404, str(error)) from error

    @routes.post("/stallverk/route")
    def set_route(
        ask: TklRouteAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        kind = RouteKind(ask.kind.value) if ask.kind is not None else None
        return operate(found, lambda made: made.set_route(ask.start, ask.end, kind))

    @routes.post("/stallverk/release")
    def release(
        ask: TklRouteRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.release(ask.route))

    @routes.post("/stallverk/emergency-release")
    def emergency_release(
        ask: TklEmergencyRelease,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        return operate(found, lambda made: made.emergency_release(ask.route, ask.confirm))

    @routes.post("/stallverk/lever")
    def lay_lever(
        ask: TklLeverAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        return operate(found, lambda made: made.lay_lever(ask.switch, ask.position))

    @routes.post("/stallverk/step")
    def step(
        ask: TklRouteRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.step(ask.route))

    @routes.post("/stallverk/arrive")
    def arrive(
        ask: TklRouteRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.arrive(ask.route))

    @routes.post("/stallverk/depart")
    def depart(
        ask: TklRouteRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.depart(ask.route))

    def coming(found: str, put: TklTrainPut) -> TklTrainPut | str:
        """A train on its way here, put by its call: its number and exit from the place's
        snapshot (STV-10). Never a guess: a call the snapshot does not have is a no."""
        reached = one_place(found)
        if isinstance(reached, str):
            return reached
        made, place = reached
        try:
            snapshot = hub(made).snapshot(place)
        except (Unreachable, HubError):
            last = store.last_seen(found, place)
            if last is None:
                return NO_CONTACT
            snapshot = last[0]
        train = next((t for t in snapshot.on_the_way if t.call == put.call), None)
        if train is None:
            return f"Tågbesöket {put.call} är inte på väg hit i hubbens bild."
        section = next((s for s in snapshot.sections if s.section == train.section), None)
        if section is None or section.exit is None:
            return (
                f"Hubben vet inte vilken utfart tåg {train.train_number} kommer in vid. Svara på "
                "hubbens fråga om utfarten, eller sätt ut tåget vid en utfart."
            )
        model, _, _ = store.interlocking(found)
        exits = plant_of(model).exits if model is not None else {}
        line = next((e.id for e in exits.values() if e.outside == section.exit), None)
        if line is None:
            return f"Utfarten {section.exit} finns inte i stationsmodellen."
        number = put.number or train.train_number
        if not re.fullmatch(r"[0-9A-Za-z]{1,8}", number):
            return f"Tågnumret {number} går inte att visa i ställverket."
        return put.model_copy(update={"number": number, "exit": line})

    @routes.post("/stallverk/train")
    def put_train(
        put: TklTrainPut,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Sätt ut ett tågnummer på ett spår eller vid en utfart, eller ett tåg på väg hit."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        if put.call is not None and put.section is None and put.exit is None:
            resolved = coming(found, put)
            if isinstance(resolved, str):
                made = interlocking_of(found)
                return answered(Outcome(False, resolved), made.view(), [])
            put = resolved
        return operate(
            found,
            lambda made: made.put_train(
                put.number, call=put.call, section=put.section, exit=put.exit
            ),
        )

    @routes.post("/stallverk/train/remove")
    def remove_train(
        ask: TklTrainRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.remove_train(ask.train))

    @routes.post("/stallverk/reset")
    def reset(
        ask: TklReset,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        return operate(found, lambda made: made.reset(ask.confirm, ask.trains))

    @routes.post("/stallverk/function")
    def panel_function(
        ask: TklFunctionAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Manövrera en panelfunktion ur katalogen (STV-04, STV-53): signalstopp, lokal
        frigivning, körström, ur drift, nödutlösning, vändskivan och programmeringsspåret."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        return operate(
            found,
            lambda made: made.function(ask.function, ask.action, ask.value, confirm=ask.confirm),
        )

    app.include_router(routes)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "at": datetime.now(UTC).isoformat()}

    @app.get("/api/version")
    def version(response: Response) -> dict[str, Any]:
        """What runs, for the deploy's check: the version and the change it was built from."""
        no_store(response)
        commit = os.environ.get("TRAINMEET_COMMIT", "").strip() or None
        return Version(
            product="TrainMeet TKL",
            version=VERSION,
            hub_name="TKL i molnet" if cloud else "TKL",
            commit=commit,
        ).model_dump(mode="json")

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> Response:
        """The web app: its files, and index.html for every page of it."""
        root = web_dir()
        if path.startswith("api/"):
            raise HTTPException(404)
        wanted = (root / path).resolve()
        if path and wanted.is_file() and root.resolve() in wanted.parents:
            return FileResponse(wanted)
        index = root / "index.html"
        if not index.is_file():
            return Response("TKL:s webbapp är inte byggd: npm run build -w apps/tkl", 503)
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    return app


def from_environment() -> FastAPI:
    """TKL_DATA_DIR, TKL_MODE (local or cloud) and TKL_HUBBAR, the hubs over the internet; and
    the login with TrainMeet ID (tkl/id_login.py)."""
    data = Path(os.environ.get("TKL_DATA_DIR", "").strip() or Path.home() / ".trainmeet-tkl")
    mode = TklMode(os.environ.get("TKL_MODE", "local").strip() or "local")
    hubs = [h.strip() for h in os.environ.get("TKL_HUBBAR", "").split(",") if h.strip()]
    found = id_login.settings_from(hubs=hubs if mode == TklMode.CLOUD else None)
    return create_app(data, mode=mode, over_internet=hubs, id_settings=found)
