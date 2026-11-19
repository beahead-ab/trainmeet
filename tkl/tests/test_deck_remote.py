"""Fjärr (#36 del d, SD37): the fjärrtågklarerare's deck. The profile is computed from the remote
catalogues of the stations TKL controls, for every reference station and every model, with no
station named in code; a route blinks after the first press and the second sends route.request;
the key shows what Hubben and the station say, a no for three seconds; the offer key takes a
station; and the role is chosen in Studio, Stream Deck, Deck. The stations are found from the
model files; nothing here names one (RS13)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.reasons import Reason
from contracts.station_model import StationModel
from contracts.station_outside import StationOutside
from contracts.tkl import (
    DECK_REMOTE_ROLE,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    TklDecks,
    TklDeckSettings,
    TklDeckView,
    TklFjarr,
    TklFjarrChoice,
)
from tkl.deck import remote
from tkl.deck.logic import FLASH_SECONDS, Said
from tkl.deck.models import BY_ID
from tkl.stallverk import plant_of
from tkl.standard import outside_of
from tkl.studio import fjarr
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_fjarr import NAMES, NEXT
from tkl.tests.test_app_fjarr import PretendHub as RemoteHub
from tkl.tests.test_app_fjarr import remote as remote_tkl
from tkl.tests.test_app_stallverk import with_model

MODELS = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
CONTEXT = station.MeetContext(meet_id="provmote", version=1, game_day=1, epoch=0)
CLOCK = station.Clock(time="09:00", seconds=32400, running=False, speed=1, game_day=1)
ME = "fjarr-1"
SIZES = [m for m in BY_ID if m != DeckModelId.PEDAL]
__all__ = ["remote_tkl"]


def outside(name: str) -> StationOutside:
    """A reference station's outside with every route of its catalogue (FR10)."""
    model = StationModel.model_validate_json((MODELS / f"{name}.tkl.json").read_text("utf-8"))
    plant = plant_of(model)
    chosen = TklFjarrChoice(routes=[c.id for c in fjarr.candidates(plant)])
    made = outside_of(model, model.station_id, model.name, remote=fjarr.remote_of(plant, chosen))
    return StationOutside.model_validate(made.model_dump(mode="json"))


def place(name: str, found: StationOutside, **more: Any) -> station.OverviewPlace:
    return station.OverviewPlace(
        place=station.Neighbour(place=name, code=name[:3].upper(), name=found.name),
        mode=station.PlaceMode.REMOTE,
        controllable=True,
        outside=found,
        **more,
    )


def picture(*places: station.OverviewPlace, offers: list[station.OfferHere] | None = None) -> Any:
    return TklFjarr(
        overview=station.Overview(context=CONTEXT, clock=CLOCK, places=list(places)),
        client_id=ME,
        controls=[p.place.place for p in places],
        offers=offers or [],
        heard=datetime.now(UTC),
    )


class Hands:
    """The hub as the deck reaches it: every command kept, and the answer given."""

    def __init__(self, said: Said | None = None) -> None:
        self.sent: list[tuple[str, station.Action, dict[str, object]]] = []
        self.said = said or Said(True, "Ja.")

    def command(self, at: str, action: station.Action, payload: dict[str, object]) -> Said:
        self.sent.append((at, action, payload))
        return self.said


@pytest.mark.parametrize("name", STATIONS)
def test_the_profile_is_made_from_the_catalogues(name: str) -> None:
    """A page per station, more pages when its routes do not fit, a key per catalogue route in
    the catalogue's order, the offers and Läge on every page; the mode Fjärr only (SD37)."""
    found = outside(name)
    stations = remote.stations(picture(place(name, found)))
    assert [s.place for s in stations] == [name]
    for size in SIZES:
        profile = remote.build(BY_ID[size].grid, size, stations)
        assert profile.modes == [DeckMode.REMOTE], size
        assert profile.pages and all(p.mode == DeckMode.REMOTE for p in profile.pages)
        assert all(p.name.startswith(found.name) for p in profile.pages), size
        keyed = [
            k.remote
            for p in profile.pages
            for k in p.keys
            if k is not None and k.type == DeckKeyType.REMOTE_ROUTE
        ]
        assert keyed == [r.id for r in found.remote_routes], size
        for page in profile.pages:
            kinds = {k.type for k in page.keys if k is not None}
            assert DeckKeyType.OFFER in kinds, (size, page.name)
            assert kinds & {DeckKeyType.MODE, DeckKeyType.NEXT}, (size, page.name)
        assert remote.build(BY_ID[size].grid, size, stations) is profile, "made once"
    pedal = remote.build(BY_ID[DeckModelId.PEDAL].grid, DeckModelId.PEDAL, stations)
    assert pedal.pages == [], "no fjärr deck on a pedal"


