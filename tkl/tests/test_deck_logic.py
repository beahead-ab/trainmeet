"""Stream Deck's logic (#86 del a): presses, holds, dials and touches that call the
interlocking's own functions, and what every key shows from its state (SD1, SD17–SD21).

A made-up station (tkl.tests.provstation.provby): line V in the west and O in the east, tracks 1
and 2. Nothing here names a real station (RS13).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts import station
from contracts.common import Side
from contracts.meet import ClearanceMode, TrackKind
from contracts.station_model import StationModel
from contracts.tkl import (
    DeckAction,
    DeckHold,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckPan,
    RouteKind,
    TklDeckFace,
    TklDeckKey,
    TklDeckRoute,
    TklDeckSettings,
)
from tkl import track_plan
from tkl.deck import logic, look
from tkl.deck.logic import Deck, Holds, Said, Selection, World
from tkl.deck.models import model_of
from tkl.deck.profile import build, geography_of
from tkl.deck.trains import Step, Turn, turns
from tkl.stallverk import Interlocking, plant_of
from tkl.standard import RouteKind as EngineKind
from tkl.tests.niva3 import Rig, level_3
from tkl.tests.provstation import provby

PLACE = "prv"
CONTEXT = station.MeetContext(meet_id="m1", version=1, game_day=1, epoch=0)


def model() -> StationModel:
    found = provby()
    exits = [e.model_copy(update={"outside_id": e.id.lower()}) for e in found.line_exits]
    return found.model_copy(update={"line_exits": exits})


@dataclass
class Hands:
    """The interlocking's own functions, and TKL's clearance as station commands, recorded."""

    it: Interlocking
    commands: list[tuple[station.Action, dict[str, object]]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def said(self, outcome: object) -> Said:
        return Said(outcome.accepted, outcome.message)  # type: ignore[attr-defined]

    def set_route(self, start: str, end: str, kind: RouteKind | None) -> Said:
        self.calls.append(f"route {start} {end}")
        wanted = EngineKind(kind.value) if kind is not None else None
        return self.said(self.it.set_route(start, end, wanted))

    def release(self, route: int) -> Said:
        self.calls.append(f"release {route}")
        return self.said(self.it.release(route))

    def step(self, route: int) -> Said:
        self.calls.append(f"step {route}")
        return self.said(self.it.step(route))

    def arrive(self, route: int) -> Said:
        self.calls.append(f"arrive {route}")
        return self.said(self.it.arrive(route))

    def function(self, name: str, on: bool) -> Said:
        self.calls.append(f"function {name}")
        return Said(False, "Ingen funktion.")

    def command(
        self, action: station.Action, payload: dict[str, object], revision: station.Revision | None
    ) -> Said:
        self.commands.append((action, payload))
        return Said(True, "Skickat.")

    def lock(self) -> Said:
        self.calls.append("lock")
        return Said(True, "TKL är låst.")

    def reset(self) -> Said:
        self.calls.append("reset")
        return self.said(self.it.reset(True))

    def emergency(self, route: int) -> Said:
        self.calls.append(f"emergency {route}")
        return self.said(self.it.emergency_release(route, True))


@dataclass
class Station:
    model: StationModel
    it: Interlocking
    hands: Hands
    selection: Selection = field(default_factory=Selection)
    snapshot: station.Snapshot | None = None
    drift: bool = False
    locked: bool = False
    now: float = 100.0

    @property
    def plant(self):  # type: ignore[no-untyped-def]
        return self.it.plant

    def world(self, *, contact: bool = True) -> World:
        panel = track_plan.panel_of(self.model)
        return World(
            plant=self.plant,
            geo=geography_of(self.plant, panel),
            interlocking=self.it if contact else None,
            snapshot=self.snapshot,
            drift=self.drift,
            locked=self.locked,
            time="06:10",
            station="Provby",
            now=self.now,
        )

    def deck(self, model_id: DeckModelId = DeckModelId.FIFTEEN, **settings: object) -> Deck:
        grid = model_of(model_id).grid
        made = build(self.plant, track_plan.panel_of(self.model), grid, model_id)
        given = TklDeckSettings(serial=f"d-{model_id.value}", model=model_id, grid=grid)
        given = given.model_copy(update=settings)
        return logic.open_deck(given, made, self.world())

    def faces(self, deck: Deck, *, contact: bool = True) -> list[TklDeckFace]:
        return logic.view(deck, self.selection, self.world(contact=contact)).keys

    def press(self, deck: Deck, key: int, hold: bool = False) -> None:
        logic.press(deck, self.selection, self.world(), self.hands, key, hold)

    def index(self, deck: Deck, label: str) -> int:
        found = [i for i, f in enumerate(self.faces(deck)) if f.label == label]
        assert found, (label, [f.label for f in self.faces(deck)])
        return found[0]


def provbanan(model_given: StationModel | None = None, it: Interlocking | None = None) -> Station:
    made = model_given or model()
    found = it or Interlocking(plant_of(made))
    return Station(made, found, Hands(found))


def section(name: str, other: str, side: Side, exit_id: str) -> station.SectionHere:
    return station.SectionHere(
        section=name,
        other_place=other,
        other_code=other.capitalize(),
        tracks=TrackKind.SINGLE,
        clearance_mode=ClearanceMode.REQUESTED,
        side=side,
        exit=exit_id,
    )


def snapshot(
    *,
    arrived: bool = False,
    cleared: bool = False,
    asks: bool = False,
    calls: list[station.CallHere] | None = None,
) -> station.Snapshot:
    """Train 41 on its way here from the east to track 2, and on to the west."""
    call = station.CallHere(
        call="c41",
        train="t41",
        train_number="41",
        train_type="Pt",
        from_place="ost",
        to_place="vby",
        planned_track="2",
        arrival="06:14",
        departure="06:16",
        arrival_state=station.ArrivalState.ARRIVED if arrived else station.ArrivalState.NONE,
        revision=3,
        allowed_actions=[station.Action.CLEARANCE_REQUEST] if arrived else [],
    )
    coming = station.TrainOnSection(
        call="c41",
        train_number="41",
        section="s-ost",
        other_place="ost",
        planned_track="2",
        departed_at="06:00",
    )
    clearances = []
    if cleared:
        clearances.append(
            station.Clearance(
                clearance_id="k41",
                call="c41",
                train_number="41",
                section="s-vast",
                from_place=PLACE,
                to_place="vby",
                status=station.ClearanceStatus.APPROVED,
                requested_at="06:15",
                revision=2,
            )
        )
    if asks:
        clearances.append(
            station.Clearance(
                clearance_id="k44",
                call="c44",
                train_number="44",
                section="s-vast",
                from_place="vby",
                to_place=PLACE,
                status=station.ClearanceStatus.WAITING,
                requested_at="06:12",
                revision=1,
            )
        )
    return station.Snapshot(
        place=station.Neighbour(place=PLACE, code="Pr", name="Provby"),
        context=CONTEXT,
        clock=station.Clock(time="06:10", seconds=22200, running=True, speed=4, game_day=1),
        place_revision=7,
        sections=[
            section("s-vast", "vby", Side.LEFT, "v"),
            section("s-ost", "ost", Side.RIGHT, "o"),
        ],
        calls=calls if calls is not None else [call],
        on_the_way=[] if arrived else [coming],
        clearances=clearances,
        neighbours=[
            station.Neighbour(place="vby", code="Vby", name="Västby"),
            station.Neighbour(place="ost", code="Öst", name="Östby"),
        ],
    )


def turn_of(s: Station, number: str) -> Turn:
    world = s.world()
    return next(t for t in world.turns if t.number == number)


# --- the train key (SD7–SD10) ---------------------------------------------------------------


def test_the_train_key_lays_the_entry_asks_for_clearance_and_lays_the_exit() -> None:
    """SD8, SD10 at levels 1–2: lägg infart, Kör, Ankommit, begär klart, lägg utfart. A press
    per step; hold releases a set route (SD9: nothing without a press).

    Ported: cda-tkl test/stream-deck.test.mjs, "the departure key walks the TMBox sequence for
    the next train ... and follows the line once requested", with the steps of TKL57."""
    s = provbanan()
    s.snapshot = snapshot()
    s.it.put_train("41", exit="O")
    deck = s.deck()
    assert deck.mode == DeckMode.TRAINS, "Nu first with Hubben (SD22)"
    first = s.faces(deck)[0]
    assert (first.text, first.under, first.type) == ("41", "väntar · lägg infart", "train")
    assert first.top == "O → 2", "from its exit to its planned track (SD7)"
    assert s.it.view().routes == [], "nothing without a press (SD9)"

    s.press(deck, 0)
    [entry] = s.it.view().routes
    assert entry.enters == "O" and entry.train is not None
    assert s.faces(deck)[0].under == "infart lagd"
    s.press(deck, 0, hold=True)
    assert s.it.view().routes == [], "hold releases the entry"
    s.press(deck, 0)
    for _ in range(8):
        if turn_of(s, "41").step == Step.ARRIVE:
            break
        s.press(deck, 0)  # Kör, outside a real meet (SD28)
    assert turn_of(s, "41").step == Step.ARRIVE
    assert s.faces(deck)[0].under == "ankommit?"
    s.press(deck, 0)
    assert s.it.view().routes == [], "Ankommit releases the entry route"

    assert turn_of(s, "41").step == Step.IN
    assert s.faces(deck)[0].under == "begär klart"
    s.snapshot = snapshot(arrived=True)
    s.press(deck, 0)
    [(action, payload)] = s.hands.commands
    assert action == station.Action.CLEARANCE_REQUEST
    assert (payload["call"], payload["section"]) == ("c41", "s-vast"), "TKL's clearance (SD14)"

    s.snapshot = snapshot(arrived=True, cleared=True)
    face = s.faces(deck)[0]
    assert (face.under, face.dashed, face.blink is not None) == ("klart · lägg ut", True, True)
    s.press(deck, 0)
    [out] = s.it.view().routes
    assert out.leaves == "V", "the exit towards the next station"
    assert turn_of(s, "41").step == Step.EXIT


