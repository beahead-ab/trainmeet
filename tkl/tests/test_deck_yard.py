"""Bangård (#87 del d): the shunter's deck, made from a part of the model for every grid, and what
its keys show and do through the interlocking's own part operations (SD60, SD61, SD74, SD86,
SD87, TKL109, TKL122, RANG-04).

A made-up station with a yard (provstation.bangard), given streets and routes out from both ends
here, carries the rules; the reference station with a part is found by its data and the 15's
page is checked against what its part has, never by name (RS13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PIL import Image

from contracts import station
from contracts.station_model import PartSide, Position, RouteOut, StationModel, SwitchStreet
from contracts.tkl import (
    DeckAction,
    DeckChange,
    DeckDial,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckStyle,
    DeckTried,
    RouteKind,
    TklDeckDeviation,
    TklDeckFace,
    TklDeckKey,
    TklDeckModel,
    TklDeckProfile,
    TklDeckSettings,
    TklPartTrain,
)
from tkl import track_plan
from tkl.deck import logic, render, yard
from tkl.deck.checks import yard_check
from tkl.deck.deviations import apply, known_of, ref_of
from tkl.deck.logic import Deck, Said, Selection, World
from tkl.deck.models import MODELS, model_of
from tkl.deck.places import Geography
from tkl.deck.profile import build, frame, geography_of, yard_tracks
from tkl.deck.tryall import keys_of, try_key
from tkl.stallverk import Interlocking, Outcome, Plant, plant_of
from tkl.standard import RouteKind as EngineKind
from tkl.tests.provstation import bangard

K = DeckKeyType
A = DeckAction
LEFT, RIGHT = PartSide.LEFT, PartSide.RIGHT
PLUS, MINUS = Position.PLUS, Position.MINUS
PART = "bangarden"
REFERENCE = Path(__file__).resolve().parents[1] / "referens"
GRIDS = [m for m in MODELS if m.id != DeckModelId.PEDAL]


def two_ends() -> StationModel:
    """The made-up yard with a street to each track from both ends, a load track from one end,
    and routes out from the left, from the right and from neither: V from both ends, B from the
    right, which goes beside B ut, from neither, so that both can be approved at once."""
    made = bangard()
    [part] = made.parts
    streets = [
        *part.streets,
        SwitchStreet(id="H51", name="H 51", side=RIGHT, track="51", positions={"4": PLUS}),
        SwitchStreet(id="H52", name="H 52", side=RIGHT, track="52", positions={"4": MINUS}),
        SwitchStreet(id="L1", name="Last 1", side=LEFT, track="Last", positions={"4": PLUS}),
    ]
    outs = [
        *part.routes_out,
        RouteOut(id="HUt", name="H Ut", side=RIGHT, track="V", start="U1", end="Ut"),
        RouteOut(id="UB", name="H B", side=RIGHT, track="B", start="U1", end="B"),
        RouteOut(id="BUt", name="B ut", side=None, track="B ut", start="B", end="Ut"),
    ]
    changed = part.model_copy(update={"streets": streets, "routes_out": outs})
    return made.model_copy(update={"parts": [changed]})


def reference() -> tuple[StationModel, str]:
    """The reference station with a part, and the part's id: found by data (RS13)."""
    for path in sorted(REFERENCE.glob("*.tkl.json")):
        model = StationModel.model_validate_json(path.read_text("utf-8"))
        if model.parts:
            return model, model.parts[0].id
    raise AssertionError("a reference station has a part")


