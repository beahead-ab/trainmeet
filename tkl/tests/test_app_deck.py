"""Stream Deck's API (#86 del a) under /api/tkl/1/deck: the same for the deck on the screen and,
in del b, a real deck. A deck is opened by its serial number with its model or its grid (SD35,
SD53), read, pressed, held, turned and touched; it waits like the interlocking's second screen.
Every route set is counted, and a set route can be pinned on Favoriter (SD24, SD48). Nothing
here names a station (RS13)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from contracts.tkl import (
    DeckConnection,
    TklDeckFavourites,
    TklDeckProfile,
    TklDecks,
    TklDeckView,
    TklWait,
)
from tkl.tests.test_app import API, PIN, set_up, tkl
from tkl.tests.test_app_stallverk import with_model

D = API + "/deck"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made)
    return made


def view(response: object) -> TklDeckView:
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    return TklDeckView.model_validate(response.json())  # type: ignore[attr-defined]


def key(found: TklDeckView, label: str) -> int:
    return next(i for i, f in enumerate(found.keys) if f.label == label)


def test_a_deck_is_opened_by_its_serial_number_with_its_model_or_grid(client: TestClient) -> None:
    """SD35, SD53, SD54: a model gives its grid; a grid TKL does not know gets its default."""
    fifteen = view(client.post(D + "/skarm-1", json={"model": "15"}))
    assert (fifteen.settings.grid.columns, fifteen.settings.grid.rows) == (5, 3)
    assert len(fifteen.keys) == 15 and fifteen.fixed == [10, 11, 12, 13, 14]
    odd = view(client.post(D + "/ABC123", json={"grid": {"columns": 4, "rows": 3}}))
    assert odd.settings.model is None and len(odd.keys) == 12
    module = view(client.post(D + "/MOD15", json={"grid": {"columns": 5, "rows": 3}}))
    assert module.settings.model == "15", "a Module 15 gets the 15's profile (SD54)"
    assert client.post(D + "/bad serial", json={"model": "xl"}).status_code == 422
    assert client.post(D + "/x", json={}).status_code == 422
    assert client.get(D + "/okand").status_code == 404
    models = client.get(D + "/models").json()
    assert len(models) == 11
    profile = TklDeckProfile.model_validate(
        client.get(D + "/profile", params={"model": "xl"}).json()
    )
    assert profile.places and profile.pages


def test_a_press_calls_the_interlocking_and_every_route_set_is_counted(client: TestClient) -> None:
    """SD1, SD24: a goal pressed in Platser sets the route through the interlocking; the
    route is counted, part by part, and only routes."""
    opened = view(client.post(D + "/skarm-1", json={"model": "xl"}))
    pressed = view(client.post(D + "/skarm-1/press", json={"key": key(opened, "Plats O")}))
    goal = key(pressed, "Mål 2")
    done = view(client.post(D + "/skarm-1/press", json={"key": goal}))
    assert done.accepted and done.message and "lagd" in done.message
    routes = client.get(API + "/stallverk").json()["routes"]
    assert [r["enters"] for r in routes] == ["O"]
    favourites = TklDeckFavourites.model_validate(client.get(API + "/deck-favoriter").json())
    assert [(c.start, c.count) for c in favourites.counted] == [(routes[0]["start"], 1)]
    client.post(API + "/stallverk/release", json={"route": routes[0]["id"]})
    client.post(
        API + "/stallverk/route", json={"start": routes[0]["start"], "end": routes[0]["end"]}
    )
    favourites = TklDeckFavourites.model_validate(client.get(API + "/deck-favoriter").json())
    assert favourites.counted[0].count == 2, "the panel's routes are counted too"
    assert [(r.start, r.end) for r in favourites.shown] == [(routes[0]["start"], routes[0]["end"])]


def test_a_route_is_pinned_on_favoriter(client: TestClient) -> None:
    """SD48: Fäst på Stream Deck puts a route on Favoriter; one that does not exist is a no."""
    pinned = client.post(
        API + "/deck-favoriter", json={"start": "In", "end": "12", "kind": "train"}
    )
    assert pinned.status_code == 200, pinned.text
    found = TklDeckFavourites.model_validate(pinned.json())
    assert [(r.start, r.end) for r in found.pinned] == [("In", "12")]
    assert (
        client.post(
            API + "/deck-favoriter", json={"start": "In", "end": "Nowhere", "kind": "train"}
        ).status_code
        == 404
    )
    opened = view(client.post(D + "/skarm-1", json={"model": "xl"}))
    client.post(D + "/skarm-1/press", json={"key": 31, "hold": True})
    every = view(client.get(D + "/skarm-1"))
    assert "Favoriter" in [f.text for f in every.keys], "the page is there with a pinned route"
    unpinned = client.post(
        API + "/deck-favoriter", json={"start": "In", "end": "12", "kind": "train", "pinned": False}
    )
    assert TklDeckFavourites.model_validate(unpinned.json()).pinned == []
    del opened


def test_the_locked_tkl_shows_only_the_clock(client: TestClient) -> None:
    """SD30: the deck shows only the clock while TKL is locked, and a press does nothing."""
    view(client.post(D + "/skarm-1", json={"model": "15"}))
    client.post(API + "/lock")
    locked = view(client.get(D + "/skarm-1"))
    assert locked.locked and [f.text for f in locked.keys if f.text] == [locked.keys[12].text]
    pressed = view(client.post(D + "/skarm-1/press", json={"key": 5}))
    assert pressed.locked
    assert client.post(D + "/skarm-1", json={"model": "xl"}).status_code == 401
    client.post(API + "/unlock", json={"pin": PIN})
    assert client.get(API + "/stallverk").json()["routes"] == []


def test_two_decks_at_one_workplace_share_the_start_and_wait_for_each_other(
    client: TestClient,
) -> None:
    """SD36, STV-05: a start pressed on one deck lights the goals on the other, whose wait
    says it changed."""
    left = view(client.post(D + "/vanster", json={"model": "15"}))
    right = view(client.post(D + "/hoger", json={"model": "xl"}))
    waited = TklWait.model_validate(
        client.get(D + "/hoger/wait", params={"after": right.revision, "seconds": 0}).json()
    )
    assert not waited.changed
    view(client.post(D + "/vanster/press", json={"key": key(left, "Plats O")}))
    waited = TklWait.model_validate(
        client.get(D + "/hoger/wait", params={"after": right.revision, "seconds": 1}).json()
    )
    assert waited.changed
    lit = view(client.get(D + "/hoger"))
    assert any(f.type == "goal" for f in lit.keys)
    laid = client.post(API + "/stallverk/route", json={"start": "In", "end": "12"})
    assert laid.json()["accepted"], laid.text
    after = TklWait.model_validate(
        client.get(D + "/hoger/wait", params={"after": lit.revision, "seconds": 1}).json()
    )
    assert after.changed, "the interlocking's change wakes the deck"


def test_dials_and_touch_points(client: TestClient) -> None:
    """SD82, SD83: the + turns and presses its dials, the strip says what each stands on; Neo's
    touch points change the page."""
    plus = view(client.post(D + "/plus", json={"model": "plus"}))
    assert [s.label for s in plus.strip] == ["Start", "Mål", "Del", "Lagd väg"]
    turned = view(client.post(D + "/plus/dial", json={"dial": 0, "turn": 1}))
    assert turned.strip[0].value != "–", "the start dial chose a place"
    neo = view(client.post(D + "/neo", json={"model": "neo"}))
    assert neo.info and neo.page
    touched = view(client.post(D + "/neo/touch", json={"point": 1}))
    assert touched.page != neo.page


def test_a_station_keeps_sixteen_decks(client: TestClient) -> None:
    """SD35. Ported: cda-tkl test/stream-deck-profile.test.mjs, "the layout store keeps one
    layout per deck, known by serial": a serial must be a serial, a deck keeps its settings
    over a new opening, and at most sixteen decks are kept; the one seen longest ago goes."""
    for n in range(16):
        view(client.post(D + f"/deck-{n}", json={"model": "mini"}))
    view(client.post(D + "/deck-0", json={"model": "xl", "workplace": "2"}))
    reopened = view(client.post(D + "/deck-0", json={"model": "xl"}))
    assert reopened.settings.workplace == "2", "kept with the deck"
    view(client.post(D + "/deck-16", json={"model": "15"}))
    assert client.get(D + "/deck-1").status_code == 404, "the one seen longest ago is gone"
    assert client.get(D + "/deck-0").status_code == 200
    assert client.get(D + "/deck-16").status_code == 200


def test_level_0_has_no_deck(tmp_path: Path) -> None:
    client = tkl(tmp_path)
    assert set_up(client).status_code == 201
    assert client.post(D + "/skarm-1", json={"model": "15"}).status_code == 404


def test_every_model_is_inte_provad_until_a_real_deck_has_been_tried(client: TestClient) -> None:
    """SD58: no model is tried with a real deck yet."""
    models = client.get(D + "/models").json()
    assert models and all(m["tried"] is False for m in models)


def test_a_deck_in_the_browser_with_webhid_and_its_status(client: TestClient) -> None:
    """SD35, SD50: a deck opened with WebHID is connected until the browser lets it go; the
    deck on the screen says so too. TKL here is local and owns decks over USB."""
    view(client.post(D + "/A1B2C3", json={"model": "mini", "connection": "webhid"}))
    view(client.post(D + "/skarm-1", json={"model": "15"}))
    found = TklDecks.model_validate(client.get(API + "/decks").json())
    assert found.usb is True
    shown = {d.serial: (d.connection, d.name, d.tried) for d in found.decks}
    assert shown == {
        "A1B2C3": (DeckConnection.WEBHID, "Mini", False),
        "skarm-1": (DeckConnection.SCREEN, "Stream Deck 15", False),
    }
    assert client.post(D + "/A1B2C3/close").status_code == 204
    found = TklDecks.model_validate(client.get(API + "/decks").json())
    assert {d.serial: d.connection for d in found.decks}["A1B2C3"] is None


def test_las_locks_tkl_for_the_whole_station(client: TestClient) -> None:
    """SD30: Lås on the deck's page Läge, or in TKL, locks TKL for every browser and every
    deck: only the clock, and only the PIN opens it. The PIN rules are as before (TKL18)."""
    other = TestClient(client.app)
    assert other.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    opened = view(client.post(D + "/skarm-1", json={"model": "15"}))
    lage = key(opened, "Läge " + opened.keys[14].text)
    menu = view(client.post(D + "/skarm-1/press", json={"key": lage}))
    locked = view(client.post(D + "/skarm-1/press", json={"key": key(menu, "Lås TKL")}))
    assert locked.locked and locked.message == "TKL är låst. PIN-koden låser upp."
    assert [f.type for f in locked.keys if f.type != "empty"] == ["clock"]
    for browser in (client, other):
        state = browser.get(API + "/state").json()
        assert (state["unlocked"], state["locked"]) == (False, True)
        assert browser.get(API + "/stallverk").status_code == 401, "every session ended"
    assert view(other.get(D + "/skarm-1")).locked, "the deck reads the clock without a PIN"
    assert other.post(API + "/unlock", json={"pin": "0000"}).status_code == 401
    assert other.post(API + "/unlock", json={"pin": PIN}).status_code == 200
    assert not view(other.get(D + "/skarm-1")).locked
    assert client.get(API + "/state").json()["locked"] is False
    assert client.get(API + "/state").json()["unlocked"] is False, "this browser gives its PIN"
    assert other.post(API + "/lock").status_code == 200
    assert view(client.get(D + "/skarm-1")).locked, "Lås in TKL locks the decks too"