def test_hold_on_the_train_key_chooses_another_track_with_a_star_on_the_planned() -> None:
    """SD8, SD20: the goals light, the planned track with a star; an occupied one is dimmed."""
    s = provbanan()
    s.snapshot = snapshot()
    s.it.put_train("41", exit="O")
    s.it.put_train("38", section="Spår 1")
    deck = s.deck()
    key = next(i for i, f in enumerate(s.faces(deck)) if f.type == "train" and f.text == "41")
    s.press(deck, key, hold=True)
    faces = s.faces(deck)
    planned = next(f for f in faces if f.text == "2")
    assert planned.star and planned.under == "planerat" and not planned.dim
    occupied = next(f for f in faces if f.text == "1")
    assert occupied.dim and occupied.dot is not None, "occupied: dimmed with a red dot"
    assert faces[-1].text == "Avbryt" and faces[-1].under == "41 från O"
    s.press(deck, faces.index(planned))
    [route] = s.it.view().routes
    assert route.enters == "O"
    assert deck.overlay is None and not s.selection.chosen


def test_at_level_3_the_arrival_is_the_entry_released_after_passage() -> None:
    """SD10: at level 3 with LocoNet the train stands on its track when the entry route has
    released itself behind it; there is no Ankommit step."""
    rig = Rig(level_3(model()))
    rig.connect()
    s = provbanan(rig.model, rig.it)
    s.snapshot = snapshot()
    rig.it.put_train("41", exit="O")
    deck = s.deck()
    s.press(deck, 0)
    rig.send(rig.it.take_orders())
    rig.run(0.5)
    [entry] = rig.it.view().routes
    assert entry.enters == "O"
    rig.layout.put_train("41", ["Infart O"])
    rig.layout.move_train("41", "Vx2")
    rig.run(0.1)
    rig.layout.move_train("41", "Spår 2")
    rig.run(0.1)
    rig.layout.move_train("41", "Spår 2", length=1)
    rig.run(0.1)
    assert rig.it.view().routes == [], "released after passage"
    assert turn_of(s, "41").step == Step.IN, "no Ankommit at level 3"
    assert s.faces(deck)[0].under == "begär klart"