@dataclass
class Hands:
    """The interlocking's own functions, the part's included, recorded."""

    it: Interlocking
    calls: list[str] = field(default_factory=list)

    def said(self, outcome: Outcome) -> Said:
        return Said(outcome.accepted, outcome.message)

    def set_route(self, start: str, end: str, kind: RouteKind | None) -> Said:
        wanted = EngineKind(kind.value) if kind is not None else None
        return self.said(self.it.set_route(start, end, wanted))

    def release(self, route: int) -> Said:
        return self.said(self.it.release(route))

    def step(self, route: int) -> Said:
        self.calls.append(f"step {route}")
        return self.said(self.it.step(route))

    def arrive(self, route: int) -> Said:
        return self.said(self.it.arrive(route))

    def function(self, name: str, on: bool) -> Said:
        return Said(False, "Ingen funktion.")

    def command(
        self, action: station.Action, payload: dict[str, object], revision: station.Revision | None
    ) -> Said:
        return Said(False, "Ingen hubb.")

    def lock(self) -> Said:
        self.calls.append("lock")
        return Said(True, "Låst.")

    def reset(self) -> Said:
        return self.said(self.it.reset(True))

    def emergency(self, route: int) -> Said:
        return self.said(self.it.emergency_release(route, True))

    def part_street(self, part: str, street: str) -> Said:
        self.calls.append(f"street {street}")
        return self.said(self.it.part_street(part, street))

    def part_request(self, part: str, route_out: str) -> Said:
        self.calls.append(f"request {route_out}")
        return self.said(self.it.part_request(part, route_out))

    def part_return(self, part: str, request: int) -> Said:
        self.calls.append(f"return {request}")
        return self.said(self.it.part_return(part, request))

    def part_done(self, part: str) -> Said:
        self.calls.append("done")
        return self.said(self.it.part_done(part))

    def part_gates(self, part: str) -> Said:
        self.calls.append("gates")
        return self.said(self.it.part_gates(part))

    def part_ring(self, part: str) -> Said:
        self.calls.append("ring")
        return self.said(self.it.part_ring(part))

    def part_fika(self, part: str, on: bool) -> Said:
        self.calls.append(f"fika {on}")
        return self.said(self.it.part_fika(part, on))

    def part_ready(self, part: str, train: TklPartTrain) -> Said:
        self.calls.append(f"ready {train.number}")
        found = self.it.part_ready(
            part, train.number, call=train.call, track=train.track, departure=train.departure
        )
        return self.said(found)


PLAN = [
    TklPartTrain(number="9101", track="51", departure="10:42"),
    TklPartTrain(number="9103", track="52", departure="11:15"),
    TklPartTrain(number="9105", track="51", departure="11:48"),
]


@dataclass
class Yard:
    model: StationModel
    part: str
    it: Interlocking
    hands: Hands
    trains: list[TklPartTrain] | None = None
    now: float = 100.0
    selection: Selection = field(default_factory=Selection)

    @property
    def plant(self) -> Plant:
        return self.it.plant

    @property
    def geo(self) -> Geography:
        """The station's geography, with its panel: the cache keeps one per model."""
        return geography_of(self.plant, track_plan.panel_of(self.model))

    def world(self) -> World:
        panel = track_plan.panel_of(self.model)
        return World(
            plant=self.plant,
            geo=geography_of(self.plant, panel),
            interlocking=self.it,
            time="10:00",
            station="Provby",
            now=self.now,
            part_trains=self.trains,
        )

    def deck(self, model_id: DeckModelId = DeckModelId.FIFTEEN, **settings: object) -> Deck:
        grid = model_of(model_id).grid
        made = build(self.plant, track_plan.panel_of(self.model), grid, model_id, self.part)
        given = TklDeckSettings(
            serial=f"d-{model_id.value}", model=model_id, grid=grid, role=self.part
        ).model_copy(update=settings)
        return logic.open_deck(given, made, self.world())

    def faces(self, deck: Deck) -> list[TklDeckFace]:
        return logic.view(deck, self.selection, self.world()).keys

    def press(self, deck: Deck, key: int, hold: bool = False) -> None:
        logic.press(deck, self.selection, self.world(), self.hands, key, hold)

    def at(self, deck: Deck, kind: DeckKeyType, track: str | None = None, **more: object) -> int:
        page = logic.current(deck)
        assert page is not None
        for i, key in enumerate(page.keys):
            if key is None or key.type != kind or (track is not None and key.track != track):
                continue
            if all(getattr(key, name) == value for name, value in more.items()):
                return i
        raise AssertionError((kind, track, more))

    def action(self, deck: Deck, action: DeckAction) -> int:
        return self.at(deck, K.ACTION, action=action)


