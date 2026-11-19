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
    GET  /api/tkl/1/studio/rita           TklRita: utkastet, eller stationens modell att rita om
    PUT  /api/tkl/1/studio/rita           TklDrawing -> TklRita (sparas som utkast, med problemen)
    POST /api/tkl/1/studio/rita/use       TklRita (Använd ritningen: 422 med problem, 409 med vägar)
    DELETE /api/tkl/1/studio/rita         TklRita (släng utkastet)
    GET  /api/tkl/1/studio/dela           TklDela: Dela stationen, delarna som utkast eller i bruk
    PUT  /api/tkl/1/studio/dela           TklDelaEdit -> TklDela (utkast, med kontrollerna)
    POST /api/tkl/1/studio/dela/use       TklDela (Använd: 422 med problem, 409 med vägar)
    DELETE /api/tkl/1/studio/dela         TklDela (släng utkastet)
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
approved for the station's place (tkl/hub_reports.py, STV-10). A station with parts that are
their own driftplatser is approved per place (TRAFIK-35, tkl/hub_places.py): a report goes as the
place whose snapshot knows it, the part's first when it is about a track in the part's area.
TKL keeps following the approval after it has its key, since a part approved later comes with
the same key.

Delställverk (#87, TKL97–TKL103): a part opens its own screen at /del/<id>, on any screen on the
station's network behind the same PIN (TKL102). The station answers in Ställverket; the part
acts under its own path, and the interlocking checks the part's rights at the border:

    POST /api/tkl/1/stallverk/parts/reply              TklPartReply: svar, Godkänn or Neka
    POST /api/tkl/1/stallverk/parts/ring-answer        TklPartRef: the station answers a ring
    POST /api/tkl/1/stallverk/ready/move               TklReadyMove: Klara att skicka, moved
    POST /api/tkl/1/stallverk/ready/sent               TklReadyRef: Skickat
    GET  /api/tkl/1/stallverk/parts/{part}/trains      TklPartTrains: the plan's trains (TKL108)
    GET  /api/tkl/1/stallverk/parts/{part}/targets     TklTargets: goals inside the area
    POST /api/tkl/1/stallverk/parts/{part}/route       TklRouteAsk: a shunting route in the area
    POST /api/tkl/1/stallverk/parts/{part}/release     TklRouteRef: one of its own routes
    POST /api/tkl/1/stallverk/parts/{part}/lever       TklLeverAsk: its own switch, or a border
                                                       switch towards its area (RANG-12)
    POST /api/tkl/1/stallverk/parts/{part}/street      TklPartStreetAsk: a switch street
    POST /api/tkl/1/stallverk/parts/{part}/request     TklPartRequestAsk: begär väg (RANG-10)
    POST /api/tkl/1/stallverk/parts/{part}/return      TklPartRequestRef: lämna tillbaka
    POST /api/tkl/1/stallverk/parts/{part}/done        Klart: everything back (RANG-04)
    POST /api/tkl/1/stallverk/parts/{part}/gates       Grindar: the border switches back
    POST /api/tkl/1/stallverk/parts/{part}/ring        Ring
    POST /api/tkl/1/stallverk/parts/{part}/fika        TklPartFika: the part's screen locked
    POST /api/tkl/1/stallverk/parts/{part}/ready       TklReadyAsk: klart att skicka (TKL108)

The messages between a part and the station are handed to `forward`, the seam for a station
that is remote-controlled through Hubben (TKL100, #36).

Studio's Koppla in at level 3 (#85), LocoNet only in a local TKL (tkl/loconet/service.py); TKL in
the cloud shows the objects and their addresses but never opens a port (TKLMOLN-08):

    GET  /api/tkl/1/studio/koppla-in              TklKopplaIn: the connection, the cards, the
                                                  objects in their four states, the question
    GET  /api/tkl/1/studio/koppla-in/ports        [TklPort]: the port list (STUDIO-11)
    POST /api/tkl/1/studio/koppla-in/connect      TklLoconetConnect: LocoBuffer USB,
                                                  BTLocoBridge or the pretend LocoNet
    POST /api/tkl/1/studio/koppla-in/disconnect
    POST /api/tkl/1/studio/koppla-in/discover     the MGP cards, with module and channel
    PUT  /api/tkl/1/studio/koppla-in/card         TklCardModule: the module a card sits in
    PUT  /api/tkl/1/studio/koppla-in/object       TklObjectChange: address, polarity, feedback
                                                  or Utan adress
    POST /api/tkl/1/studio/koppla-in/learn        TklLearnAsk: Lägg om, Skicka kör, a wagon
    POST /api/tkl/1/studio/koppla-in/answer       TklLearnAnswer: the owner's answer
    POST /api/tkl/1/studio/koppla-in/level        TklLevelAsk: level 3 on or off
    GET  /api/tkl/1/studio/koppla-in/lyssna       TklListen: Lyssna, behind Felsök
    POST /api/tkl/1/studio/koppla-in/latsas       TklPretendAsk: a wagon on the pretend LocoNet

At level 3 with LocoNet the interlocking's orders go out on the bus after every operation.

Stream Deck (#86), the same for the deck on the screen and a real deck, over USB or WebHID.
A deck is known by its serial number (SD35); its faces come from the interlocking and the hub,
and what it does goes through the interlocking's operations above (SD1):

    GET  /api/tkl/1/deck/models                   [TklDeckModel]: Elgato's models (SD52), each
                                                  tried with a real deck or Inte provad (SD58)
    GET  /api/tkl/1/deck/profile?model=           TklDeckProfile: the default for a model (SD39)
    GET  /api/tkl/1/decks                         TklDecks: the decks, how each is connected
    POST /api/tkl/1/deck/{serial}                 TklDeckOpen -> TklDeckView: the deck, opened;
                                                  409 when TKL owns it over USB (SD50)
    POST /api/tkl/1/deck/{serial}/close           the browser let go of its deck (WebHID)
    GET  /api/tkl/1/deck/{serial}                 TklDeckView: every key's face (only the clock
                                                  while TKL is locked, SD30)
    GET  /api/tkl/1/deck/{serial}/key/{i}.png?size=   a key as a real deck shows it, with an ETag
    GET  /api/tkl/1/deck/{serial}/strip.png       the touch strip of + and + XL (SD33)
    GET  /api/tkl/1/deck/{serial}/info.png        Neo's info line (SD34)
    GET  /api/tkl/1/deck/ingen-kontakt.png?size=  Ingen kontakt as a key, for WebHID (SD21)
    POST /api/tkl/1/deck/{serial}/press           TklDeckPress: a press or a hold (SD29)
    POST /api/tkl/1/deck/{serial}/dial            TklDeckDialAsk: a dial (SD83)
    POST /api/tkl/1/deck/{serial}/touch           TklDeckTouch: Neo's touch points (SD82)
    GET  /api/tkl/1/deck/{serial}/wait?after=     TklWait: a long poll for the deck's next change
    GET  /api/tkl/1/deck-favoriter                TklDeckFavourites (SD24)
    POST /api/tkl/1/deck-favoriter                TklDeckPin: Fäst på Stream Deck (SD48)
    PUT  /api/tkl/1/deck/{serial}                 TklDeckChange -> TklDeckStatus: ljusstyrka,
                                                  hålltid, släckning, lås, start och arbetsplats
                                                  (SD46); they reach the deck over USB and WebHID
    POST /api/tkl/1/deck/{serial}/blinka          TklDeckStatus: the deck lights up (SD46)
    DELETE /api/tkl/1/deck/{serial}               Glöm deck: its settings on this computer go

Studio, Inställningar, Stream Deck (#86 del c, SD38–SD47): the owner's deviations from the
default per size, kept with the model and versioned with it like Manöver's settings (SD40, SD49);
every deck uses the owner's profile of its size, on the screen, over USB and with WebHID:

    GET  /api/tkl/1/studio/stream-deck?size=      TklDeckStudio: Sidor for one size, with Att
                                                  kolla, the checks (SD44) and Knappar (SD41)
    POST /api/tkl/1/studio/stream-deck/utkast     TklDeckEdit -> TklDeckStudio: shown, not kept
    PUT  /api/tkl/1/studio/stream-deck            TklDeckEdit -> TklDeckStudio: kept; 422 with
                                                  the reasons when a change may not be made (SD43)
    POST /api/tkl/1/studio/stream-deck/foresla    TklDeckSuggest -> TklDeckStudio: Föreslå (SD45)
    GET  /api/tkl/1/studio/stream-deck/prova?size= TklDeckProva: Prova alla knappar (SD47)
    POST /api/tkl/1/studio/stream-deck/prova/start TklDeckProvaAsk: in the background, against an
                                                  empty interlocking, never the live one
    POST /api/tkl/1/studio/stream-deck/prova/stop

A deck opens as the tågklarerare or as a part of the station, its role (#87 del d): set in Studio,
Deck, or given when the deck on a part's screen /del/<id> opens it. A part's deck has the mode
Bangård only, the shunter's deck, whose keys go through the part's operations above; the owner's
changes for it are kept per part and size, and Sidor and Prova take `part`.

A local TKL owns its decks over USB in the background (tkl/deck/usb.py), so that they work
without an open tab; TKL in the cloud never opens USB, and there Chrome and Edge drive a deck with
WebHID through the pictures above (SD50). Lås, in TKL's header or on the page Läge of a deck
(Fika), locks TKL for the whole station: every session ends, every deck shows only the clock, and
the PIN opens it again (SD30, TKL18).

Every route set, from the panel or a deck, is counted in TKL's runtime data (SD24, SD49).

Studio's Prova (#85 del c, STUDIO-05, STUDIO-12, STUDIO-21, STUDIO-27): the simulated test, a
train through every route, in the background (tkl/prova.py), and Provkör on the real layout with
LocoNet connected (tkl/provkor.py):

    GET  /api/tkl/1/studio/prova                  TklProva: the progress, the results, Klart
    POST /api/tkl/1/studio/prova/start            start the simulated test
    POST /api/tkl/1/studio/prova/stop             stop it
    POST /api/tkl/1/studio/prova/provkor/start    Provkör: each route on the layout
    POST /api/tkl/1/studio/prova/provkor/answer   TklProvkorAnswer: right, wrong or skip
    POST /api/tkl/1/studio/prova/provkor/stop

Prova connects only to a preview run in the hub, never to a real meet (STUDIO-12): Anslut from
Prova, or while the pretend LocoNet is connected, needs the run's code and a hub that says the
run is Provbanan's; the pretend LocoNet is refused while TKL is connected to a real meet, and
nothing it reports goes up to one.

While the station has a model, Studio's list is its outside derived from the model (STD-08,
TKL92): it is shown but not written, and a new version is made as before (TKL25).

Rita (#85): the owner draws the station on the grid, or redraws the panel of the one it has
(STUDIO-02, STUDIO-30). The drawing is kept as a draft, problems and all; the same drawing as
the station's model is no draft. Använd ritningen makes it the station's model as an import
does: refused with the problems while it has any, and while the interlocking has set routes or
train numbers.

Fjärrstyrning (#36 del c, tkl/fjarr/): TKL started in the remote role is a remote interlocking
with no station of its own (FR1, TKL47); it connects as the station protocol's client kind remote
with its remote area (FR4). A station's own TKL controls a neighbour with the same fjärrbild, as
the same client (FR3). Hubben decides which places TKL may read and act on:

    POST /api/tkl/1/fjarr/setup                   TklRemoteSetUp -> TklState: första start som
                                                  Fjärrställverk (ingen egen station)
    GET  /api/tkl/1/fjarr/areas?address=          TklRemoteAreas: the plan's remote areas (FR49)
    POST /api/tkl/1/fjarr/connection              TklRemoteConnect -> TklConnection (kind remote)
    GET  /api/tkl/1/fjarr                         TklFjarr: the overview, and what TKL controls and
                                                  is offered (FR8, FR31–FR38)
    GET  /api/tkl/1/fjarr/places/{place}          TklView: a station TKL controls, for Klarering
    POST /api/tkl/1/fjarr/commands                TklCommand -> station.Reply: place.offer.answer,
                                                  route.request, route.cancel and the clearance
                                                  for the whole station (FR11, FR13, FR17)

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
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated, Any, Literal, NoReturn
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathPart
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import ValidationError

from contracts import station
from contracts.hub import Version
from contracts.station_model import StationModel, StationPart, dump
from contracts.station_outside import StationOutside
from contracts.sync import StationPackage
from contracts.tkl import (
    DeckConnection,
    DeckModelId,
    Panel,
    TklAnswer,
    TklCardModule,
    TklCommand,
    TklConnect,
    TklConnection,
    TklDeckChange,
    TklDeckDeviations,
    TklDeckDialAsk,
    TklDeckEdit,
    TklDeckOpen,
    TklDeckPin,
    TklDeckPress,
    TklDeckProvaAsk,
    TklDeckRoute,
    TklDecks,
    TklDeckSettings,
    TklDeckStatus,
    TklDeckSuggest,
    TklDeckTouch,
    TklDelaEdit,
    TklDelaState,
    TklDrawing,
    TklDrawingState,
    TklEmergencyRelease,
    TklFjarr,
    TklFunctionAction,
    TklFunctionAsk,
    TklIdState,
    TklInterlocking,
    TklLearnAnswer,
    TklLearnAsk,
    TklLevelAsk,
    TklLeverAsk,
    TklListen,
    TklLoconetConnect,
    TklManover,
    TklMode,
    TklObjectChange,
    TklPartFika,
    TklPartMessage,
    TklPartRef,
    TklPartReply,
    TklPartRequestAsk,
    TklPartRequestRef,
    TklPartStreetAsk,
    TklPartTrain,
    TklPartTrains,
    TklPinChange,
    TklPretendAsk,
    TklProvkor,
    TklProvkorAnswer,
    TklReadyAsk,
    TklReadyMove,
    TklReadyRef,
    TklRemote,
    TklRemoteConnect,
    TklRemoteSetUp,
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
from tkl import VERSION, fjarr, hub_places, hub_reports, id_login, manover, prova, track_plan
from tkl.deck import deviations as deck_deviations
from tkl.deck import logic as deck_logic
from tkl.deck import look as deck_look
from tkl.deck import render as deck_render
from tkl.deck import service as deck_service
from tkl.deck import studio as deck_studio
from tkl.deck import suggest as deck_suggest
from tkl.deck import tryall as deck_tryall
from tkl.deck import usb as deck_usb
from tkl.deck.models import BY_ID as DECK_BY_ID
from tkl.deck.models import MODELS as DECK_MODELS
from tkl.deck.models import name_of as deck_name
from tkl.deck.profile import build as deck_profile
from tkl.deck.profile import geography_of
from tkl.deck.service import Shown
from tkl.hub_client import TIMEOUT, HubClient, HubError, Unreachable, browse, find_hubs
from tkl.id_login import TklIdLogin, TklIdSettings
from tkl.loconet import service as loconet
from tkl.provkor import NoQuestion, Provkor, idle
from tkl.stallverk import Interlocking, Outcome, Plant, UnknownStart, load, plant_of
from tkl.stallverk.interlocking import KOPPLA_IN, Order
from tkl.stallverk.parts import Part, plan_trains
from tkl.standard import LayoutError, RouteKind, problems
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
from tkl.studio import dela, rita

SESSION = "tkl_session"
SLOT = "tkl_station"
REPO = Path(__file__).resolve().parent.parent
SessionCookie = Annotated[str | None, Cookie(alias=SESSION, max_length=120)]
SlotCookie = Annotated[str | None, Cookie(alias=SLOT, max_length=120)]
IdLoginCookie = Annotated[str | None, Cookie(alias="tkl_id_login", max_length=120)]
PartId = Annotated[str, PathPart(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")]
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
DECK_FRESH = 5.0
"""The deck reads the place's snapshot from Hubben when the last one is older than this."""
WAIT_STEP = 0.2
LOCKED = "TKL är låst. PIN-koden låser upp."
OWNED = "Decket sköts av TKL över USB."
SERIAL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
PROVA_CODE = (
    "Prova ansluts bara till en provkörning i Provbanan, aldrig till en riktig träff "
    "(STUDIO-12). Skriv provkörningens kod."
)
NOT_PREVIEW = (
    "Hubben säger att det är en riktig träff. Prova ansluts bara till en provkörning i "
    "Provbanan, aldrig till en riktig träff (STUDIO-12)."
)
NOT_TO_A_MEET = (
    "Prova rapporterar aldrig till en riktig träff (STUDIO-12). Inget rapporterades till hubben."
)
PROVA_BUSY = "Prova provar så många stationer det hinner just nu. Försök igen om en stund."
PROVKOR_LEVEL = f"Provkör kräver nivå 3. Slå på den i {KOPPLA_IN}."
PROVKOR_LAYOUT = (
    f"Provkör kräver LocoNet anslutet till banan i {KOPPLA_IN}. Låtsas-LocoNet provas med Prova."
)
PROVKOR_BUSY = (
    "Ställverket har lagda vägar eller tågnummer. Lös ut vägarna och ta bort tågnumren innan "
    "Provkör, så att inget läggs om under ett tåg."
)
PROVKOR_IDLE = "Provkör är inte igång."
PROVKOR_WAITS = "Provkör väntar på återrapporten. Svara när vägen ligger, eller hoppa över den."


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
    loconet_settings: loconet.Settings | None = None,
    usb_finder: deck_usb.Finder | None = None,
) -> FastAPI:
    """mode: one station on the station's computer, or one per browser in the cloud.
    over_internet: the hubs TKL may reach over the internet; in the cloud, the only ones.
    id_settings: the login with TrainMeet ID and the cloud hub for the station packages (#78).
    loconet_settings: how a local TKL reaches LocoNet (#85); the cloud never does.
    usb_finder: how a local TKL finds its Stream Decks on USB (#86, SD50), by default through
    libhidapi; the cloud never looks. The driver runs while the app's lifespan does."""
    store = TklStore(data_dir / "tkl.sqlite3")
    roles = fjarr.Roles(data_dir / "fjarr.sqlite3")
    internet = [a.rstrip("/") for a in (over_internet or [])]
    cloud = mode == TklMode.CLOUD
    services: list[loconet.Service] = []
    starting: list[Callable[[], None]] = []
    stopping: list[Callable[[], None]] = []

    runner = prova.Runner()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for start in starting:
            start()
        yield
        for stop in stopping:
            await run_in_threadpool(stop)
        runner.close()
        for running in services:
            running.close()

    app = FastAPI(
        title="TrainMeet TKL", version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan
    )
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
            locked=found is not None and store.station_locked(slot),
            remote=roles.role(slot) if found is not None else None,
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
        """Lås: TKL is locked for the whole station, not only in this browser (SD30). Every
        session ends and every deck shows only the clock until the PIN opens TKL again."""
        same_site(request)
        no_store(response)
        found = slot_of(slot)
        if found is not None:
            store.lock_station(found)
        store.lock(session)
        response.delete_cookie(SESSION)
        return state(found, None)

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

    # --- Rita (#85): the station drawn on the grid, kept as a draft until it is used ------------

    def drawn(found: str) -> tuple[TklDrawing, TklDrawingState]:
        """The owner's draft; else the station's model as a drawing; else a new one."""
        draft = store.drawing(found)
        if draft is not None:
            return draft, TklDrawingState.DRAFT
        model = store.station_model(found)
        if model is None:
            own = store.station_of(found)
            assert own is not None
            return rita.empty(own.station_id, own.name), TklDrawingState.NEW
        try:
            return rita.drawing_of(model), TklDrawingState.IN_USE
        except LayoutError as error:
            raise HTTPException(
                409, f"Motorn kan inte lägga ut stationen, så den går inte att rita om. {error}"
            ) from error

    @routes.get("/studio/rita")
    def drawing(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        made, state = drawn(unlocked(slot, session))
        return rita.view(made, state).model_dump(mode="json")

    def keep_drawing(found: str, given: TklDrawing) -> dict[str, Any]:
        """Kept as a draft, with the station's own id and name. A drawing that is the
        station's model as it is is no draft."""
        own = store.station_of(found)
        assert own is not None
        model = given.model.model_copy(update={"station_id": own.station_id, "name": own.name})
        drawing = given.model_copy(update={"model": model})
        made = rita.model_of(drawing)
        if made == store.station_model(found):
            store.forget_drawing(found)
            return rita.view(drawing, TklDrawingState.IN_USE, made).model_dump(mode="json")
        store.save_drawing(found, drawing)
        return rita.view(drawing, TklDrawingState.DRAFT, made).model_dump(mode="json")

    @routes.put("/studio/rita")
    async def save_drawing(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Spara ritningen på datorn: always, problems and all; the checks say what is wrong."""
        same_site(request)
        no_store(response)
        found = await run_in_threadpool(unlocked, slot, session)
        body = await request.body()
        if len(body) > MODEL_LIMIT:
            raise HTTPException(413, "Ritningen är för stor.")
        try:
            given = TklDrawing.model_validate_json(body)
        except ValidationError as error:
            said = [
                f"{'.'.join(str(part) for part in e['loc']) or 'ritningen'}: {e['msg']}"
                for e in error.errors()[:5]
            ]
            refuse_model("Ritningen gick inte att läsa.", said)
        return await run_in_threadpool(keep_drawing, found, given)

    @routes.post("/studio/rita/use")
    def use_drawing(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Använd ritningen: the draft becomes the station's model, which derives the outside
        and gives the interlocking its model. Only without problems (STD-04), and never under
        set routes or train numbers."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        draft = store.drawing(found)
        stored = store.station_model(found)
        if draft is None:
            if stored is None:
                raise HTTPException(404, "Det finns ingen ritning att använda. Rita först.")
            return rita.view(*drawn(found), stored).model_dump(mode="json")
        made = rita.model_of(draft)
        if stored is not None:
            made = rita.ordered_like(made, stored)
        wrong = problems(made)
        if wrong:
            refuse_model("Ritningen kan inte användas än. Rätta problemen först.", wrong)
        try:
            kept = store.save_model(found, made)
        except InterlockingBusy as error:
            raise HTTPException(409, BUSY) from error
        return rita.view(*drawn(found), kept).model_dump(mode="json")

    @routes.delete("/studio/rita")
    def forget_drawing(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Släng utkastet: back to the station's model, or to nothing drawn."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        store.forget_drawing(found)
        made, state = drawn(found)
        return rita.view(made, state).model_dump(mode="json")

    # --- Dela stationen (#87 del b): the parts, kept as a draft until they are used ----------

    panels: dict[str, Panel | None] = {}

    def to_json_parts(parts: list[StationPart]) -> str:
        """The parts as the model file keeps them: equal parts with their switches in another
        order are not the same streets (street_end walks them in order)."""
        return TklDelaEdit(parts=parts).model_dump_json()

    def dela_panel(model: StationModel, key: str) -> Panel | None:
        """The panel the sides are read from, made once per model."""
        if key not in panels:
            if len(panels) >= 4:
                panels.pop(next(iter(panels)))
            panels[key] = track_plan.panel_of(model)
        return panels[key]

    def dela_view(found: str, given: list[StationPart] | None = None) -> dict[str, Any]:
        """The parts as the draft has them, else as the model does, with what Studio works out
        for them and the checks."""
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        draft = given if given is not None else store.parts_draft(found)
        state = TklDelaState.DRAFT if draft is not None else TklDelaState.IN_USE
        plant = plant_of(model)
        shown = dela.view(
            model,
            plant,
            draft if draft is not None else list(model.parts),
            state,
            dela_panel(model, plant.fingerprint),
        )
        return shown.model_dump(mode="json")

    @routes.get("/studio/dela")
    def parts_view(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        no_store(response)
        return dela_view(unlocked(slot, session))

    @routes.put("/studio/dela")
    def save_parts(
        given: TklDelaEdit,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """The parts as the owner has them, kept as a draft, checks and all. Parts that are the
        model's as they are make no draft."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        plant = plant_of(model)
        panel = dela_panel(model, plant.fingerprint)
        cells = {n.id: n.cell for n in panel.nodes} if panel is not None else {}
        parts = dela.ordered(plant, list(given.parts), cells)
        if to_json_parts(parts) == to_json_parts(list(model.parts)):
            store.forget_parts_draft(found)
            return dela_view(found)
        store.save_parts_draft(found, parts)
        return dela_view(found, parts)

    @routes.post("/studio/dela/use")
    def use_parts(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Använd: the draft's parts become the station model's, which the interlocking runs
        and the outside follows. Only without problems, and never under set routes or train
        numbers."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        draft = store.parts_draft(found)
        if draft is None:
            return dela_view(found)
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        wrong = [c.text for c in dela.checks(plant_of(model), draft) if c.problem]
        if wrong:
            refuse_model("Delarna kan inte användas än. Rätta problemen först.", wrong)
        try:
            store.save_parts(found, draft)
        except InterlockingBusy as error:
            raise HTTPException(409, BUSY) from error
        return dela_view(found)

    @routes.delete("/studio/dela")
    def forget_parts(
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Släng utkastet: back to the model's parts."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        store.forget_parts_draft(found)
        return dela_view(found)

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
        own = store.deck_deviations_of_version(found, number) if model is not None else None
        if own is not None:
            # The owner's Stream Deck profiles, as deviations per size (SD49).
            inside["streamdeck"] = own.model_dump(mode="json", exclude_defaults=True)
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
        approved = made.status == station.ApprovalStatus.APPROVED and made.key is not None
        return TklConnection(
            connected=True,
            address=made.address,
            hub_name=made.hub_name,
            status=made.status,
            places=made.places,
            place=hub_places.home_place(made) if approved else None,
            parts=hub_places.part_places(made),
            outside_version=made.outside_version,
            message=made.message,
            preview=made.preview,
        ).model_dump(mode="json")

    def follow(found: str, made: Connection) -> Connection:
        """Ask the hub how the approval stands; the key comes once. After the approval TKL
        keeps asking, since a part approved later comes with the same key (TRAFIK-35): as
        often as before while a place waits, more seldom once each has its answer."""
        settled = made.status != station.ApprovalStatus.WAITING and made.key is not None
        if settled and time.time() - made.asked < hub_places.next_question(made):
            return made
        try:
            reply = hub(made).connection(made.client_id)
        except Unreachable:
            store.asked(found)
            return store.connection(found) or made
        except HubError as error:
            if error.status == 404 and made.key is None:
                store.approval(
                    found,
                    station.ApprovalStatus.REVOKED,
                    [],
                    None,
                    "Hubben känner inte igen TKL längre. Anslut igen.",
                )
            else:
                store.asked(found)
            return store.connection(found) or made
        store.approval(
            found, reply.status, reply.places, reply.key, reply.message, list(reply.wanted)
        )
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
        """Anslut: TKL says which station it is, at which level, and brings its outside
        (KLAR-02, KLAR-12). From Prova, or while the pretend LocoNet is connected, only a
        preview run in Provbanan, never a real meet (STUDIO-12)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        address = checked(given.address)
        own = store.station_of(found)
        assert own is not None
        code = (given.code or "").strip() or None
        in_prova = given.prova or (service is not None and service.pretending)
        if in_prova and code is None:
            raise HTTPException(422, PROVA_CODE)
        number, outside = store.latest_outside(found)
        request_ = station.ConnectRequest(
            kind=station.ClientKind.TKL,
            name=f"TKL {own.name}",
            software=f"TKL {VERSION}",
            station_id=own.station_id,
            outside=outside,
            code=code,
            level=own.level,
            preview_only=in_prova,
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
        if in_prova and not reply.preview:
            raise HTTPException(409, NOT_PREVIEW)
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
                preview=reply.preview,
                wanted=list(reply.wanted),
                asked=time.time(),
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
            made = follow(found, made)
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
        ) -> tuple[TklInterlocking | None, tuple[Outcome, TklInterlocking, list[Order], int]]:
            if model is None:
                raise HTTPException(404, NO_MODEL)
            made = load(plant_of(model), revision, body)
            first_new = made.last_id + 1
            outcome = act(made)
            orders = made.take_orders()
            state = made.view()
            kept = state if made.revision != revision else None
            return kept, (outcome, state, orders, first_new)

        outcome, state, orders, first_new = store.change_interlocking(found, change)
        if orders and services:
            services[0].send(orders)
        if outcome.accepted:
            # Stream Deck: every route set is counted, part by part (TKL70, SD24).
            laid = [r for r in state.routes if r.id >= first_new]
            deck_service.count(
                store, found, [TklDeckRoute(start=r.start, end=r.end, kind=r.kind) for r in laid]
            )
        if outcome.accepted and outcome.reports:
            reports = up(found, list(outcome.reports))
            state = interlocking_of(found).view() if reports else state
        else:
            reports = list(outcome.reports)
        if outcome.accepted and "Nödutlösning" in outcome.message:
            LOGGER.warning("Ställverket: %s", outcome.message)
        if outcome.messages:
            forward(found, list(outcome.messages))
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

    def up(found: str, given: list[TklReport]) -> list[TklReport]:
        """The reports up to the hub, and how they went in the interlocking's events. The
        exit signal's aspect and the line's occupancy are too many to note each one."""
        reports = report(found, given)
        quiet = (TklReportKind.EXIT_SIGNAL, TklReportKind.SECTION_OCCUPANCY)
        noted = [hub_reports.said(r) for r in reports if r.kind not in quiet]
        if noted:
            note(found, noted)
        return reports

    def one_place(found: str) -> tuple[Connection, str] | str:
        """The connection and the station's own place in Hubben. With parts that are their
        own driftplatser TKL is approved for several places; the station's is the one that is
        no part (TRAFIK-35)."""
        made = store.connection(found)
        if made is not None:
            made = follow(found, made)
        if made is None or made.key is None:
            return NOT_CONNECTED
        home = hub_places.home_place(made)
        if home is None:
            return "TKL är inte godkänd för stationens driftplats."
        return made, home

    def part_tracks(found: str, made: Connection) -> dict[str, str]:
        """The station tracks in the parts' areas, by their id in the outside, with the
        approved place of the part (TKL101): a report about such a track is the part's first."""
        model, _, _ = store.interlocking(found)
        if model is None:
            return {}
        plant = plant_of(model)
        found_tracks: dict[str, str] = {}
        for part in plant.parts.values():
            place = hub_places.part_place(made, part.id, part.spec.place)
            if not part.spec.own_place or place is None:
                continue
            area = set(part.pieces)
            for track in model.station_tracks:
                if track.pieces and set(track.pieces) <= area:
                    found_tracks[plant.track_outside.get(track.id, track.id)] = place
        return found_tracks

    def report(found: str, reports: list[TklReport]) -> list[TklReport]:
        """Up to the hub (STV-10), each as the place whose snapshot knows it: the station's
        first, a part's first when it is about a track in the part's area (TKL101)."""
        reached = one_place(found)
        if isinstance(reached, str):
            said = f"{reached} Inget rapporterades till hubben."
            return [r.model_copy(update={"message": said}) for r in reports]
        made, _ = reached
        if service is not None and service.pretending and not made.preview:
            return [r.model_copy(update={"message": NOT_TO_A_MEET}) for r in reports]
        places = hub_places.places_of(made)
        tracks = part_tracks(found, made) if len(places) > 1 else {}
        seen_now: dict[str, station.Snapshot | str] = {}

        def snapshot_of(place: str) -> station.Snapshot | str:
            if place not in seen_now:
                try:
                    seen_now[place] = hub(made).snapshot(place)
                except Unreachable:
                    seen_now[place] = NO_CONTACT
                except HubError as error:
                    seen_now[place] = error.detail
            return seen_now[place]

        done: list[TklReport] = []
        for given in reports:
            first = tracks.get(given.track or "")
            order = [first, *(p for p in places if p != first)] if first else places
            why: str | None = None
            chosen: tuple[str, station.Snapshot] | None = None
            for place in order:
                snapshot = snapshot_of(place)
                if isinstance(snapshot, str):
                    why = why or snapshot
                    continue
                planned = hub_reports.plan(snapshot, given)
                if isinstance(planned, str):
                    why = why or planned
                    continue
                chosen = place, snapshot
                break
            if chosen is None:
                done.append(given.model_copy(update={"message": why}))
                continue
            place, snapshot = chosen
            sent, last = hub_reports.send(hub(made), made.client_id, place, snapshot, [given])
            seen_now[place] = last
            done += sent
        for snapshot in seen_now.values():
            if not isinstance(snapshot, str):
                store.remember(found, snapshot)
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

    # --- Delställverk (#87, TKL97–TKL103): the station's answers, and a part's own screen ------

    def forward(found: str, messages: list[TklPartMessage]) -> None:
        """The five messages between a part and the station (TKL98), as the interlocking hands
        them on. Locally the station's interlocking is the whole exchange, and nothing more is
        sent. When the station is remote-controlled they go through Hubben to whoever
        remote-controls it, who answers as the station would (TKL100, DRIFT-40): that waits for
        #36, and is sent from here."""
        for message in messages:
            LOGGER.debug("Delställverk %s: %s", message.part, message.kind.value)
        del found

    @routes.post("/stallverk/parts/reply")
    def part_reply(
        ask: TklPartReply,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Svar (TKL98): Godkänn lays the route out with the station's interlocking; Neka
        refuses it."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        return operate(found, lambda made: made.part_reply(ask.request, ask.approved))

    @routes.post("/stallverk/parts/ring-answer")
    def part_ring_answer(
        ask: TklPartRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.part_ring_answer(ask.part))

    @routes.post("/stallverk/ready/move")
    def ready_move(
        ask: TklReadyMove,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Klara att skicka: the station moves a train in the list (TKL108)."""
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.ready_move(ask.number, ask.to))

    @routes.post("/stallverk/ready/sent")
    def ready_sent(
        ask: TklReadyRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), lambda made: made.ready_sent(ask.number))

    def part_snapshots(found: str, part: Part) -> tuple[Any, Any, str | None]:
        """The station's own snapshot and, when TKL is approved for the part's driftplats too,
        the part's, found by its link (#87 del c and del b, TRAFIK-35): fresh from the hub,
        else the last one seen. And the part's place in Hubben, approved or not."""
        made = store.connection(found)
        if made is not None:
            made = follow(found, made)
        if made is None or made.key is None:
            return None, None, None

        def read(place: str | None) -> station.Snapshot | None:
            if place is None:
                return None
            try:
                fresh = hub(made).snapshot(place)
            except (Unreachable, HubError):
                last = store.last_seen(found, place)
                return last[0] if last is not None else None
            store.remember(found, fresh)
            return fresh

        link = next((w.place for w in made.wanted if w.part == part.id), part.spec.place)
        own = hub_places.part_place(made, part.id, part.spec.place)
        return read(hub_places.home_place(made)), read(own), link

    def part_trains(found: str, part_id: str) -> TklPartTrains:
        model, _, _ = store.interlocking(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        plant = plant_of(model)
        part = plant.parts.get(part_id)
        if part is None:
            raise HTTPException(404, f"Delställverket {part_id} finns inte i stationsmodellen.")
        here, own, place = part_snapshots(found, part)
        return plan_trains(part, plant, here, own, place)

    @routes.get("/stallverk/parts/{part}/trains")
    def part_trains_route(
        part: PartId, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """The trains the part chooses among for Klart att skicka (TKL108, TKL110)."""
        no_store(response)
        return part_trains(unlocked(slot, session), part).model_dump(mode="json")

    @routes.get("/stallverk/parts/{part}/targets")
    def part_targets(
        part: PartId,
        response: Response,
        start: str = Query(min_length=1, max_length=80),
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """The goals the part may set from a start inside its area."""
        no_store(response)
        made = interlocking_of(unlocked(slot, session))
        try:
            return made.part_targets(part, start).model_dump(mode="json")
        except UnknownStart as error:
            raise HTTPException(404, str(error)) from error

    def part_act(
        request: Request,
        response: Response,
        slot: str | None,
        session: str | None,
        act: Callable[[Interlocking], Outcome],
    ) -> Any:
        same_site(request)
        no_store(response)
        return operate(unlocked(slot, session), act)

    @routes.post("/stallverk/parts/{part}/route")
    def part_route(
        part: PartId,
        ask: TklRouteAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """A shunting route inside the part's area."""
        return part_act(
            request, response, slot, session, lambda m: m.part_route(part, ask.start, ask.end)
        )

    @routes.post("/stallverk/parts/{part}/release")
    def part_release(
        part: PartId,
        ask: TklRouteRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        return part_act(request, response, slot, session, lambda m: m.part_release(part, ask.route))

    @routes.post("/stallverk/parts/{part}/lever")
    def part_lever(
        part: PartId,
        ask: TklLeverAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        return part_act(
            request,
            response,
            slot,
            session,
            lambda m: m.part_lever(part, ask.switch, ask.position),
        )

    @routes.post("/stallverk/parts/{part}/street")
    def part_street(
        part: PartId,
        ask: TklPartStreetAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """A switch street (RANG-02)."""
        return part_act(request, response, slot, session, lambda m: m.part_street(part, ask.street))

    @routes.post("/stallverk/parts/{part}/request")
    def part_request(
        part: PartId,
        ask: TklPartRequestAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Begär väg (TKL98): refused at once when it cannot go (RANG-10)."""
        return part_act(
            request, response, slot, session, lambda m: m.part_request(part, ask.route_out)
        )

    @routes.post("/stallverk/parts/{part}/return")
    def part_return(
        part: PartId,
        ask: TklPartRequestRef,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Lämna tillbaka (TKL98, RANG-09)."""
        return part_act(
            request, response, slot, session, lambda m: m.part_return(part, ask.request)
        )

    @routes.post("/stallverk/parts/{part}/done")
    def part_done(
        part: PartId,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Klart (RANG-04): every request returned, the border switches back."""
        return part_act(request, response, slot, session, lambda m: m.part_done(part))

    @routes.post("/stallverk/parts/{part}/gates")
    def part_gates(
        part: PartId,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Grindar: the border switches back, nothing returned (TKL55)."""
        return part_act(request, response, slot, session, lambda m: m.part_gates(part))

    @routes.post("/stallverk/parts/{part}/ring")
    def part_ring(
        part: PartId,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Ring (TKL98)."""
        return part_act(request, response, slot, session, lambda m: m.part_ring(part))

    @routes.post("/stallverk/parts/{part}/fika")
    def part_fika(
        part: PartId,
        ask: TklPartFika,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Fika: the part's screen is locked until it is back, and the station sees it."""
        return part_act(request, response, slot, session, lambda m: m.part_fika(part, ask.on))

    @routes.post("/stallverk/parts/{part}/ready")
    def part_ready(
        part: PartId,
        ask: TklReadyAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Klart att skicka (TKL108): a train from the plan, with its track and planned
        departure, or a typed number."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        chosen = None
        if store.connection(found) is not None:
            trains = part_trains(found, part).trains
            chosen = next(
                (t for t in trains if (ask.call and t.call == ask.call) or t.number == ask.number),
                None,
            )
        return operate(
            found,
            lambda m: m.part_ready(
                part,
                ask.number,
                call=chosen.call if chosen else ask.call,
                track=chosen.track if chosen else None,
                departure=chosen.departure if chosen else None,
            ),
        )

    # --- Stream Deck (#86): the deck's profile, its logic, the deck on the screen and real decks

    room = deck_service.Room()

    class DeckHands:
        """What a deck does goes through the interlocking's operations, as the panel's, and
        TKL's clearance as it is (SD1, SD14). Not tied to a request: the USB driver uses the
        same hands for the decks TKL owns (SD50)."""

        def __init__(self, found: str) -> None:
            self.found = found

        def answer(self, act: Callable[[Interlocking], Outcome]) -> deck_logic.Said:
            try:
                told = operate(self.found, act)
            except HTTPException as error:
                return deck_logic.Said(False, str(error.detail))
            return deck_logic.Said(bool(told["accepted"]), str(told["message"]))

        def set_route(self, start: str, end: str, kind: object | None) -> deck_logic.Said:
            wanted = RouteKind(str(getattr(kind, "value", kind))) if kind is not None else None
            return self.answer(lambda made: made.set_route(start, end, wanted))

        def release(self, route: int) -> deck_logic.Said:
            return self.answer(lambda made: made.release(route))

        def step(self, route: int) -> deck_logic.Said:
            return self.answer(lambda made: made.step(route))

        def arrive(self, route: int) -> deck_logic.Said:
            return self.answer(lambda made: made.arrive(route))

        def function(self, name: str, on: bool) -> deck_logic.Said:
            action = TklFunctionAction.ON if on else TklFunctionAction.OFF
            return self.answer(lambda made: made.function(name, action, None, confirm=False))

        def command(
            self,
            action: station.Action,
            payload: dict[str, object],
            revision: station.Revision | None,
        ) -> deck_logic.Said:
            reached = one_place(self.found)
            if isinstance(reached, str):
                return deck_logic.Said(False, reached)
            made, place = reached
            try:
                snapshot = hub(made).snapshot(place)
                sent = station.Command(
                    client_id=made.client_id,
                    message_id=f"tkl-deck-{secrets.token_hex(8)}",
                    place=place,
                    context=snapshot.context,
                    action=action,
                    expected_revision=revision,
                    payload=payload,
                )
                reply = hub(made).command(sent)
            except Unreachable:
                return deck_logic.Said(False, NO_CONTACT)
            except HubError as error:
                return deck_logic.Said(False, error.detail)
            store.remember(self.found, reply.snapshot)
            accepted = reply.status != station.ReplyStatus.REJECTED
            return deck_logic.Said(accepted, reply.message or ("Ja." if accepted else "Nej."))

        def lock(self) -> deck_logic.Said:
            """Lås on the deck (Fika, SD30): TKL is locked for the whole station."""
            store.lock_station(self.found)
            LOGGER.info("TKL är låst från ett Stream Deck.")
            return deck_logic.Said(True, LOCKED)

        def reset(self) -> deck_logic.Said:
            """Noll with a hold (SD29): the hold is the confirmation, as the panel's dialog."""
            return self.answer(lambda made: made.reset(True))

        def emergency(self, route: int) -> deck_logic.Said:
            """Nödutlösning with a hold (SD29): the hold is the confirmation."""
            return self.answer(lambda made: made.emergency_release(route, True))

        # The shunter's deck (#87 del d): the interlocking's own part operations, as the part's
        # screen calls them (SD1).

        def part_street(self, part: str, street: str) -> deck_logic.Said:
            return self.answer(lambda made: made.part_street(part, street))

        def part_request(self, part: str, route_out: str) -> deck_logic.Said:
            return self.answer(lambda made: made.part_request(part, route_out))

        def part_return(self, part: str, request: int) -> deck_logic.Said:
            return self.answer(lambda made: made.part_return(part, request))

        def part_done(self, part: str) -> deck_logic.Said:
            return self.answer(lambda made: made.part_done(part))

        def part_gates(self, part: str) -> deck_logic.Said:
            return self.answer(lambda made: made.part_gates(part))

        def part_ring(self, part: str) -> deck_logic.Said:
            return self.answer(lambda made: made.part_ring(part))

        def part_fika(self, part: str, on: bool) -> deck_logic.Said:
            return self.answer(lambda made: made.part_fika(part, on))

        def part_ready(self, part: str, train: TklPartTrain) -> deck_logic.Said:
            """Klart att skicka (TKL108): the train from the plan with its track and time."""
            return self.answer(
                lambda made: made.part_ready(
                    part,
                    train.number,
                    call=train.call,
                    track=train.track,
                    departure=train.departure,
                )
            )

    def deck_snapshot(found: str) -> tuple[station.Snapshot | None, datetime | None, bool]:
        """The place's snapshot for the deck, at most DECK_FRESH seconds old, when it was
        heard, and whether TKL is in drift: connected to a real meet (SD28)."""
        reached = one_place(found)
        if isinstance(reached, str):
            return None, None, False
        made, place = reached
        drift = not made.preview
        last = store.last_seen(found, place)
        if last is not None and (datetime.now(UTC) - last[1]).total_seconds() < DECK_FRESH:
            return last[0], last[1], drift
        try:
            snapshot = hub(made).snapshot(place)
        except (Unreachable, HubError):
            return (last[0], last[1], drift) if last else (None, None, drift)
        return snapshot, store.remember(found, snapshot), drift

    def deck_clock(snapshot: station.Snapshot | None, heard: datetime | None) -> str:
        """The game clock from Hubben, run on since it was heard; else the computer's (SD15)."""
        if snapshot is None or heard is None:
            return datetime.now().astimezone().strftime("%H:%M")
        c = snapshot.clock
        passed = (datetime.now(UTC) - heard).total_seconds() if c.running else 0.0
        minutes = int((c.seconds + passed * c.speed) // 60)
        return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"

    def deck_seen(found: str, made: Connection, place: str) -> station.Snapshot | None:
        """A place's snapshot for the deck, at most DECK_FRESH seconds old, else the last."""
        last = store.last_seen(found, place)
        if last is not None and (datetime.now(UTC) - last[1]).total_seconds() < DECK_FRESH:
            return last[0]
        try:
            fresh = hub(made).snapshot(place)
        except (Unreachable, HubError):
            return last[0] if last is not None else None
        store.remember(found, fresh)
        return fresh

    def deck_part_trains(found: str, plant: Plant, part_id: str) -> list[TklPartTrain] | None:
        """The trains the shunter's train key steps through (SD60): the same list as
        /stallverk/parts/{id}/trains, from the snapshots the deck already reads."""
        part = plant.parts.get(part_id)
        if part is None:
            return None
        made = store.connection(found)
        if made is not None and made.key is None:
            made = follow(found, made)
        here: station.Snapshot | None = None
        own: station.Snapshot | None = None
        if made is None or made.key is None:
            return None  # no plan from Hubben: the train key says so
        for place in made.places:
            seen = deck_seen(found, made, place)
            if place == part.spec.place:
                own = seen
            elif here is None:
                here = seen
        return plan_trains(part, plant, here, own).trains

    def deck_world(
        found: str, locked: bool, part: str | None = None
    ) -> tuple[deck_logic.World, Any]:
        model, revision, body = store.interlocking(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        plant = plant_of(model)
        panel = room.panel(plant, lambda: track_plan.panel_of(model))
        geo = geography_of(plant, panel)
        try:
            made: Interlocking | None = load(plant, revision, body)
        except (ValueError, KeyError):
            made = None
        snapshot, heard, drift = deck_snapshot(found) if not locked else (None, None, False)
        here = store.station_of(found)
        world = deck_logic.World(
            plant=plant,
            geo=geo,
            interlocking=made,
            snapshot=snapshot,
            drift=drift,
            locked=locked,
            time=deck_clock(snapshot, heard),
            station=here.name if here is not None else "",
            favourites=deck_service.favourites(store, found, plant).shown,
            daily_kept=deck_service.todays(store, found, snapshot, plant, geo),
            part_trains=deck_part_trains(found, plant, part) if part and not locked else None,
        )
        return world, panel

    def deck_found(slot: str | None, session: str | None) -> tuple[str, bool]:
        """The station, and whether TKL is locked, for the whole station or in this browser:
        then the deck shows only the clock (SD30)."""
        found = slot_of(slot)
        if found is None or store.station_of(found) is None:
            raise HTTPException(401, "Lås upp TKL med PIN-koden.")
        return found, store.station_locked(found) or not store.unlocked(found, session)

    def deck_signature(found: str, serial: str, workplace: str) -> tuple[object, ...]:
        selection = room.selection(found, workplace)
        reached = store.connection(found)
        # Every place's latest snapshot: the shunter's train key reads the part's too (#87).
        heard = tuple(
            (last[1] if (last := store.last_seen(found, place)) else None)
            for place in (reached.places if reached is not None else [])
        )
        drift = store.deck_drift(found)
        return (
            store.interlocking_revision(found),
            heard,
            selection.revision,
            id(selection),
            str(drift.get(deck_service.PINNED)),
            store.station_locked(found),
            store.deck_deviations_body(found),
            room.blinking(found, serial),
            settings.model_dump_json() if (settings := store.deck(found, serial)) else None,
        )

    def deck_picture(world: deck_logic.World, panel: Any) -> deck_render.Picture | None:
        """The panel with the interlocking's state, for Spårplan's keys (SD70, SD71)."""
        if panel is None or world.interlocking is None:
            return None
        state = world.state
        sections = world.snapshot.sections if world.snapshot is not None else []
        busy = {
            e.exit for e in state.exits if any(s.exit == e.outside and s.occupied for s in sections)
        }
        return deck_render.picture(panel, state, busy)

    Act = Callable[[deck_logic.Deck, deck_logic.Selection, deck_logic.World], None]

    def part_given(found: str, part: str) -> str:
        """A deck's role must be a part of the station's model (#87 del d)."""
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        if all(p.id != part for p in model.parts):
            raise HTTPException(422, f"Delen {part} finns inte i stationsmodellen.")
        return part

    def deck_view(found: str, serial: str, locked: bool, act: Act | None = None) -> Shown:
        settings = store.deck(found, serial)
        if settings is None:
            raise HTTPException(
                404, "Decket finns inte här. Öppna det på skärmen eller koppla in det."
            )
        room.heard(found, serial)
        role = settings.role
        world, panel = deck_world(found, locked, role)
        # The owner's profile of the deck's size (SD40), the default when the owner changed none;
        # a part's deck has the shunter's, Bangård, and never the tågklarerare's modes (#87).
        kept = store.deck_deviations(found)
        sizes = kept.parts.get(role, {}) if role is not None else kept.sizes
        mine = deck_studio.deviations_for(sizes, settings.model)
        applied = deck_deviations.owned(
            world.plant, panel, settings.grid, settings.model, mine, role
        )
        profile = applied.profile
        with room.lock:
            deck = room.deck(found, settings, profile, world)
            selection = room.selection(found, deck.settings.workplace)
            if act is not None and not locked:
                act(deck, selection, world)
                if deck.settings != settings:
                    store.save_deck(found, deck.settings)
                locked = locked or store.station_locked(found)
                world, _ = deck_world(found, locked, role)
            room.revision(found, serial, deck_signature(found, serial, deck.settings.workplace))
            view = deck_logic.view(deck, selection, world)
            picture = deck_picture(world, panel) if any(f.tile for f in view.keys) else None
            shown = Shown(deck_render.stamp(view, picture), picture)
            room.keep(found, serial, shown)
            return shown

    def deck_opened(found: str, serial: str, given: TklDeckOpen) -> Shown:
        """A deck on this computer, by its serial number (SD35): the deck on the screen, one in
        the browser with WebHID, or one TKL owns over USB (SD50). Its settings are kept here
        (SD49)."""
        if (
            given.connection != DeckConnection.USB
            and room.connection(found, serial) == DeckConnection.USB
        ):
            raise HTTPException(409, OWNED)
        if given.role is not None:
            part_given(found, given.role)
        known = store.deck(found, serial)
        settings = deck_service.settings_for(known, serial, given)
        if known is None or known.grid != settings.grid or known.role != settings.role:
            room.forget(found, serial)
        store.save_deck(found, settings)
        room.link(found, serial, given.connection)
        return deck_view(found, serial, store.station_locked(found))

    def deck_shown(found: str, serial: str, locked: bool) -> Shown:
        """The deck's last view while nothing has changed, else a new one: its pictures are
        drawn from it, one request per key."""
        settings = store.deck(found, serial)
        if settings is None:
            raise HTTPException(404, "Decket finns inte här.")
        revision = room.revision(found, serial, deck_signature(found, serial, settings.workplace))
        kept = room.kept_view(found, serial, revision)
        if kept is not None and kept.view.locked == locked:
            return kept
        return deck_view(found, serial, locked)

    def deck_press(found: str, serial: str, locked: bool, key: int, hold: bool) -> Shown:
        hands = DeckHands(found)

        def act(
            deck: deck_logic.Deck, chosen: deck_logic.Selection, world: deck_logic.World
        ) -> None:
            deck_logic.press(deck, chosen, world, hands, key, hold)

        return deck_view(found, serial, locked, act)

    def deck_turn(found: str, serial: str, locked: bool, ask: TklDeckDialAsk) -> Shown:
        hands = DeckHands(found)

        def act(
            deck: deck_logic.Deck, chosen: deck_logic.Selection, world: deck_logic.World
        ) -> None:
            deck_logic.dial(deck, chosen, world, hands, ask.dial, ask.turn, ask.press)

        return deck_view(found, serial, locked, act)

    def deck_touched(found: str, serial: str, locked: bool, point: Literal[-1, 1]) -> Shown:
        def act(
            deck: deck_logic.Deck, chosen: deck_logic.Selection, world: deck_logic.World
        ) -> None:
            deck_logic.touch(deck, world, point)

        return deck_view(found, serial, locked, act)

    class UsbDesk:
        """The decks a local TKL owns over USB (SD50): the same deck service as the API's, for
        the station on this computer, without an HTTP request and without a browser's PIN
        session. The station's own lock still holds: locked, a deck shows only the clock."""

        def found(self) -> tuple[str, bool]:
            if store.station_of(LOCAL) is None:
                raise NotSetUp()
            return LOCAL, store.station_locked(LOCAL)

        def open(self, serial: str, model: DeckModelId) -> Shown:
            found, _ = self.found()
            return deck_opened(
                found, serial, TklDeckOpen(model=model, connection=DeckConnection.USB)
            )

        def view(self, serial: str) -> Shown:
            found, locked = self.found()
            return deck_view(found, serial, locked)

        def press(self, serial: str, key: int, hold: bool) -> Shown:
            found, locked = self.found()
            return deck_press(found, serial, locked, key, hold)

        def dial(self, serial: str, dial: int, turn: int, press: bool) -> Shown:
            found, locked = self.found()
            ask = TklDeckDialAsk(dial=dial, turn=turn, press=press)
            return deck_turn(found, serial, locked, ask)

        def touch(self, serial: str, point: Literal[-1, 1]) -> Shown:
            found, locked = self.found()
            return deck_touched(found, serial, locked, point)

        def revision(self, serial: str) -> int:
            found, _ = self.found()
            settings = store.deck(found, serial)
            if settings is None:
                raise HTTPException(404, "Decket finns inte här.")
            return room.revision(found, serial, deck_signature(found, serial, settings.workplace))

        def gone(self, serial: str) -> None:
            room.unlink(LOCAL, serial)

    usb = None if cloud else deck_usb.Driver(UsbDesk(), usb_finder or deck_usb.find)
    app.state.deck_usb = usb
    if usb is not None:
        starting.append(usb.start)
        stopping.append(usb.stop)

    def picture_answer(request: Request, tag: str, draw: Callable[[], bytes]) -> Response:
        """A picture with its ETag: the same picture again is a 304, so that a deck in the
        browser may ask after every change."""
        headers = {"ETag": tag, "Cache-Control": "no-cache"}
        if tag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers=headers)
        return Response(draw(), media_type="image/png", headers=headers)

    @routes.get("/deck/models")
    def deck_models(response: Response) -> Any:
        """Elgato's models and their grids (SD52), each tried with a real deck or not (SD58)."""
        no_store(response)
        return [m.model_dump(mode="json") for m in DECK_MODELS]

    @routes.get("/deck/profile")
    def deck_profile_of(
        response: Response,
        model: DeckModelId,
        part: Annotated[str | None, Query(max_length=80)] = None,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """The default profile for a model, computed from the station model (SD39, SD53); with
        a part, the shunter's deck, Bangård (#87 del d)."""
        no_store(response)
        found = unlocked(slot, session)
        if part is not None:
            part_given(found, part)
        world, panel = deck_world(found, False)
        known = next(m for m in DECK_MODELS if m.id == model)
        return deck_profile(world.plant, panel, known.grid, model, part).model_dump(mode="json")

    @routes.get("/deck/ingen-kontakt.png")
    def deck_no_contact_picture(
        request: Request,
        size: Annotated[int, Query(ge=deck_render.SMALLEST, le=deck_render.LARGEST)] = 72,
        height: Annotated[
            int | None, Query(ge=deck_render.SMALLEST, le=deck_render.LARGEST)
        ] = None,
    ) -> Response:
        """Ingen kontakt as a key (SD21): fetched once by a deck in the browser, which shows it
        on every key when TKL does not answer, never an old state."""
        face = deck_look.no_contact()
        tall = height or size
        tag = deck_render.key_etag(face, size, tall, 0)
        return picture_answer(
            request, tag, lambda: deck_render.png(deck_render.key(face, size, tall))
        )

    def deck_status(found: str, settings: TklDeckSettings) -> TklDeckStatus:
        known = DECK_BY_ID.get(settings.model) if settings.model is not None else None
        return TklDeckStatus(
            serial=settings.serial,
            model=settings.model,
            name=deck_name(settings.model, settings.grid),
            grid=settings.grid,
            workplace=settings.workplace,
            connection=room.connection(found, settings.serial),
            tried=known.tried if known is not None else False,
            settings=settings,
            blinking=room.blinking(found, settings.serial),
        )

    @routes.get("/decks")
    def decks(response: Response, slot: SlotCookie = None, session: SessionCookie = None) -> Any:
        """The decks TKL knows, how each is connected now, and whether TKL owns decks over USB
        here (SD35, SD50, SD58): what Studio, Deck shows (#86 del c)."""
        no_store(response)
        found = unlocked(slot, session)
        listed = [deck_status(found, settings) for settings in store.decks(found)]
        problem = usb.problem if usb is not None else None
        model = store.station_model(found)
        roles = deck_studio.roles_of(plant_of(model)) if model is not None else []
        return TklDecks(
            usb=usb is not None, usb_problem=problem, decks=listed, roles=roles
        ).model_dump(mode="json")

    @routes.post("/deck/{serial}")
    def deck_open(
        serial: Annotated[str, PathPart(pattern=SERIAL_PATTERN)],
        given: TklDeckOpen,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """A deck on this computer, by its serial number (SD35): the deck on the screen, or one
        in the browser with WebHID; one TKL owns over USB is not opened twice (SD50)."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        return deck_opened(found, serial, given).view.model_dump(mode="json")

    @routes.post("/deck/{serial}/close", status_code=204)
    def deck_close(
        serial: str,
        request: Request,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Response:
        """The browser let go of its deck: unplugged, or the page closed (SD50)."""
        same_site(request)
        found, _ = deck_found(slot, session)
        if room.connection(found, serial) != DeckConnection.USB:
            room.unlink(found, serial)
        return Response(status_code=204)

    @routes.get("/deck/{serial}")
    def deck_state(
        serial: str, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Every key's face for the deck now: the locked TKL shows only the clock (SD30)."""
        no_store(response)
        found, locked = deck_found(slot, session)
        return deck_view(found, serial, locked).view.model_dump(mode="json")

    @routes.get("/deck/{serial}/key/{index}.png")
    def deck_key_picture(
        serial: str,
        index: Annotated[int, PathPart(ge=0, le=255)],
        request: Request,
        size: Annotated[int, Query(ge=deck_render.SMALLEST, le=deck_render.LARGEST)] = 72,
        height: Annotated[
            int | None, Query(ge=deck_render.SMALLEST, le=deck_render.LARGEST)
        ] = None,
        phase: Annotated[int, Query(ge=0, le=1)] = 0,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Response:
        """One key as a real deck shows it, at the deck's own size (SD3): the same picture for
        WebHID as over USB. `phase` 1 is a blinking key's other colour."""
        found, locked = deck_found(slot, session)
        shown = deck_shown(found, serial, locked)
        faces = shown.view.keys
        face = faces[index] if index < len(faces) else deck_look.EMPTY
        tall = height or size
        tag = deck_render.key_etag(face, size, tall, phase)

        def draw() -> bytes:
            return deck_render.png(deck_render.key(face, size, tall, shown.picture, phase))

        return picture_answer(request, tag, draw)

    @routes.get("/deck/{serial}/strip.png")
    def deck_strip_picture(
        serial: str,
        request: Request,
        width: Annotated[int, Query(ge=100, le=2000)] = 800,
        height: Annotated[int, Query(ge=20, le=400)] = 100,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Response:
        """The touch strip of + and + XL (SD33, SD83): a segment per dial."""
        found, locked = deck_found(slot, session)
        view = deck_shown(found, serial, locked).view
        dials = view.settings.grid.dials
        parts = view.strip
        tag = deck_render.etag(
            "strip", [p.model_dump() for p in parts], view.said, view.contact, dials, width, height
        )

        def draw() -> bytes:
            image = deck_render.strip(
                parts, dials, width, height, said=view.said, contact=view.contact
            )
            return deck_render.png(image)

        return picture_answer(request, tag, draw)

    @routes.get("/deck/{serial}/info.png")
    def deck_info_picture(
        serial: str,
        request: Request,
        width: Annotated[int, Query(ge=100, le=2000)] = 248,
        height: Annotated[int, Query(ge=20, le=400)] = 58,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Response:
        """Neo's info line (SD34, SD82): the clock and the page, and the latest no."""
        found, locked = deck_found(slot, session)
        view = deck_shown(found, serial, locked).view
        tag = deck_render.etag("info", view.info, view.contact, width, height)

        def draw() -> bytes:
            return deck_render.png(deck_render.info(view.info, width, height, contact=view.contact))

        return picture_answer(request, tag, draw)

    @routes.post("/deck/{serial}/press")
    def deck_press_route(
        serial: str,
        ask: TklDeckPress,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """A press or a hold (SD29)."""
        same_site(request)
        no_store(response)
        found, locked = deck_found(slot, session)
        return deck_press(found, serial, locked, ask.key, ask.hold).view.model_dump(mode="json")

    @routes.post("/deck/{serial}/dial")
    def deck_dial(
        serial: str,
        ask: TklDeckDialAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """A dial turned or pressed (SD83)."""
        same_site(request)
        no_store(response)
        found, locked = deck_found(slot, session)
        return deck_turn(found, serial, locked, ask).view.model_dump(mode="json")

    @routes.post("/deck/{serial}/touch")
    def deck_touch(
        serial: str,
        ask: TklDeckTouch,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Neo's touch points (SD82)."""
        same_site(request)
        no_store(response)
        found, locked = deck_found(slot, session)
        return deck_touched(found, serial, locked, ask.point).view.model_dump(mode="json")

    @routes.get("/deck/{serial}/wait")
    async def deck_wait(
        serial: str,
        response: Response,
        after: int = Query(ge=0),
        seconds: float = Query(default=WAIT_SECONDS, ge=0, le=30),
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Wait for the deck's next change after `after`, as the interlocking's wait."""
        no_store(response)
        found, _ = await run_in_threadpool(deck_found, slot, session)
        settings = await run_in_threadpool(store.deck, found, serial)
        if settings is None:
            raise HTTPException(404, "Decket finns inte här.")
        room.heard(found, serial)
        waited = 0.0
        while True:
            signature = await run_in_threadpool(deck_signature, found, serial, settings.workplace)
            revision = room.revision(found, serial, signature)
            if revision != after or waited >= seconds:
                return TklWait(revision=revision, changed=revision != after).model_dump(mode="json")
            await asyncio.sleep(WAIT_STEP)
            waited += WAIT_STEP

    @routes.get("/deck-favoriter")
    def deck_favourites(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Favoriter: the pinned routes and how often each route is set (SD24)."""
        no_store(response)
        found = unlocked(slot, session)
        world, _ = deck_world(found, False)
        return deck_service.favourites(store, found, world.plant).model_dump(mode="json")

    @routes.post("/deck-favoriter")
    def deck_pin(
        ask: TklDeckPin,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Fäst på Stream Deck (SD48): a route onto Favoriter, or off it."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        world, _ = deck_world(found, False)
        route = TklDeckRoute(start=ask.start, end=ask.end, kind=ask.kind)
        if not deck_service.exists(world.plant)(route):
            raise HTTPException(
                404, f"Vägen {ask.start} → {ask.end} finns inte i stationsmodellen."
            )
        deck_service.pin(store, found, route, ask.pinned)
        return deck_service.favourites(store, found, world.plant).model_dump(mode="json")

    # --- Studio, Deck (#86 del c, SD46): each deck's own settings, on this computer -----------

    def known_deck(found: str, serial: str) -> TklDeckSettings:
        settings = store.deck(found, serial)
        if settings is None:
            raise HTTPException(404, "Decket finns inte här. Koppla in det eller öppna det.")
        return settings

    @routes.put("/deck/{serial}")
    def deck_settings(
        serial: Annotated[str, PathPart(pattern=SERIAL_PATTERN)],
        change: TklDeckChange,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Ljusstyrka, hålltid, släckning, lås, the page it opens on and the workplace, for one
        deck (SD29, SD35, SD36, SD46). Brightness and sleep reach the deck over USB and WebHID
        with its next view; the deck opens on its start page again."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        settings = known_deck(found, serial)
        given = {k: v for k, v in change.model_dump(exclude_unset=True).items() if v is not None}
        for cleared in ("name", "opens_on", "role"):
            if cleared in given and not str(given[cleared]).strip():
                given[cleared] = None
        if given.get("role") is not None:
            # Rollen (#87 del d): a part of the station; empty is the tågklarerare.
            given["role"] = part_given(found, str(given["role"]).strip())
        made = settings.model_copy(update=given)
        made = TklDeckSettings.model_validate(made.model_dump())
        store.save_deck(found, made)
        if (
            made.opens_in != settings.opens_in
            or made.opens_on != settings.opens_on
            or made.role != settings.role
        ):
            room.forget(found, serial)
        return deck_status(found, made).model_dump(mode="json")

    @routes.post("/deck/{serial}/blinka")
    def deck_blink(
        serial: Annotated[str, PathPart(pattern=SERIAL_PATTERN)],
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Blinka (SD46): every key of the deck lights up for a moment, on the deck itself."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        settings = known_deck(found, serial)
        room.blink(found, serial)
        return deck_status(found, settings).model_dump(mode="json")

    @routes.delete("/deck/{serial}", status_code=204)
    def deck_forget(
        serial: Annotated[str, PathPart(pattern=SERIAL_PATTERN)],
        request: Request,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Response:
        """Glöm deck: its settings on this computer go. A deck that is connected again gets the
        defaults."""
        same_site(request)
        found = unlocked(slot, session)
        if not store.forget_deck(found, serial):
            raise HTTPException(404, "Decket finns inte här.")
        room.forget(found, serial)
        if room.connection(found, serial) != DeckConnection.USB:
            room.unlink(found, serial)
        return Response(status_code=204)

    # --- Studio, Inställningar, Stream Deck (#86 del c): Sidor and Prova ----------------------

    keys_runner = deck_tryall.Runner()
    stopping.append(keys_runner.close)

    def deck_station(found: str) -> tuple[Any, Any]:
        model = store.station_model(found)
        if model is None:
            raise HTTPException(404, NO_MODEL)
        plant = plant_of(model)
        panel = room.panel(plant, lambda: track_plan.panel_of(model))
        return plant, panel

    def kept_sizes(found: str, part: str | None) -> dict[DeckModelId, list[Any]]:
        """The owner's deviations per size: the tågklarerare's, or a part's deck's (#87)."""
        kept = store.deck_deviations(found)
        return dict(kept.parts.get(part, {})) if part is not None else dict(kept.sizes)

    def studio_deck(
        found: str,
        size: DeckModelId,
        deviations: list[Any] | None = None,
        message: str | None = None,
        part: str | None = None,
    ) -> Any:
        """Sidor for one size: the owner's deviations as kept, or as given and not kept yet,
        made the fewest that give the same profile, with Att kolla after them. With a part, the
        shunter's deck, Bangård (#87 del d)."""
        plant, panel = deck_station(found)
        kept = kept_sizes(found, part)
        given = kept.get(size, []) if deviations is None else deviations
        default = deck_studio.default_of(plant, panel, size, part)
        known = deck_deviations.known_of(plant, geography_of(plant, panel), part)
        made, applied = deck_deviations.tidy(default, given, known)
        decks_here = [d.model for d in store.decks(found) if d.role == part]
        shown = {**kept, size: made}
        return deck_studio.view(
            size,
            plant,
            panel,
            made,
            applied,
            saved=made == kept.get(size, []),
            all_sizes=deck_studio.sizes(plant, panel, shown, decks_here, part),
            message=message,
            roles=deck_studio.roles_of(plant),
        ).model_dump(mode="json")

    def refused_changes(edit: TklDeckEdit) -> None:
        grid = DECK_BY_ID[edit.size].grid
        wrong = deck_deviations.refusals(edit.deviations, edit.size, grid)
        if wrong:
            raise HTTPException(
                422,
                {"message": "Ändringen går inte att göra på ett Stream Deck.", "problems": wrong},
            )

    def size_given(size: DeckModelId, part: str | None = None) -> DeckModelId:
        if size not in deck_studio.SIZES:
            raise HTTPException(
                422, "Den modellen får profilen för sin storlek (SD54). Välj storleken."
            )
        if part is not None and size not in deck_studio.YARD_SIZES:
            raise HTTPException(422, "Pedalen har inget rangerardeck (TKL122).")
        return size

    def studio_part(found: str, part: str | None) -> str | None:
        return part_given(found, part) if part is not None else None

    @routes.get("/studio/stream-deck")
    def stream_deck(
        response: Response,
        size: DeckModelId = DeckModelId.FIFTEEN,
        part: Annotated[str | None, Query(max_length=80)] = None,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Sidor (SD41): the owner's profile for one size, Att kolla, the checks and Knappar.
        The default is there without the owner doing anything (SD39). With a part, its deck,
        Bangård (#87 del d)."""
        no_store(response)
        found = unlocked(slot, session)
        part = studio_part(found, part)
        return studio_deck(found, size_given(size, part), part=part)

    @routes.post("/studio/stream-deck/utkast")
    def stream_deck_draft(
        edit: TklDeckEdit,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """The owner's changes shown before they are kept: refused with the reason when one may
        not be made (SD43)."""
        found = doing(request, response, slot, session)
        part = studio_part(found, edit.part)
        size_given(edit.size, part)
        refused_changes(edit)
        return studio_deck(found, edit.size, list(edit.deviations), part=part)

    @routes.put("/studio/stream-deck")
    def save_stream_deck(
        edit: TklDeckEdit,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """The owner's changes for one size, kept with the station's model and versioned with
        it (SD40, SD49). Every deck of the size gets them on its next view."""
        found = doing(request, response, slot, session)
        part = studio_part(found, edit.part)
        size_given(edit.size, part)
        refused_changes(edit)
        plant, panel = deck_station(found)
        default = deck_studio.default_of(plant, panel, edit.size, part)
        known = deck_deviations.known_of(plant, geography_of(plant, panel), part)
        made, _ = deck_deviations.tidy(default, list(edit.deviations), known)
        kept = store.deck_deviations(found)
        if part is None:
            saved = kept.model_copy(update={"sizes": {**kept.sizes, edit.size: made}})
        else:
            # The shunter's deck: its own deviations per part and size (#87 del d).
            mine = {**kept.parts.get(part, {}), edit.size: made}
            saved = kept.model_copy(update={"parts": {**kept.parts, part: mine}})
        try:
            store.save_deck_deviations(found, TklDeckDeviations.model_validate(saved.model_dump()))
        except NoModel as error:
            raise HTTPException(404, NO_MODEL) from error
        return studio_deck(found, edit.size, message="Sparat. Decken visar det direkt.", part=part)

    @routes.post("/studio/stream-deck/foresla")
    def stream_deck_suggest(
        ask: TklDeckSuggest,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Föreslå (SD45): a page made again geographically, by Dagens vägar or by Mest
        använda. Shown, not kept, until the owner saves."""
        found = doing(request, response, slot, session)
        part = studio_part(found, ask.part)
        size_given(ask.size, part)
        refused_changes(ask)
        plant, panel = deck_station(found)
        geo = geography_of(plant, panel)
        default = deck_studio.default_of(plant, panel, ask.size, part)
        known = deck_deviations.known_of(plant, geo, part)
        daily = deck_service.kept_daily(store, found)
        counts = deck_service.counts(store, found)
        try:
            made = deck_suggest.suggest(
                default, list(ask.deviations), ask.page, ask.rule, known, plant, geo, daily, counts
            )
        except deck_suggest.NoSuggestion as error:
            raise HTTPException(409, str(error)) from error
        return studio_deck(found, ask.size, made, part=part)

    @routes.get("/studio/stream-deck/prova")
    def stream_deck_prova(
        response: Response,
        size: DeckModelId | None = None,
        part: Annotated[str | None, Query(max_length=80)] = None,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Prova alla knappar (SD47): the progress while it runs, then every key's result; for
        the tågklarerare's deck, or a part's (#87 del d)."""
        no_store(response)
        found = unlocked(slot, session)
        return deck_tryall.view(keys_runner.job(found), size, part).model_dump(mode="json")

    @routes.post("/studio/stream-deck/prova/start")
    def stream_deck_prova_start(
        ask: TklDeckProvaAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Every key of every page of the size, the owner's profile as it is kept, pressed on an
        empty interlocking in the background; never the live one (SD47)."""
        found = doing(request, response, slot, session)
        part = studio_part(found, ask.part)
        size = size_given(ask.size, part)
        plant, panel = deck_station(found)
        mine = kept_sizes(found, part).get(size, [])
        grid = DECK_BY_ID[size].grid
        profile = deck_deviations.owned(plant, panel, grid, size, mine, part).profile
        favourites = deck_service.favourites(store, found, plant).shown
        try:
            job = keys_runner.start(
                found,
                size,
                profile,
                plant,
                geography_of(plant, panel),
                favourites,
                deck_service.kept_daily(store, found),
            )
        except deck_tryall.Busy as error:
            raise HTTPException(429, PROVA_BUSY) from error
        return deck_tryall.view(job, size, part).model_dump(mode="json")

    @routes.post("/studio/stream-deck/prova/stop")
    def stream_deck_prova_stop(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        found = doing(request, response, slot, session)
        keys_runner.stop(found)
        job = keys_runner.job(found)
        if job is not None and job.thread is not None:
            job.thread.join(timeout=10)
        return deck_tryall.view(job, any_part=True).model_dump(mode="json")

    # --- Studio's Koppla in at level 3 (#85): LocoNet, only in a local TKL -----------------

    def deliver(reports: list[TklReport]) -> None:
        """What the interlocking reports when the layout moves: up to the hub, as for the
        panel's operations."""
        up(LOCAL, reports)

    service = None if cloud else loconet.Service(store, LOCAL, loconet_settings, on_reports=deliver)
    if service is not None:
        services.append(service)
    app.state.loconet = service

    def koppla(found: str) -> Any:
        if service is None:
            model = store.station_model(found)
            return loconet.shown(model, loconet.unavailable(), [], {}).model_dump(mode="json")
        return service.view().model_dump(mode="json")

    def local() -> loconet.Service:
        if service is None:
            raise HTTPException(409, loconet.CLOUD)
        return service

    def said_no(error: loconet.Refused) -> HTTPException:
        if error.problems:
            return HTTPException(error.status, {"message": str(error), "problems": error.problems})
        return HTTPException(error.status, str(error))

    def doing(request: Request, response: Response, slot: str | None, session: str | None) -> str:
        same_site(request)
        no_store(response)
        return unlocked(slot, session)

    @routes.get("/studio/koppla-in")
    def koppla_in(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Koppla in: the connection, the cards, the objects in their four states (STUDIO-17)
        and the learning question as it comes (STUDIO-04)."""
        no_store(response)
        return koppla(unlocked(slot, session))

    @routes.get("/studio/koppla-in/ports")
    def koppla_in_ports(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """The port list (STUDIO-11): LocoBuffer USB and BTLocoBridge, and the pretend LocoNet.
        Nothing in the cloud."""
        no_store(response)
        unlocked(slot, session)
        if service is None:
            return []
        return [p.model_dump(mode="json") for p in service.ports()]

    @routes.post("/studio/koppla-in/connect")
    def koppla_in_connect(
        ask: TklLoconetConnect,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        found = doing(request, response, slot, session)
        try:
            local().connect(ask.type, ask.port, ask.channel)
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.post("/studio/koppla-in/disconnect")
    def koppla_in_disconnect(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        found = doing(request, response, slot, session)
        local().disconnect()
        return koppla(found)

    @routes.post("/studio/koppla-in/discover")
    def koppla_in_discover(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Discover: the MGP cards answer, and their base addresses are read (STUDIO-18)."""
        found = doing(request, response, slot, session)
        try:
            local().discover()
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.put("/studio/koppla-in/card")
    def koppla_in_card(
        ask: TklCardModule,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        found = doing(request, response, slot, session)
        try:
            local().set_module(ask.card, ask.module)
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.put("/studio/koppla-in/object")
    def koppla_in_object(
        ask: TklObjectChange,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """An object's address as the owner gives it, its polarity and feedback, or Utan
        adress. Saved in the station model; it may not stop the model from running."""
        found = doing(request, response, slot, session)
        try:
            if service is not None:
                service.change(ask)
            else:
                model = store.station_model(found)
                if model is None:
                    raise HTTPException(404, loconet.NO_MODEL)
                keep_model(found, loconet.object_changed(model, ask))
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.post("/studio/koppla-in/learn")
    def koppla_in_learn(
        ask: TklLearnAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Lär in (STUDIO-04): Lägg om a switch, Skicka kör to a signal, or wait for a wagon."""
        found = doing(request, response, slot, session)
        try:
            local().learn(ask.kind, ask.name)
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.post("/studio/koppla-in/answer")
    def koppla_in_answer(
        ask: TklLearnAnswer,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        found = doing(request, response, slot, session)
        try:
            local().answer(ask)
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.post("/studio/koppla-in/level")
    def koppla_in_level(
        ask: TklLevelAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """Level 3 on, when the model has addresses and passes the checks, or off."""
        found = doing(request, response, slot, session)
        try:
            local().set_level(ask.level)
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    @routes.get("/studio/koppla-in/lyssna")
    def koppla_in_listen(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Lyssna, behind Felsök: the last LocoNet messages in Swedish (STUDIO-24)."""
        no_store(response)
        unlocked(slot, session)
        if service is None:
            return TklListen(connected=False).model_dump(mode="json")
        return service.listen().model_dump(mode="json")

    @routes.post("/studio/koppla-in/latsas")
    def koppla_in_pretend(
        ask: TklPretendAsk,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """The pretend LocoNet: a wagon put on a track circuit, or lifted off it."""
        found = doing(request, response, slot, session)
        try:
            local().pretend_wagon(ask.track_circuit, ask.occupied)
        except loconet.Refused as error:
            raise said_no(error) from error
        return koppla(found)

    # --- Studio's Prova (#85 del c): the simulated test and Provkör ------------------------

    provkors: dict[str, Provkor] = {}
    keeping = threading.Lock()

    def kept_prova(found: str) -> tuple[str, prova.Saved | None] | None:
        row = store.prova(found)
        return None if row is None else (row[0], prova.read(row[1]))

    def keep(found: str, model: str, change: Callable[[prova.Saved | None], prova.Saved]) -> None:
        """Prova's results kept with the station for the model they tried; what was kept for
        the same model is changed, anything older replaced."""
        with keeping:
            before = kept_prova(found)
            saved = change(before[1] if before is not None and before[0] == model else None)
            store.save_prova(found, model, saved.tried, saved.model_dump_json())

    def provkor_reason(model: StationModel | None) -> str | None:
        if service is None:
            return loconet.CLOUD
        if model is None or model.level < 3:
            return PROVKOR_LEVEL
        if not service.on_layout:
            return PROVKOR_LAYOUT
        return None

    def prova_view(found: str) -> Any:
        model = store.station_model(found)
        current = store.model_fingerprint(found)
        reason = provkor_reason(model)
        running = provkors.get(found)
        if running is not None and running.running:
            if reason is not None:
                running.stop()
            else:
                running.tick(interlocking_of(found).view())
        saved = kept_prova(found)
        if running is not None and running.running:
            shown_provkor: TklProvkor = running.shown(reason is None, reason)
        else:
            kept = saved[1] if saved is not None and saved[0] == current else None
            shown_provkor = idle(
                reason is None,
                reason,
                kept.provkor if kept is not None else [],
                kept.provkor_finished if kept is not None else None,
            )
        found_view = prova.view(model, current, saved, runner.job(found), shown_provkor)
        return found_view.model_dump(mode="json")

    @routes.get("/studio/prova")
    def prova_state(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Prova: the progress while it runs, the results failures first, and Klart."""
        no_store(response)
        return prova_view(unlocked(slot, session))

    @routes.post("/studio/prova/start")
    def prova_start(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Starta Prova: every route, one at a time from a clean state, in the background
        (STUDIO-05, STUDIO-27). One that already runs goes on."""
        found = doing(request, response, slot, session)
        model = store.station_model(found)
        current = store.model_fingerprint(found)
        if model is None or current is None:
            raise HTTPException(404, NO_MODEL)

        def finish(job: prova.Job, _complete: bool) -> None:
            keep(found, job.model, lambda before: prova.saved_of(job, before))

        try:
            runner.start(found, model, current, finish)
        except prova.Busy as error:
            raise HTTPException(429, PROVA_BUSY) from error
        return prova_view(found)

    @routes.post("/studio/prova/stop")
    def prova_stop(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        found = doing(request, response, slot, session)
        runner.stop(found)
        job = runner.job(found)
        if job is not None and job.thread is not None:
            job.thread.join(timeout=10)
        return prova_view(found)

    @routes.post("/studio/prova/provkor/start")
    def provkor_start(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        """Provkör: each route on the real layout, the switches ordered and their feedback
        checked, and the owner asked (STUDIO-05, STUDIO-27)."""
        found = doing(request, response, slot, session)
        model = store.station_model(found)
        reason = provkor_reason(model)
        if reason is not None or model is None:
            raise HTTPException(409, reason or NO_MODEL)
        running = provkors.get(found)
        if running is not None and running.running:
            return prova_view(found)
        state = interlocking_of(found).view()
        if state.routes or state.trains:
            raise HTTPException(409, PROVKOR_BUSY)
        current = store.model_fingerprint(found) or ""

        def changed(made: Provkor) -> None:
            def update(before: prova.Saved | None) -> prova.Saved:
                base = before or prova.Saved(simulator=prova.simulator(model.level))
                return base.model_copy(
                    update={"provkor": list(made.results), "provkor_finished": made.finished}
                )

            keep(found, current, update)

        made = Provkor(prova.ways(model), local().operate, on_change=changed)
        provkors[found] = made
        made.begin()
        return prova_view(found)

    @routes.post("/studio/prova/provkor/answer")
    def provkor_answer(
        ask: TklProvkorAnswer,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> Any:
        """The owner's answer: the signal and the path are right, wrong, or skip the route."""
        found = doing(request, response, slot, session)
        running = provkors.get(found)
        if running is None or not running.running:
            raise HTTPException(409, PROVKOR_IDLE)
        running.tick(interlocking_of(found).view())
        try:
            running.answer(ask.answer)
        except NoQuestion as error:
            raise HTTPException(409, PROVKOR_WAITS) from error
        return prova_view(found)

    @routes.post("/studio/prova/provkor/stop")
    def provkor_stop(
        request: Request, response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> Any:
        found = doing(request, response, slot, session)
        running = provkors.get(found)
        if running is not None:
            running.stop()
        return prova_view(found)

    # --- Fjärrstyrning (#36 del c): the remote interlocking and the fjärrbild ----------------

    def remote_of(found: str) -> TklRemote:
        remote = roles.role(found)
        if remote is None:
            raise HTTPException(409, "TKL är stationens ställverk, inte ett fjärrställverk.")
        return remote

    @routes.post("/fjarr/setup", status_code=201)
    def remote_set_up(
        change: TklRemoteSetUp, request: Request, response: Response
    ) -> dict[str, Any]:
        """Första start som Fjärrställverk (ingen egen station, FR1, TKL47): the same PIN and
        lock as a station's TKL, with the remote interlocking's name and its remote area."""
        same_site(request)
        no_store(response)
        given = token_urlsafe(32) if cloud else None
        slot = token_hash(given) if given else LOCAL
        remote = TklRemote(
            name=" ".join(change.name.split()), area=change.area, places=change.places
        )
        try:
            token = store.set_up(slot, fjarr.remote_id(remote.name), remote.name, change.pin)
        except AlreadySetUp as error:
            raise HTTPException(409, "TKL har redan en station.") from error
        except Full as error:
            raise HTTPException(429, "TKL i molnet har inte plats för fler stationer.") from error
        roles.keep(slot, remote)
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

    @routes.get("/fjarr/areas")
    def remote_areas(
        response: Response,
        address: Annotated[str, Query(max_length=200)],
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """The plan's remote areas and driftplatser at the hub, to choose from (FR49)."""
        no_store(response)
        unlocked(slot, session)
        return fjarr.areas(client, checked(address)).model_dump(mode="json")

    @routes.post("/fjarr/connection")
    def remote_connect(
        given: TklRemoteConnect,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """Anslut som fjärrställverk (FR4): the client kind remote, with no station and its
        remote area. TKL then waits for the approval and keeps following it, as for a station."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        asked = fjarr.connect_request(remote_of(found), given, f"TKL {VERSION}")
        address = checked(given.address)
        reaching = HubClient(client, address)
        try:
            reply = reaching.connect(asked)
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
                outside_version=0,
                message=reply.message,
                key=reply.key,
                preview=reply.preview,
                wanted=list(reply.wanted),
                asked=time.time(),
            ),
        )
        return shown(store.connection(found))

    def keyed(found: str) -> Connection:
        """The connection with its key, following the approval until it comes. Hubben decides
        which places TKL may read and act on: those it runs, controls or is offered (FR4)."""
        made = store.connection(found)
        if made is not None and made.key is None:
            made = follow(found, made)
        if made is None or made.key is None:
            raise HTTPException(409, NOT_CONNECTED)
        return made

    pictures: dict[str, TklFjarr] = {}

    @routes.get("/fjarr")
    def remote_picture(
        response: Response, slot: SlotCookie = None, session: SessionCookie = None
    ) -> dict[str, Any]:
        """Fjärrbildens data (FR31–FR38): Hubben's overview, with what TKL controls and is
        offered now (FR8). The last good one, marked stale, when the hub cannot be reached."""
        no_store(response)
        found = unlocked(slot, session)
        made = keyed(found)
        home = None if roles.role(found) else hub_places.home_place(made)
        try:
            seen = fjarr.picture(hub(made), made, home)
        except Unreachable:
            last = pictures.get(found)
            kept = last or TklFjarr(client_id=made.client_id)
            return kept.model_copy(update={"stale": True, "message": NO_CONTACT}).model_dump(
                mode="json"
            )
        except HubError as error:
            refused(found, error)
        pictures[found] = seen
        return seen.model_dump(mode="json")

    @routes.get("/fjarr/places/{place}")
    def remote_place(
        place: Annotated[str, PathPart(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")],
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """A station TKL controls, or is offered, as its own snapshot: Tåg and Klarering for the
        whole station (FR17)."""
        no_store(response)
        found = unlocked(slot, session)
        made = keyed(found)
        try:
            snapshot = hub(made).snapshot(place)
        except Unreachable:
            return seen(found, place, NO_CONTACT)
        except HubError as error:
            refused(found, error)
        heard = store.remember(found, snapshot)
        return TklView(snapshot=snapshot, heard=heard).model_dump(mode="json")

    @routes.post("/fjarr/commands")
    def remote_command(
        given: TklCommand,
        request: Request,
        response: Response,
        slot: SlotCookie = None,
        session: SessionCookie = None,
    ) -> dict[str, Any]:
        """A command at a station TKL controls or is offered: Ta emot or Avböj (FR8), Lägg
        tågvägen and Ta bort (FR11, FR13), and the clearance for the whole station (FR17). Never
        done locally: Hubben's answer and the station's report are what count."""
        same_site(request)
        no_store(response)
        found = unlocked(slot, session)
        made = keyed(found)
        sent = station.Command(client_id=made.client_id, **given.model_dump())
        try:
            reply = hub(made).command(sent)
        except Unreachable as error:
            raise HTTPException(502, NO_CONTACT) from error
        except HubError as error:
            refused(found, error)
        store.remember(found, reply.snapshot)
        return reply.model_dump(mode="json")

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