def test_the_turn_is_the_order_of_what_happens_next() -> None:
    """Ported: cda-tkl test/stream-deck-turns.test.mjs, "the turn is the timetable order of
    every train still due, and a train leaves it when done", and "the actual track wins over
    the planned one"."""
    s = provbanan()

    def call(n: str, arrival: str, **more: object) -> station.CallHere:
        return station.CallHere(
            call=f"c{n}",
            train=f"t{n}",
            train_number=n,
            from_place="ost",
            to_place="vby",
            planned_track="1",
            arrival=arrival,
            revision=1,
            **more,  # type: ignore[arg-type]
        )

    calls = [
        call("53", "07:10"),
        call("51", "06:50", track="2"),
        call("55", "06:40", departure_state=station.DepartureState.DEPARTED),
    ]
    s.snapshot = snapshot(calls=calls).model_copy(update={"on_the_way": []})
    world = s.world()
    found = turns(world.state, s.snapshot, world.plant, world.geo)
    assert [t.number for t in found] == ["51", "53"], "in time order, the departed one gone"
    assert found[0].track == "2" and found[0].planned == "1", "the actual track wins"


# --- what a key shows (SD17–SD21) ------------------------------------------------------------


def test_a_refused_route_shows_the_reason_for_three_seconds() -> None:
    """SD17, SD18: a goal that cannot be set is dimmed with a mark and the reason; pressed
    anyway, the interlocking's no stands on the key for three seconds."""
    s = provbanan()
    s.it.put_train("38", section="Spår 2")
    deck = s.deck()
    assert deck.mode == DeckMode.PLACES, "without Hubben, Platser (SD11)"
    o = s.index(deck, "Plats O")
    s.press(deck, o)
    faces = s.faces(deck)
    two = next(i for i, f in enumerate(faces) if f.text == "2")
    assert faces[two].dim and faces[two].dot and faces[two].under == "belagt · tåg 38"
    s.press(deck, two)
    refused = s.faces(deck)[two]
    assert refused.type == "answer" and refused.bg == "#b91c1c"
    assert refused.under == "belagt · tåg 38"
    assert deck.message and "belagd" in deck.message, "the interlocking's own reason"
    s.now += 2.9
    assert s.faces(deck)[two].type == "answer"
    s.now += 0.2
    assert s.faces(deck)[two].type != "answer", "gone after three seconds"