def made_up(trains: list[TklPartTrain] | None = None) -> Yard:
    model = two_ends()
    it = Interlocking(plant_of(model))
    return Yard(model, PART, it, Hands(it), trains)


def the_reference() -> Yard:
    model, part = reference()
    it = Interlocking(plant_of(model))
    return Yard(model, part, it, Hands(it))


def profile_of(y: Yard, model_id: DeckModelId) -> TklDeckProfile:
    grid = model_of(model_id).grid
    return build(y.plant, track_plan.panel_of(y.model), grid, model_id, y.part)


def shown(y: Yard) -> list[str]:
    """The part's state in short, for the asserts."""
    [part] = [p for p in y.it.view().parts if p.id == y.part]
    return [f"{r.route_out} {r.state.value}" for r in part.requests]


# --- the profile, for every grid ------------------------------------------------------------


@pytest.mark.parametrize("where", ["made-up", "reference"])
@pytest.mark.parametrize("model", GRIDS, ids=[m.id.value for m in GRIDS])
def test_the_bangard_profile_for_every_grid(where: str, model: TklDeckModel) -> None:
    """SD61, SD74, SD86, SD87: one mode, Bangård; Läge in its place; the train key, Lämna,
    Klart and Ring on every grid; every street to a track of the yard and every route out
    reached (the SD44 check), from the part's own data."""
    y = made_up() if where == "made-up" else the_reference()
    found = profile_of(y, model.id)
    f = frame(found.grid)
    assert found.modes == [DeckMode.YARD] and found.part == y.part
    assert found.pages and all(p.mode == DeckMode.YARD for p in found.pages)
    assert all(p.kind == DeckPageKind.YARD for p in found.pages)
    role, kind = ("next", K.NEXT) if f.style == DeckStyle.NEXT else ("mode", K.MODE)
    assert all(p.keys[f.fixed[role]] == TklDeckKey(type=kind) for p in found.pages), "SD27"
    keys = [k for p in found.pages for k in p.keys if k is not None]
    actions = {k.action for k in keys if k.type == K.ACTION}
    assert {A.GIVE_BACK, A.DONE, A.RING} <= actions
    assert any(k.type == K.READY for k in keys)
    if f.style != DeckStyle.COLUMN:
        assert any(k.type == K.END for k in keys), "Ände, where the keys follow the end"
    plant = y.plant
    checked = yard_check(found, plant, known_of(plant, y.geo, y.part))
    assert checked.problems == [] and checked.reached == checked.routes > 0
    big = found.grid.columns * found.grid.rows >= 32
    assert ({A.GATES, A.HORN, A.FIKA, A.RUN, A.CLOCK} <= actions) == big, "RANG-04"


def test_the_15_is_the_single_page_of_the_document() -> None:
    """SD61, SD86, TKL109, TKL122: the tracks with a street from both ends and the train key,
    the routes out, and Ände, Lämna, Klart, Ring and Läge, on one page."""
    y = the_reference()
    found = profile_of(y, DeckModelId.FIFTEEN)
    [page] = found.pages
    part = y.plant.parts[y.part]
    through = [t.track for t in yard_tracks(part.streets.values()) if t.through]
    outs = [t.track for t in yard_tracks(part.routes_out.values())]
    rows = [page.keys[r * 5 : r * 5 + 5] for r in range(3)]
    assert [(k.type, k.track, k.side) for k in rows[0][:4] if k] == [
        (K.STREET, t, None) for t in through
    ]
    assert rows[0][4] == TklDeckKey(type=K.READY)
    assert [(k.type, k.track) for k in rows[1] if k] == [(K.REQUEST, t) for t in outs]
    assert [(k.type, k.action) for k in rows[2] if k] == [
        (K.END, None),
        (K.ACTION, A.GIVE_BACK),
        (K.ACTION, A.DONE),
        (K.ACTION, A.RING),
        (K.MODE, None),
    ]
    stubs = [t.track for t in yard_tracks(part.streets.values()) if not t.through]
    assert stubs and not any(k and k.track in stubs for k in page.keys), "laid on the screen"