def test_every_reference_station_on_one_deck_and_none() -> None:
    """Two stations controlled: each has its pages. None: one page with the offers."""
    found = [place(name, outside(name)) for name in STATIONS]
    profile = remote.build(
        BY_ID[DeckModelId.XL].grid, DeckModelId.XL, remote.stations(picture(*found))
    )
    names = {p.name.rsplit(" ", 1)[0] if p.name[-1].isdigit() else p.name for p in profile.pages}
    assert names == {p.outside.name for p in found if p.outside is not None}
    empty = remote.build(BY_ID[DeckModelId.FIFTEEN].grid, DeckModelId.FIFTEEN, [])
    assert [p.name for p in empty.pages] == [remote.NOTHING_YET]


def deck_for(name: str, size: DeckModelId = DeckModelId.FIFTEEN) -> tuple[Any, StationOutside]:
    found = outside(name)
    stations = remote.stations(picture(place(name, found)))
    settings = TklDeckSettings(serial="fjarr-1", model=size, grid=BY_ID[size].grid)
    deck = remote.open_deck(settings, remote.build(settings.grid, size, stations))
    return deck, found


def first_route(deck: Any) -> int:
    page = deck.profile.pages[deck.page]
    return next(
        i for i, k in enumerate(page.keys) if k is not None and k.type == DeckKeyType.REMOTE_ROUTE
    )


def world(name: str, found: StationOutside, *, now: float = 100.0, **more: Any) -> Any:
    return remote.RemoteWorld(fjarr=picture(place(name, found, **more)), time="09:00", now=now)


def test_a_route_blinks_and_the_second_press_sends_it() -> None:
    """SD37, FR13: the first press chooses the route and the key blinks; the second press sends
    route.request with the catalogue's id; the key waits until the station has answered."""
    name = STATIONS[0]
    deck, found = deck_for(name)
    hands = Hands()
    key = first_route(deck)
    here = world(name, found)
    remote.press(deck, here, hands, key)
    assert hands.sent == []
    face = remote.view(deck, here).keys[key]
    assert face.blink is not None and face.under == "tryck igen"
    remote.press(deck, here, hands, key)
    [(at, action, payload)] = hands.sent
    route = found.remote_routes[0]
    assert (at, action, payload["route"]) == (name, station.Action.ROUTE_REQUEST, route.id)
    assert deck.chosen_route is None
    request = str(payload["request_id"])
    asked = station.RemoteRouteHere(
        request_id=request,
        route=route.id,
        state=station.RemoteRouteState.REQUESTED,
        by=ME,
        asked_at="09:00",
    )
    waiting = world(name, found, routes=[asked])
    assert remote.view(deck, waiting).keys[key].under == "begärd"
    locked = world(
        name,
        found,
        routes=[asked.model_copy(update={"state": station.RemoteRouteState.LOCKED})],
        route_state=station.RouteState(
            locked=[station.LockedRoute(route=route.id, by=station.RouteBy.REMOTE)]
        ),
    )
    shown = remote.view(deck, locked).keys[key]
    assert (shown.under, shown.bg) == ("låst", "#15803d"), "green when the station has locked it"
    assert deck.sent_routes == {}
    # Holding the route TKL laid takes it away.
    remote.press(deck, locked, hands, key, hold=True)
    assert hands.sent[-1][1:] == (station.Action.ROUTE_CANCEL, {"request_id": request})


def test_a_no_stands_on_the_key_for_three_seconds() -> None:
    """SD18: Hubben's no at once, and the station's no when it comes, red with the reason for
    three seconds; then the key is as before."""
    name = STATIONS[0]
    deck, found = deck_for(name)
    key = first_route(deck)
    said = "En fientlig väg är lagd."
    hands = Hands(Said(False, said))
    here = world(name, found)
    remote.press(deck, here, hands, key)
    remote.press(deck, here, hands, key)
    soon = world(name, found, now=100.0 + FLASH_SECONDS - 0.1)
    face = remote.view(deck, soon).keys[key]
    assert face.type == "answer" and "fientlig" in face.under
    later = world(name, found, now=100.0 + FLASH_SECONDS + 0.1)
    assert remote.view(deck, later).keys[key].type == "remote"
    # The station says no after the request went: the key shows its reason too.
    hands = Hands()
    remote.press(deck, later, hands, key)
    remote.press(deck, later, hands, key)
    request = str(hands.sent[-1][2]["request_id"])
    refused = station.RemoteRouteHere(
        request_id=request,
        route=found.remote_routes[0].id,
        state=station.RemoteRouteState.REFUSED,
        reason=Reason.CONFLICTING_ROUTE,
        by=ME,
        asked_at="09:00",
    )
    answered = world(name, found, now=200.0, routes=[refused])
    face = remote.view(deck, answered).keys[key]
    assert face.type == "answer" and "fientlig" in face.under
    assert remote.view(deck, world(name, found, now=204.0)).keys[key].type == "remote"