def test_ingen_kontakt_never_shows_an_old_state() -> None:
    """SD21: when the interlocking does not answer every key says Ingen kontakt, and a press
    does nothing."""
    s = provbanan()
    deck = s.deck()
    faces = s.faces(deck, contact=False)
    assert {f.label for f in faces} == {"Ingen kontakt"}
    logic.press(deck, s.selection, s.world(contact=False), s.hands, 0)
    assert s.hands.calls == []


def test_the_lock_shows_only_the_clock() -> None:
    """SD30: when TKL is locked the deck shows only the clock, and does nothing."""
    s = provbanan()
    deck = s.deck(DeckModelId.XL)
    s.locked = True
    faces = s.faces(deck)
    shown = [(i, f.text) for i, f in enumerate(faces) if f.text]
    assert shown == [(7, "06:10")], "the clock where Larm och klocka is"
    s.press(deck, 0)
    assert s.hands.calls == [] and not s.selection.chosen


def test_a_hold_is_six_tenths_of_a_second() -> None:
    """SD29: a key held 0.6 seconds is a hold, once, while it is still down; a shorter one is a
    press. The deck's hold time is Kort, Normal or Lång."""
    holds = Holds()
    holds.pressed(3, 10.0)
    assert holds.released(3, 10.5) == "press"
    holds.pressed(3, 20.0)
    assert holds.tick(20.59) == []
    assert holds.tick(20.6) == [3]
    assert holds.tick(21.0) == [], "once"
    assert holds.released(3, 21.2) is None, "already a hold"
    holds.pressed(4, 30.0)
    assert holds.released(4, 30.7) == "hold"
    assert logic.HOLD_MS[DeckHold.NORMAL] == 600
    s = provbanan()
    deck = s.deck(hold=DeckHold.SHORT)
    assert logic.view(deck, s.selection, s.world()).hold_ms == 400