def test_the_other_models() -> None:
    """SD87: Mini chooses the end and the track, and Begär opens the routes out; Neo has the
    tracks and the requests on pages of their own; on + a dial requests; on XL and + XL the
    yard is drawn with the requests in two columns."""
    y = the_reference()
    mini = profile_of(y, DeckModelId.MINI)
    first = mini.pages[0].keys
    assert first[0] == TklDeckKey(type=K.END) and first[1] is not None and first[1].type == K.STREET
    begar = next(
        k for p in mini.pages for k in p.keys if k and k.type == K.ACTION and k.action == A.REQUESTS
    )
    assert begar.page is not None
    opened = mini.pages[begar.page]
    assert not opened.listed and any(k and k.type == K.REQUEST for k in opened.keys)

    neo = profile_of(y, DeckModelId.NEO)
    tracks = [p for p in neo.pages if any(k and k.type == K.STREET for k in p.keys)]
    outs = [p for p in neo.pages if any(k and k.type == K.REQUEST for k in p.keys)]
    assert tracks and outs and not set(map(id, tracks)) & set(map(id, outs))

    plus = profile_of(y, DeckModelId.PLUS)
    assert not any(k and k.type == K.REQUEST for p in plus.pages for k in p.keys)
    assert plus.dials[DeckMode.YARD][0] == DeckDial.REQUEST

    for model_id in (DeckModelId.XL, DeckModelId.PLUS_XL):
        found = profile_of(y, model_id)
        [page] = found.pages
        grid = found.grid
        width = grid.columns - 1
        column = [[page.keys[r * grid.columns + c] for r in range(grid.rows)] for c in range(width)]
        left = [k for k in column[0] if k]
        right = [k for k in column[width - 1] if k]
        assert all(k.type == K.REQUEST and k.side in (LEFT, None) for k in left)
        assert all(k.type == K.REQUEST and k.side in (RIGHT, None) for k in right)
        assert any(k.side == LEFT for k in left) and any(k.side == RIGHT for k in right)
        assert all(k and k.type == K.STREET and k.side == LEFT for k in column[1])
        right_streets = [k for k in column[width - 2] if k and k.type == K.STREET]
        assert right_streets and all(k.side == RIGHT for k in right_streets)


def test_the_pedal_has_no_shunters_deck() -> None:
    """TKL122."""
    y = made_up()
    found = profile_of(y, DeckModelId.PEDAL)
    assert found.pages == [] and found.modes == [] and found.pedals == [None, None, None]


# --- the keys ---------------------------------------------------------------------------------


def test_ande_chooses_the_end_and_shows_it() -> None:
    """SD86: a press changes between the left and the right end, and the key shows which."""
    y = made_up()
    deck = y.deck()
    end = y.at(deck, K.END)
    assert y.faces(deck)[end].label == "Ände: vänster"
    y.press(deck, end)
    assert deck.end == RIGHT and y.faces(deck)[end].label == "Ände: höger"
    y.press(deck, end)
    assert deck.end == LEFT


def test_a_street_from_each_end() -> None:
    """SD61: a track key lays the switch street from the chosen end, through the
    interlocking's part operation (SD1)."""
    y = made_up()
    deck = y.deck()
    fifty_one = y.at(deck, K.STREET, "51")
    y.press(deck, fifty_one)
    assert y.hands.calls == ["street V51"]
    assert y.faces(deck)[fifty_one].under == "ligger"
    y.press(deck, y.at(deck, K.END))
    fifty_two = y.at(deck, K.STREET, "52")
    assert y.faces(deck)[fifty_two].under == "H 52"
    y.press(deck, fifty_two)
    assert y.hands.calls[-1] == "street H52"
    assert y.it.view().switches["4"].position == MINUS
    assert deck.message is not None and "H 52" in deck.message


