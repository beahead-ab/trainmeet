"""The shunter's deck through TKL's API (#87 del d): a deck's role, set when it opens on the part's
screen or in Studio, Deck; the mode Bangård only for a part's deck, its presses through the
part's operations, over USB and as the pictures WebHID shows, and Studio's Sidor and Prova for
the part. Nothing here names a station
(RS13)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.tkl import (
    DeckChange,
    DeckKeyType,
    DeckMode,
    DeckPageRef,
    TklDeckDeviation,
    TklDeckProva,
    TklDecks,
    TklDeckStatus,
    TklDeckStudio,
    TklDeckView,
    TklInterlocking,
)
from tkl.app import create_app
from tkl.deck import usb
from tkl.tests.provstation import bangard
from tkl.tests.test_app import API, set_up, tkl
from tkl.tests.test_app_stallverk import with_model
from tkl.tests.test_deck_usb import picture, xl

D = API + "/deck"
STUDIO = API + "/studio/stream-deck"
PART = "bangarden"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    made = tkl(tmp_path)
    assert set_up(made).status_code == 201
    with_model(made, bangard())
    return made


def view(response: object) -> TklDeckView:
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    return TklDeckView.model_validate(response.json())  # type: ignore[attr-defined]


def at(found: TklDeckView, label: str) -> int:
    return next(i for i, f in enumerate(found.keys) if f.label == label)


def test_the_deck_on_the_parts_screen_opens_in_its_role(client: TestClient) -> None:
    """SD74: a deck opened in a part's role has Bangård only; its keys go through the part's
    operations; an unknown part is refused."""
    opened = view(client.post(D + "/del-bangarden-1", json={"model": "15", "role": PART}))
    assert opened.settings.role == PART
    assert opened.modes == [DeckMode.YARD] and opened.mode == DeckMode.YARD
    assert opened.page == "Bangård"
    train = next(f for f in opened.keys if f.type == "train")
    assert (train.text, train.under) == ("Tåg", "ingen plan"), "without Hubben, no plan (SD60)"
    street = next(i for i, f in enumerate(opened.keys) if f.type == "street")
    pressed = view(client.post(D + "/del-bangarden-1/press", json={"key": street}))
    assert pressed.accepted and pressed.message and "Växelgatan" in pressed.message
    state = TklInterlocking.model_validate(client.get(API + "/stallverk").json())
    assert state.events[0].by == "Bangården", "the part did it, as on its screen"
    out = next(i for i, f in enumerate(pressed.keys) if f.type == "request")
    asked = view(client.post(D + "/del-bangarden-1/press", json={"key": out}))
    assert asked.keys[out].under == "väntar"
    state = TklInterlocking.model_validate(client.get(API + "/stallverk").json())
    assert [r.state.value for r in state.parts[0].requests] == ["waiting"]
    assert client.post(D + "/x-1", json={"model": "15", "role": "finns-inte"}).status_code == 422
    station = view(client.post(D + "/skarm-1", json={"model": "15"}))
    assert DeckMode.YARD not in station.modes, "the tågklarerare's deck has no Bangård"


def test_the_role_is_set_in_studio_deck(client: TestClient) -> None:
    """Studio, Deck: Roll, the tågklarerare or a part; the deck opens again in it, and never
    reaches the other role's modes."""
    view(client.post(D + "/skarm-1", json={"model": "xl"}))
    decks = TklDecks.model_validate(client.get(API + "/decks").json())
    assert [(r.part, r.name) for r in decks.roles] == [(None, "Tågklareraren"), (PART, "Bangården")]
    changed = client.put(D + "/skarm-1", json={"role": PART})
    assert changed.status_code == 200, changed.text
    settings = TklDeckStatus.model_validate(changed.json()).settings
    assert settings is not None and settings.role == PART
    shunter = view(client.get(D + "/skarm-1"))
    assert shunter.modes == [DeckMode.YARD]
    mode = next(i for i, f in enumerate(shunter.keys) if f.type == "mode")
    held = view(client.post(D + "/skarm-1/press", json={"key": mode, "hold": True}))
    assert {f.under for f in held.keys if f.type == "page"} == {"Bangård"}
    assert client.put(D + "/skarm-1", json={"role": "okand"}).status_code == 422
    back = client.put(D + "/skarm-1", json={"role": ""})
    assert back.status_code == 200
    assert DeckMode.YARD not in view(client.get(D + "/skarm-1")).modes
    view(client.post(D + "/skarm-1", json={"model": "xl", "role": PART}))
    reopened = view(client.post(D + "/skarm-1", json={"model": "xl"}))
    assert reopened.settings.role == PART, "opening without a role keeps the deck's role"