def test_kor_only_outside_a_real_meet() -> None:
    """SD28, TKL60: Kör in Prova and without a meet; in drift Ankommit stands there."""
    s = provbanan()
    deck = s.deck()
    arrived = s.faces(deck)[10]
    assert arrived.text == "Kör"
    s.drift = True
    assert s.faces(deck)[10].text == "Ankommit"


# --- Nu, the line key and the alarm (SD13, SD15, SD22) -------------------------------------


def test_the_neighbours_question_is_never_answered_with_a_single_press() -> None:
    """SD13, SD15, TKL58: the line key blinks while the neighbour asks; a press opens the
    question with Klart and Nej as keys of their own. The alarm key shows it too.

    Ported: cda-tkl test/stream-deck.test.mjs, "the arrival key answers requests": a request
    blinks, and accepting it is the deck's own press; here a second one (TKL58)."""
    s = provbanan()
    s.snapshot = snapshot(asks=True)
    deck = s.deck()
    faces = s.faces(deck)
    line = next(i for i, f in enumerate(faces) if f.type == "line" and f.text == "Vby")
    assert faces[line].under == "frågar: 44" and faces[line].blink
    alarm = next(f for f in faces if f.type == "alarm")
    assert alarm.under == "frågar: 44"
    s.press(deck, line)
    assert s.hands.commands == []
    faces = s.faces(deck)
    assert [faces[1].text, faces[2].text, faces[-1].text] == ["Klart", "Nej", "Tillbaka"]
    s.press(deck, 1)
    [(action, payload)] = s.hands.commands
    assert action == station.Action.CLEARANCE_RESPONSE
    assert payload == {"clearance_id": "k44", "approved": True}


def test_without_hubben_there_are_no_train_keys() -> None:
    """SD11, SD63: without Hubben Tågen is not there, and the deck opens on Platser."""
    s = provbanan()
    deck = s.deck()
    assert logic.modes(deck, s.world()) == [DeckMode.PLACES, DeckMode.TRACK_PLAN]
    assert deck.mode == DeckMode.PLACES
    assert not any(f.type == "train" for f in s.faces(deck))


# --- Läge and the pages (SD26, SD64, SD78) ------------------------------------------------


def test_lage_chooses_the_mode_and_holding_it_shows_every_page() -> None:
    """SD64, SD26: a press shows the modes with each one's variant under; hold shows every
    page, the first page first."""
    s = provbanan()
    s.snapshot = snapshot()
    deck = s.deck()
    s.press(deck, 14)
    faces = s.faces(deck)
    assert [f.text for f in faces[:3]] == ["Tågen", "Platser", "Spårplan"]
    assert (faces[6].top, faces[6].text) == ("Platser visar", "Alla"), "the variant under (SD68)"
    assert (faces[7].top, faces[7].text) == ("Ritas som", "85"), "SD72"
    s.press(deck, 6)
    assert s.faces(deck)[6].text == "Valbara"
    s.press(deck, 2)
    assert deck.mode == DeckMode.TRACK_PLAN and deck.overlay is None
    s.press(deck, 14, hold=True)
    faces = s.faces(deck)
    assert faces[0].text == "Nu" and faces[-1].text == "Tillbaka"
    s.press(deck, 0)
    page = logic.current(deck)
    assert page is not None and page.name == "Nu" and page.mode == DeckMode.TRAINS


def test_on_mini_holding_the_arrow_opens_lage() -> None:
    """SD78: on Mini holding ▶ opens the page Läge, with the modes, Sidor and Tillbaka."""
    s = provbanan()
    s.snapshot = snapshot()
    deck = s.deck(DeckModelId.MINI)
    s.press(deck, 5, hold=True)
    faces = s.faces(deck)
    assert [faces[0].text, faces[1].text, faces[4].text, faces[5].text] == [
        "Tågen",
        "Platser",
        "Sidor",
        "Tillbaka",
    ]
    s.press(deck, 4)
    assert s.faces(deck)[0].text == "Nu", "Sidor shows every page (SD26)"


# --- Platser (SD66–SD68, SD79, SD80) -------------------------------------------------------