def test_a_request_and_the_station_approves() -> None:
    """SD61, RANG-03: a route out is requested, waits blinking, and is green when approved."""
    y = made_up()
    deck = y.deck()
    out = y.at(deck, K.REQUEST, "V")
    assert y.faces(deck)[out].under == "begär"
    y.press(deck, out)
    assert y.hands.calls == ["request Ut"] and shown(y) == ["Ut waiting"]
    face = y.faces(deck)[out]
    assert face.under == "väntar" and face.blink
    [part] = y.it.view().parts
    assert y.it.part_reply(part.requests[0].id, True).accepted
    face = y.faces(deck)[out]
    assert face.under == "godkänd" and face.bg == "#15803d"
    y.press(deck, out)
    assert shown(y) == ["Ut approved"], "a press alone never returns it (RANG-09)"


def test_lamna_then_a_track_returns_that_route() -> None:
    """SD61: with several approved routes, Lämna and then the track returns that one; with one,
    Lämna returns it at once; with none, Lämna says so."""
    y = made_up()
    deck = y.deck()
    give = y.action(deck, A.GIVE_BACK)
    y.press(deck, give)
    assert deck.message == "Ingen godkänd väg att lämna tillbaka." and not deck.giving
    y.press(deck, y.at(deck, K.END))
    y.press(deck, y.at(deck, K.REQUEST, "B"))
    y.press(deck, y.at(deck, K.REQUEST, "B ut"))
    for request in y.it.view().parts[0].requests:
        assert y.it.part_reply(request.id, True).accepted
    assert shown(y) == ["UB approved", "BUt approved"]
    y.press(deck, give)
    assert deck.giving and y.faces(deck)[give].under == "välj spår"
    assert y.faces(deck)[y.at(deck, K.REQUEST, "B ut")].under == "lämna?"
    y.press(deck, y.at(deck, K.REQUEST, "B ut"))
    assert not deck.giving and shown(y) == ["UB approved"]
    assert y.hands.calls[-1].startswith("return")
    y.press(deck, give)
    assert shown(y) == [], "the last one at once"


def test_klart_returns_everything_and_lays_the_gates_back() -> None:
    """RANG-04: Klart returns every request, waiting or approved, and lays the border switch
    back towards the yard."""
    y = made_up()
    deck = y.deck()
    y.press(deck, y.at(deck, K.REQUEST, "V"))
    [part] = y.it.view().parts
    y.it.part_reply(part.requests[0].id, True)
    assert y.it.view().switches["3"].position == PLUS, "the route out lies over 3 +"
    y.press(deck, y.action(deck, A.DONE))
    assert y.hands.calls[-1] == "done" and shown(y) == []
    assert y.it.view().switches["3"].position == MINUS
    assert deck.message is not None and deck.message.startswith("Bangården: klart.")


def test_ring_rings_the_station() -> None:
    """RANG-04, TKL98: Ring rings until the station answers; the key blinks meanwhile."""
    y = made_up()
    deck = y.deck()
    ring = y.action(deck, A.RING)
    y.press(deck, ring)
    assert y.hands.calls == ["ring"] and y.it.view().parts[0].rings is not None
    assert y.faces(deck)[ring].blink and y.faces(deck)[ring].under == "ringer"
    y.it.part_ring_answer(PART)
    assert not y.faces(deck)[ring].blink