def test_the_pictures_of_the_shunters_keys(client: TestClient) -> None:
    """RANG-15: a real deck, over USB or WebHID, shows the same keys as pictures."""
    opened = view(client.post(D + "/del-bangarden-1", json={"model": "xl", "role": PART}))
    for i, face in enumerate(opened.keys):
        if face.type in ("street", "request", "train", "action"):
            picture = client.get(f"{D}/del-bangarden-1/key/{i}.png", params={"size": 96})
            assert picture.status_code == 200 and picture.content[:4] == b"\x89PNG"


def test_studio_sidor_and_prova_for_a_part(client: TestClient) -> None:
    """Studio, Stream Deck: Sidor shows Bangård for a part with its own changes, the SD44 check
    covers its streets and routes out, and Prova alla knappar tries it. The pedal has none."""
    found = client.get(STUDIO, params={"size": "15", "part": PART})
    assert found.status_code == 200, found.text
    studio = TklDeckStudio.model_validate(found.json())
    assert studio.part == PART and studio.profile.modes == [DeckMode.YARD]
    assert [r.part for r in studio.roles] == [None, PART]
    assert "pedal" not in [s.size.value for s in studio.sizes]
    assert studio.checks.problems == [] and studio.checks.reached == studio.checks.routes > 0
    assert {b.group.value for b in studio.buttons} >= {"bangard-spar", "bangard-vagar-ut"}
    assert client.get(STUDIO, params={"size": "pedal", "part": PART}).status_code == 422
    [page] = studio.profile.pages
    ready = next(k for k in page.keys if k is not None and k.type == DeckKeyType.READY)
    change = TklDeckDeviation(
        change=DeckChange.KEY,
        page=DeckPageRef(kind=page.kind, name=page.name),
        key=ready,
        text="Skicka",
    )
    body = {"size": "15", "part": PART, "deviations": [change.model_dump(mode="json")]}
    saved = client.put(STUDIO, json=body)
    assert saved.status_code == 200, saved.text
    station = TklDeckStudio.model_validate(client.get(STUDIO, params={"size": "15"}).json())
    assert station.deviations == [] and station.part is None, "the tågklarerare's stay as they are"
    opened = view(client.post(D + "/del-bangarden-1", json={"model": "15", "role": PART}))
    assert any(f.text == "Skicka" for f in opened.keys), "every deck of the part gets it"
    started = client.post(STUDIO + "/prova/start", json={"size": "15", "part": PART})
    assert started.status_code == 200, started.text
    for _ in range(100):
        prova = TklDeckProva.model_validate(
            client.get(STUDIO + "/prova", params={"size": "15", "part": PART}).json()
        )
        if not prova.running:
            break
        time.sleep(0.05)
    assert prova.part == PART and prova.total and prova.did
    other = TklDeckProva.model_validate(client.get(STUDIO + "/prova", params={"size": "15"}).json())
    assert other.total == 0, "the tågklarerare's deck is not the part's"
    state = TklInterlocking.model_validate(client.get(API + "/stallverk").json())
    assert state.parts[0].requests == [], "Prova never touches the live interlocking"


def test_a_real_deck_on_usb_in_a_parts_role(tmp_path: Path) -> None:
    """RANG-15: a local TKL's deck over USB set to the part's role in Studio, Deck: it draws the
    shunter's keys and a press lays the street through the part's operation."""
    plugged: list[Any] = []
    now = [1000.0]
    app = create_app(tmp_path, discover=lambda: [], usb_finder=lambda: list(plugged))
    made = TestClient(app)
    assert set_up(made).status_code == 201
    with_model(made, bangard())
    driver = app.state.deck_usb
    assert isinstance(driver, usb.Driver)
    driver.clock = lambda: now[0]
    deck = xl()
    plugged.append(deck)
    driver.step()
    assert made.put(D + "/XL0001", json={"role": PART}).status_code == 200
    now[0] += 0.5
    driver.step()
    shown = driver.desk.view("XL0001").view
    assert shown.modes == [DeckMode.YARD]
    for index, face in enumerate(shown.keys):
        assert deck.images[index] == picture(face, (96, 96)), index
    street = next(i for i, f in enumerate(shown.keys) if f.label == "Växelgata V 51 mot 51")
    deck.down(street)
    driver.step()
    now[0] += 0.05
    deck.up(street)
    driver.step()
    state = TklInterlocking.model_validate(made.get(API + "/stallverk").json())
    assert state.events[0].by == "Bangården" and "V 51" in state.events[0].text
    assert deck.images[street] == picture(driver.desk.view("XL0001").view.keys[street], (96, 96))