def test_platser_lights_the_goals_and_sets_the_route_through_the_signals_between() -> None:
    """SD67: a press on the start lights the goals, a press on a goal sets the route.

    Ported: cda-tkl test/stream-deck.test.mjs, "plupp appearance mirrors the track plan
    classes": the chosen start has its ring, the goals theirs, and a route set is green."""
    s = provbanan()
    deck = s.deck(DeckModelId.XL)
    s.press(deck, s.index(deck, "Plats O"))
    faces = s.faces(deck)
    goals = {f.text for f in faces if f.type == "goal"}
    assert goals == {"1", "2", "V"}, "the tracks, and V through the station (TKL53)"
    two = next(i for i, f in enumerate(faces) if f.text == "2")
    s.press(deck, two)
    [route] = s.it.view().routes
    assert route.enters == "O" and not s.selection.chosen


def test_platser_valbara_darkens_what_cannot_be_chosen() -> None:
    """SD68: Bara valbara: with a start chosen, the rest is dark."""
    s = provbanan()
    s.it.put_train("38", section="Spår 2")
    deck = s.deck(DeckModelId.XL, places_shown="valbara")
    s.press(deck, s.index(deck, "Plats O"))
    texts = {f.text for f in s.faces(deck) if f.type in ("place", "goal")}
    assert "2" not in texts and "1" in texts


def test_small_decks_count_the_goals_in_each_part() -> None:
    """SD79: after the start, each part says how many goals it has."""
    s = provbanan()
    deck = s.deck(DeckModelId.MINI)
    parts = s.faces(deck)
    east = next(i for i, f in enumerate(parts) if f.type == "part" and f.text == "Öster")
    s.press(deck, east)
    s.press(deck, s.index(deck, "Plats O"))
    s.press(deck, next(i for i, f in enumerate(s.faces(deck)) if f.text == "Tillbaka"))
    counted = {f.text: f.under for f in s.faces(deck) if f.type == "part"}
    assert counted["Öster"] == "start O"
    assert any(u.endswith("mål") for u in counted.values())


def test_signal_numbers_are_a_setting_per_deck() -> None:
    """SD69: off from the start; on, the place shows its signals in small text."""
    s = provbanan()
    plain = s.deck(DeckModelId.XL)
    assert not any(f.small for f in s.faces(plain))
    numbered = s.deck(DeckModelId.XL, signal_numbers=True)
    assert any(f.small for f in s.faces(numbered) if f.type == "place")


# --- shared start, Spårplan, Dagens vägar and Favoriter -------------------------------------


def test_decks_at_the_same_workplace_share_the_start() -> None:
    """SD36: a start pressed on one deck lights the goals on the other."""
    s = provbanan()
    left, right = s.deck(DeckModelId.FIFTEEN), s.deck(DeckModelId.XL)
    s.press(left, s.index(left, "Plats O"))
    goals = {f.text: i for i, f in enumerate(s.faces(right)) if f.type == "goal"}
    assert "2" in goals
    s.press(right, goals["2"])
    assert len(s.it.view().routes) == 1 and not s.selection.chosen


def test_sparplan_whole_and_cut_out() -> None:
    """SD70, SD71, SD81: Hela stationen cut in a piece per key; a press opens the cut-out
    there, where the pan keys move it and a signal is pressed as in the panel."""
    s = provbanan()
    deck = s.deck(DeckModelId.FIFTEEN)
    logic.go_mode(deck, s.world(), DeckMode.TRACK_PLAN)
    faces = s.faces(deck)
    assert all(f.type == "tile" and f.tile is not None for f in faces[:10])
    s.press(deck, 0)
    page = logic.current(deck)
    assert page is not None and page.kind == DeckPageKind.CUTOUT
    faces = s.faces(deck)
    assert [f.label for f in faces[10:14]] == ["Hela stationen", "Väster", "Öster", "Nedåt"]
    before = deck.origin
    logic._pan(deck, DeckPan.EAST)
    assert deck.origin[0] >= before[0]
    deck.origin = (0, 0)
    for _ in range(12):
        cells = [
            i
            for i, f in enumerate(s.faces(deck))
            if f.type == "cell" and "In" in f.tile.names  # type: ignore[union-attr]
        ]
        if cells:
            break
        logic._pan(deck, DeckPan.DOWN)
    assert cells, "the entry signal In is in a square"
    s.press(deck, cells[0])
    assert s.selection.point == "In"
    lit = [f for f in s.faces(deck) if f.type == "cell" and f.tile and f.tile.goals]
    assert lit or s.world().targets("In") is not None