def test_the_train_key_press_and_hold() -> None:
    """SD60: the next train from the plan; a hold shows the next one, a press announces it Klart
    att skicka (TKL108), and the key goes on to the next."""
    y = made_up(PLAN)
    deck = y.deck()
    ready = y.at(deck, K.READY)
    face = y.faces(deck)[ready]
    assert (face.top, face.text, face.under) == ("klart att skicka", "9101", "spår 51 · 10:42")
    y.press(deck, ready, hold=True)
    assert y.faces(deck)[ready].text == "9103" and y.hands.calls == []
    y.press(deck, ready)
    assert y.hands.calls == ["ready 9103"]
    assert [(r.number, r.track, r.departure) for r in y.it.view().ready] == [
        ("9103", "52", "11:15")
    ]
    assert y.faces(deck)[ready].text == "9101", "the announced one is not offered again"
    y.press(deck, ready, hold=True)
    y.press(deck, ready, hold=True)
    assert y.faces(deck)[ready].text == "9101", "round the plan"
    empty = made_up([])
    deck = empty.deck()
    assert empty.faces(deck)[empty.at(deck, K.READY)].dim


def test_a_refused_request_shows_the_reason_for_three_seconds() -> None:
    """SD18, RANG-10: a request that cannot go is refused at once with the reason, which stands
    on the key for three seconds; the station's Neka does the same."""
    y = made_up()
    assert y.it.set_route("In", "11", None).accepted
    deck = y.deck()
    out = y.at(deck, K.REQUEST, "V")
    assert y.faces(deck)[out].dim and y.faces(deck)[out].dot, "hindered beforehand (SD17)"
    y.press(deck, out)
    face = y.faces(deck)[out]
    assert face.type == "answer" and face.bg == "#b91c1c" and face.label.startswith("Nej:")
    assert shown(y) == [], "nothing reached the station"
    y.now += 3.5
    assert y.faces(deck)[out].type == "request"

    neka = made_up()
    deck = neka.deck()
    out = neka.at(deck, K.REQUEST, "V")
    neka.press(deck, out)
    neka.faces(deck)
    [part] = neka.it.view().parts
    neka.it.part_reply(part.requests[0].id, False)
    face = neka.faces(deck)[out]
    assert face.type == "answer" and "nekade" in (deck.message or "")
    neka.now += 3.5
    assert neka.faces(deck)[out].under == "begär"


def test_fika_darkens_the_deck_until_the_shunter_is_back() -> None:
    """RANG-04: Fika on the Läge page (a part's deck never locks the whole station); every key
    shows the cup, and a press brings the shunter back."""
    y = made_up()
    deck = y.deck()
    y.press(deck, y.at(deck, K.MODE))
    faces = y.faces(deck)
    fika = next(i for i, f in enumerate(faces) if f.type == "fika")
    assert not any(f.label == "Lås TKL" for f in faces)
    y.press(deck, fika)
    assert y.hands.calls == ["fika True"] and "lock" not in y.hands.calls
    assert all(f.type == "fika" for f in y.faces(deck))
    y.press(deck, 0)
    assert y.hands.calls[-1] == "fika False" and not y.it.view().parts[0].fika


def test_a_part_deck_cannot_reach_the_tagklarerare_pages() -> None:
    """SD74: a deck with a part's role opens in Bangård and offers only the part's modes, even
    when its settings say Tågen or a page of the tågklarerare's."""
    y = made_up()
    deck = y.deck(opens_in=DeckMode.TRAINS, opens_on="Nu")
    assert deck.mode == DeckMode.YARD
    y.press(deck, y.at(deck, K.MODE))
    modes = [f.text for f in y.faces(deck) if f.type == "mode"]
    assert set(modes) == {"Bangård"}
    y.press(deck, y.at(deck, K.MODE))
    y.press(deck, y.at(deck, K.MODE), hold=True)
    tabs = [f.under for f in y.faces(deck) if f.type == "page"]
    assert tabs and set(tabs) == {"Bangård"}
    for model_id in (DeckModelId.MINI, DeckModelId.NEO, DeckModelId.XL):
        other = y.deck(model_id)
        assert {p.mode for p in other.profile.pages} == {DeckMode.YARD}