def test_the_offer_key_takes_a_station_and_laege_lists_the_pages() -> None:
    """FR8: the offer stands on its key; a press takes it, a hold declines it. Läge drops a
    chosen route, and otherwise shows the pages."""
    name = STATIONS[0]
    deck, found = deck_for(name)
    offered = station.OfferHere(
        place="annan",
        to=station.Receiver(client_id=ME, kind=station.ClientKind.REMOTE, name="Fjärr"),
        expires_in=42,
    )
    here = remote.RemoteWorld(
        fjarr=picture(place(name, found), offers=[offered]), time="09:00", now=1.0
    )
    page = deck.profile.pages[deck.page]
    offer = next(i for i, k in enumerate(page.keys) if k and k.type == DeckKeyType.OFFER)
    assert "0:42" in remote.view(deck, here).keys[offer].under
    hands = Hands()
    remote.press(deck, here, hands, offer)
    remote.press(deck, here, hands, offer, hold=True)
    assert [(a, p) for _, a, p in hands.sent] == [
        (station.Action.PLACE_OFFER_ANSWER, {"accept": True}),
        (station.Action.PLACE_OFFER_ANSWER, {"accept": False}),
    ]
    mode = next(i for i, k in enumerate(page.keys) if k and k.type == DeckKeyType.MODE)
    remote.press(deck, here, hands, first_route(deck))
    remote.press(deck, here, hands, mode)
    assert deck.chosen_route is None and deck.overlay is None
    remote.press(deck, here, hands, mode)
    tabs = [f for f in remote.view(deck, here).keys if f.type == "page"]
    assert [t.text for t in tabs] == [p.name for p in deck.profile.pages]


def test_without_hubben_every_key_says_no_contact() -> None:
    deck, _ = deck_for(STATIONS[0])
    shown = remote.view(deck, remote.RemoteWorld(fjarr=None))
    assert not shown.contact and {f.type for f in shown.keys} == {"contact"}


# --- In TKL: the role in Studio, Stream Deck, Deck, and the deck on the screen ----------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made)
    return made


def test_the_role_is_chosen_in_studio_deck(client: TestClient) -> None:
    """Studio, Stream Deck, Deck lists the fjärrtågklarerare's role; a deck set to it opens in
    Fjärr, which says Ingen kontakt until TKL controls a station through Hubben."""
    opened = client.post(API + "/deck/skarm-1", json={"model": "15"})
    assert opened.status_code == 200, opened.text
    assert TklDeckView.model_validate(opened.json()).mode != DeckMode.REMOTE
    decks = TklDecks.model_validate(client.get(API + "/decks").json())
    assert (DECK_REMOTE_ROLE, "Fjärrtågklareraren", True) in [
        (r.part, r.name, r.remote) for r in decks.roles
    ]
    changed = client.put(API + "/deck/skarm-1", json={"role": DECK_REMOTE_ROLE})
    assert changed.status_code == 200, changed.text
    shown = TklDeckView.model_validate(client.get(API + "/deck/skarm-1").json())
    assert (shown.mode, shown.modes) == (DeckMode.REMOTE, [DeckMode.REMOTE])
    assert not shown.contact
    back = client.put(API + "/deck/skarm-1", json={"role": ""})
    assert back.status_code == 200 and back.json()["settings"]["role"] is None
    again = TklDeckView.model_validate(client.get(API + "/deck/skarm-1").json())
    assert again.mode != DeckMode.REMOTE
    on_screen = client.post(API + "/deck/fjarr-1", json={"model": "xl", "role": DECK_REMOTE_ROLE})
    assert on_screen.status_code == 200, on_screen.text
    assert TklDeckView.model_validate(on_screen.json()).mode == DeckMode.REMOTE


def test_the_remote_interlockings_deck_on_the_screen(
    remote_tkl: tuple[TestClient, RemoteHub],
) -> None:
    """In the remote role's own app every deck is the fjärrtågklarerare's: the offer key takes
    the station, its page follows, a route's key blinks after the first press, and the second
    sends route.request through Hubben, as the fjärrbild's /fjarr/commands; the key is green when
    the station has locked it."""
    client, hub = remote_tkl
    hub.offers = {NEXT: 50}
    opened = client.post(API + "/deck/fjarr-1", json={"model": "15"})
    assert opened.status_code == 200, opened.text
    shown = TklDeckView.model_validate(opened.json())
    assert shown.mode == DeckMode.REMOTE and shown.settings.role == DECK_REMOTE_ROLE
    offer = next(i for i, f in enumerate(shown.keys) if f.type == "offer")
    assert "0:50" in shown.keys[offer].under
    taken = TklDeckView.model_validate(
        client.post(API + "/deck/fjarr-1/press", json={"key": offer}).json()
    )
    assert taken.accepted and hub.controls == [NEXT]
    assert taken.page == NAMES[NEXT], "the station's page, from its catalogue"
    key = next(i for i, f in enumerate(taken.keys) if f.type == "remote")
    first = TklDeckView.model_validate(
        client.post(API + "/deck/fjarr-1/press", json={"key": key}).json()
    )
    assert first.keys[key].blink is not None and first.refresh_ms <= 1000
    assert hub.commands[-1].action == station.Action.PLACE_OFFER_ANSWER
    second = TklDeckView.model_validate(
        client.post(API + "/deck/fjarr-1/press", json={"key": key}).json()
    )
    sent = hub.commands[-1]
    assert (sent.place, sent.action) == (NEXT, station.Action.ROUTE_REQUEST)
    assert sent.client_id == hub.client_id
    assert second.keys[key].under == "låst"