def test_dagens_vagar_from_the_snapshot() -> None:
    """SD23: the entry and the exit of every train on its planned track, from the meet's
    timetable in the snapshot."""
    s = provbanan()
    s.snapshot = snapshot()
    world = s.world()
    [entry, exit_] = world.daily
    assert (entry.origin, entry.goal, entry.number, entry.entry) == ("O", "2", "41", True)
    assert (exit_.origin, exit_.goal, exit_.entry) == ("2", "V", False)
    deck = s.deck()
    logic.press(deck, s.selection, world, s.hands, 14, hold=True)
    pages = [f.text for f in s.faces(deck)]
    assert "Dagens vägar" in pages
    deck.overlay = None
    deck.page = next(i for i, p in enumerate(deck.profile.pages) if p.kind == DeckPageKind.DAILY)
    face = s.faces(deck)[0]
    assert (face.text, face.under) == ("O→2", "41 · 06:14")
    s.press(deck, 0)
    [route] = s.it.view().routes
    assert route.enters == "O"


def test_favoriter_are_the_pinned_routes_then_the_most_used() -> None:
    """SD24, SD48, TKL70: pinned first, then those set at least twice, the most used first;
    only routes that still exist."""
    pinned = [TklDeckRoute(start="In", end="12", kind=RouteKind.TRAIN)]
    counted = {
        ("In", "12", RouteKind.TRAIN): 5,
        ("Ut2", "Ut", RouteKind.TRAIN): 2,
        ("In2", "22", RouteKind.TRAIN): 3,
        ("Gone", "X", RouteKind.TRAIN): 9,
        ("In", "22", RouteKind.TRAIN): 1,
    }
    shown = logic.favourites(pinned, counted, lambda r: r.start != "Gone")
    assert [(r.start, r.end) for r in shown] == [("In", "12"), ("In2", "22"), ("Ut2", "Ut")]


def test_las_on_the_page_lage_locks_tkl() -> None:
    """SD30: Lås (Fika) stands on the last free key of the page Läge on every deck, and a
    press asks TKL to lock itself; the default pages stay as they are."""
    for model_id in (DeckModelId.MINI, DeckModelId.FIFTEEN, DeckModelId.XL, DeckModelId.PLUS):
        s = provbanan()
        s.snapshot = snapshot()
        deck = s.deck(model_id)
        assert "Lås TKL" not in [f.label for f in s.faces(deck)], "not on the pages"
        mini = model_id == DeckModelId.MINI
        lage = next(
            i
            for i, f in enumerate(s.faces(deck))
            if f.label.startswith("Nästa sida" if mini else "Läge")
        )
        s.press(deck, lage, hold=mini)
        faces = s.faces(deck)
        at = s.index(deck, "Lås TKL")
        assert all(f.type != "empty" for f in faces[at + 1 :]), "the last free key"
        assert (faces[at].text, faces[at].under) == ("Lås", "fika")
        assert "lock" not in s.hands.calls
        s.press(deck, at)
        assert s.hands.calls == ["lock"], model_id
        assert deck.overlay is None and deck.accepted is True


def test_las_as_a_key_of_its_own_locks_tkl() -> None:
    """SD4, SD30: Lås is in the catalogue, so a profile may put it on a page (Studio, #86 del c)."""
    s = provbanan()
    deck = s.deck(DeckModelId.FIFTEEN)
    page = logic.current(deck)
    assert page is not None
    keys = list(page.keys)
    keys[9] = TklDeckKey(type=DeckKeyType.ACTION, action=DeckAction.LOCK)
    pages = list(deck.profile.pages)
    pages[deck.page] = page.model_copy(update={"keys": keys})
    deck.profile = deck.profile.model_copy(update={"pages": pages})
    assert s.faces(deck)[9] == look.LOCK
    s.press(deck, 9)
    assert s.hands.calls == ["lock"]