def test_a_parts_deck_never_does_the_tagklarerares_actions() -> None:
    """SD74: even when the owner gives a key of the shunter's deck Lös ut, it does not release
    the station's routes."""
    y = made_up()
    assert y.it.set_route("In", "11", None).accepted
    found = profile_of(y, DeckModelId.FIFTEEN)
    [page] = found.pages
    ready = next(k for k in page.keys if k is not None and k.type == K.READY)
    changed = TklDeckDeviation(change=DeckChange.KEY, page=ref_of(page), key=ready, press=A.RELEASE)
    known = known_of(y.plant, y.geo, y.part)
    owned = apply(found, [changed], known).profile
    deck = logic.open_deck(
        TklDeckSettings(serial="d", model=DeckModelId.FIFTEEN, grid=found.grid, role=y.part),
        owned,
        y.world(),
    )
    y.press(deck, y.at(deck, K.READY))
    assert deck.message == logic.NOT_THE_PARTS
    assert [r.start for r in y.it.view().routes] == ["In"], "the station's route stays"


def test_mini_opens_the_routes_out_and_lamna_goes_there() -> None:
    """SD87: on Mini, Begär opens the routes out; ▶ there goes back; with two approved routes
    Lämna opens them for the choice."""
    y = made_up()
    deck = y.deck(DeckModelId.MINI)
    more = next(i for i, p in enumerate(deck.profile.pages) if p.name == "Mer")
    deck.page = more
    y.press(deck, y.action(deck, A.REQUESTS))
    page = logic.current(deck)
    assert page is not None and not page.listed and page.name == "Begäran"
    y.press(deck, y.at(deck, K.REQUEST, "V"))
    assert shown(y) == ["Ut waiting"]
    y.press(deck, 5)
    assert deck.page == more, "▶ goes back to Begär's page"


def test_plus_requests_with_the_dial() -> None:
    """SD87: on + the first dial chooses the route out and a press requests it."""
    y = made_up()
    deck = y.deck(DeckModelId.PLUS)
    world = y.world()
    strip = logic.view(deck, y.selection, world).strip
    assert strip[0].label == "Begär" and strip[0].value == "V Ut"
    logic.dial(deck, y.selection, y.world(), y.hands, 0, 1)
    assert logic.view(deck, y.selection, y.world()).strip[0].value == "B ut"
    logic.dial(deck, y.selection, y.world(), y.hands, 0, 0, pushed=True)
    assert shown(y) == ["BUt waiting"]


def test_the_shunters_kor_runs_only_the_parts_own_route_outside_drift() -> None:
    """RANG-04, SD28: Kör on the 32-key deck steps the part's latest route with a train."""
    y = made_up()
    deck = y.deck(DeckModelId.XL)
    kor = y.action(deck, A.RUN)
    assert y.faces(deck)[kor].dim
    y.press(deck, kor)
    assert deck.message == "Ingen väg med tåg att köra."


# --- Studio and Prova --------------------------------------------------------------------------


def test_the_sd44_check_covers_the_streets_and_routes_out() -> None:
    """SD44 for the shunter's deck: a route out or a track taken off the deck is a problem."""
    y = made_up()
    found = profile_of(y, DeckModelId.FIFTEEN)
    [page] = found.pages
    known = known_of(y.plant, y.geo, y.part)
    out = next(k for k in page.keys if k and k.type == K.REQUEST and k.track == "V")
    gone = [TklDeckDeviation(change=DeckChange.REMOVE, page=ref_of(page), key=out)]
    applied = apply(found, gone, known)
    checked = yard_check(applied.profile, y.plant, known)
    texts = [p.text for p in checked.problems]
    assert any("V Ut" in t for t in texts) and any("H Ut" in t for t in texts)
    assert checked.reached == checked.routes - 2
    mini = profile_of(y, DeckModelId.MINI)
    tracks = mini.pages[0]
    end = TklDeckKey(type=K.END)
    gone_end = [TklDeckDeviation(change=DeckChange.REMOVE, page=ref_of(tracks), key=end)]
    lost = yard_check(apply(mini, gone_end, known).profile, y.plant, known).problems
    assert {p.text.split(" till ")[0] for p in lost if "Växelgatan" in p.text} == {
        "Växelgatan H 51",
        "Växelgatan H 52",
    }, "without Ände a key that follows the end reaches only the left end"
    assert any("H B" in p.text for p in lost)
    missing = TklDeckKey(type=K.STREET, track="99")
    added = apply(
        found,
        [TklDeckDeviation(change=DeckChange.ADD, page=ref_of(page), key=missing, cell=9)],
        known,
    )
    assert added.to_check and "ingen växelgata" in added.to_check[0].text
    signal = TklDeckKey(type=K.SIGNAL, point="U1")
    wrong = apply(
        found,
        [TklDeckDeviation(change=DeckChange.ADD, page=ref_of(page), key=signal, cell=9)],
        known,
    )
    assert wrong.to_check and wrong.to_check[0].text == "Bangård har bara rangerarens knappar."


def test_prova_alla_knappar_on_bangard() -> None:
    """SD47: every key of the shunter's deck pressed on an empty interlocking, through the part's
    operations; the live one is never touched."""
    y = made_up()
    plant = y.plant
    found = profile_of(y, DeckModelId.FIFTEEN)
    geo = y.geo
    tried = {p.cell: try_key(found, p, plant, geo) for p in keys_of(found)}
    page = found.pages[0]
    by = {i: k for i, k in enumerate(page.keys) if k is not None}
    for cell, key in by.items():
        result = tried[cell]
        if key.type in (K.STREET, K.END) or key.action in (A.DONE, A.RING):
            assert result.result == DeckTried.DID, (key, result)
    out = next(c for c, k in by.items() if k.type == K.REQUEST and k.track == "V")
    assert tried[out].result == DeckTried.DID and "begär" in tried[out].said
    right = next(c for c, k in by.items() if k.type == K.REQUEST and k.track == "B")
    assert tried[right].result == DeckTried.DID, "tried from the right end, where B has its route"
    give = next(c for c, k in by.items() if k.action == A.GIVE_BACK)
    assert tried[give].result == DeckTried.NOTHING
    assert y.it.view().parts[0].requests == [], "the live interlocking is untouched"


# --- the renderer -----------------------------------------------------------------------------


@pytest.mark.parametrize("size", render.SIZES)
def test_the_renderer_draws_the_new_keys(size: int) -> None:
    """The shunter's keys over USB and WebHID (RANG-15): drawn with the locked look, and Fika
    with its cup."""
    y = made_up(PLAN)
    deck = y.deck(DeckModelId.XL)
    faces = [f for f in y.faces(deck) if f.type != "empty"]
    assert {"street", "request", "train", "action", "clock"} <= {f.type for f in faces}
    end = yard.action_face(deck, y.world(), A.GIVE_BACK)
    for face in [*faces, end, yard.fika_key(), yard.fika_faces(1)[0]]:
        image = render.key(face, size)
        assert image.size == (size, size)
        colours = image.getcolors(size * size) or []
        assert len(colours) > 2, face.label
        assert image.getpixel((1, 1)) == render.rgb(face.bg) or face.frame, face.label
    cup = render.key(yard.fika_key(), size)
    plain = TklDeckFace(type="action", text="Fika", under="ta paus", bg="#1c1917", fg="#fef3c7")
    assert _differs(cup, render.key(plain, size)), "the cup is drawn"
    ande = yard.face(deck, y.world(), TklDeckKey(type=K.END))
    assert ande.type == "end" and "Ände" in ande.label
    assert len(render.key(ande, size).getcolors(size * size) or []) > 2


def _differs(a: Image.Image, b: Image.Image) -> bool:
    return a.tobytes() != b.tobytes()


def test_no_code_names_the_part() -> None:
    """RS13: the shunter's deck is made from the part's data."""
    model, part = reference()
    code = Path(__file__).resolve().parents[1] / "deck"
    names = {part, model.parts[0].name, *(s.track for s in model.parts[0].streets)}
    for file in code.glob("*.py"):
        text = file.read_text("utf-8")
        for name in names:
            assert f'"{name}"' not in text, (file.name, name)
