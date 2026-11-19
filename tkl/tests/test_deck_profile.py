"""Stream Deck's profiles (#86 del a): computed from the station model for every Elgato model's
grid (SD31, SD32, SD39, SD52–SD54), as data (SD5), with the modes each model has (SD76) and Läge
where it sits (SD77, SD78).

The four reference stations are looped over without naming one (RS13): what a test needs is
read from the station's own data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.station_model import StationModel
from contracts.tkl import (
    DeckDial,
    DeckKeyType,
    DeckMode,
    DeckModelId,
    DeckPageKind,
    DeckStyle,
    Panel,
    TklDeckGrid,
    TklDeckKey,
    TklDeckProfile,
)
from tkl import track_plan
from tkl.deck.models import MODELS, model_of, size_of
from tkl.deck.places import compressed
from tkl.deck.profile import build, frame, geography_of
from tkl.stallverk import Interlocking, Plant, plant_of
from tkl.standard import RouteKind

FILES = Path(__file__).resolve().parents[2] / "tkl" / "referens"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in FILES.glob("*.tkl.json"))
K = DeckKeyType


def station(name: str) -> tuple[StationModel, Plant, Panel | None]:
    model = StationModel.model_validate_json((FILES / f"{name}.tkl.json").read_text("utf-8"))
    return model, plant_of(model), track_plan.panel_of(model)


def profile(name: str, model_id: DeckModelId) -> TklDeckProfile:
    _, plant, panel = station(name)
    return build(plant, panel, model_of(model_id).grid, model_id)


def keys(page_keys: list[TklDeckKey | None], kind: DeckKeyType) -> list[int]:
    return [i for i, k in enumerate(page_keys) if k is not None and k.type == kind]


def test_every_model_is_there_with_its_grid() -> None:
    """SD52: Elgato's eleven decks, with the grids the library reads (the modeller's table)."""
    grids = {m.id: (m.grid.columns, m.grid.rows) for m in MODELS}
    assert grids == {
        DeckModelId.MINI: (3, 2),
        DeckModelId.NEO: (4, 2),
        DeckModelId.FIFTEEN: (5, 3),
        DeckModelId.XL: (8, 4),
        DeckModelId.PLUS: (4, 2),
        DeckModelId.PLUS_XL: (9, 4),
        DeckModelId.PEDAL: (0, 0),
        DeckModelId.MODULE_6: (3, 2),
        DeckModelId.MODULE_15: (5, 3),
        DeckModelId.MODULE_32: (8, 4),
        DeckModelId.STUDIO: (16, 2),
    }
    assert model_of(DeckModelId.PLUS).grid.dials == 4 and model_of(DeckModelId.PLUS).grid.strip
    assert model_of(DeckModelId.PLUS_XL).grid.dials == 6
    assert model_of(DeckModelId.NEO).grid.info and model_of(DeckModelId.NEO).grid.touch == 2
    assert model_of(DeckModelId.PEDAL).grid.pedals == 3


def test_a_grid_is_known_by_its_size_and_an_unknown_one_still_gets_a_default() -> None:
    """Ported: cda-tkl test/stream-deck-profile.test.mjs, "models, key counts and the automatic
    layout": modelFor(5,3) is the 15 and modelFor(8,4) the XL. Changed by SD53: a grid TKL does
    not know is no longer refused; it gets the default computed for its grid."""
    assert size_of(TklDeckGrid(columns=5, rows=3)) == DeckModelId.FIFTEEN
    assert size_of(TklDeckGrid(columns=8, rows=4)) == DeckModelId.XL
    assert size_of(TklDeckGrid(columns=3, rows=2)) == DeckModelId.MINI, "Module 6 is a Mini"
    assert size_of(TklDeckGrid(columns=9, rows=8)) is None
    _, plant, panel = station(STATIONS[0])
    for grid in (TklDeckGrid(columns=4, rows=3), TklDeckGrid(columns=9, rows=8)):
        made = build(plant, panel, grid)
        assert made.pages, grid
        assert all(len(p.keys) == grid.columns * grid.rows for p in made.pages)
        assert keys(made.pages[0].keys, K.MODE), "Läge is on every grid with keys"


@pytest.mark.parametrize("name", STATIONS)
@pytest.mark.parametrize("model_id", [m.id for m in MODELS])
def test_the_default_profile_for_every_model_and_station(name: str, model_id: DeckModelId) -> None:
    """SD32, SD39, SD53: every model's default is computed from the station model. Every page
    holds exactly the grid's keys, row by row (SD5), with the fixed keys on every page (SD27),
    and every place of Platser is on it once.

    Ported: cda-tkl test/stream-deck.test.mjs, "pages ... cover every plupp once", and
    test/stream-deck-profile.test.mjs, "every page has the model's key count"."""
    made = profile(name, model_id)
    grid = made.grid
    size = grid.columns * grid.rows
    if model_id == DeckModelId.PEDAL:
        assert made.style == DeckStyle.NONE and made.pages == [] and made.modes == []
        return
    assert made.pages
    for page in made.pages:
        assert len(page.keys) == size, page.name
        if page.kind != DeckPageKind.CUTOUT or made.style != DeckStyle.ROW:
            for index in made.fixed:
                assert page.keys[index] is not None, (page.name, index)
    placed = [
        k.place or ""
        for p in made.pages
        if p.kind in (DeckPageKind.PLACES, DeckPageKind.PART)
        for k in p.keys
        if k is not None and k.type in (K.PLACE, K.TRACK)
    ]
    assert sorted(placed) == sorted(p.id for p in made.places), "every place once"


@pytest.mark.parametrize("model_id", [m.id for m in MODELS if m.id != DeckModelId.PEDAL])
def test_lage_sits_where_sd77_says(model_id: DeckModelId) -> None:
    """SD77, SD78: far right in the fixed row on the 15 and Studio, at the bottom of the right
    column on XL and + XL, as the last key on Neo and +; on Mini holding ▶ opens Läge."""
    made = profile(STATIONS[0], model_id)
    grid = made.grid
    size = grid.columns * grid.rows
    first = made.pages[0].keys
    if made.style == DeckStyle.NEXT:
        assert keys(first, K.NEXT) == [size - 1] and not keys(first, K.MODE)
    elif made.style == DeckStyle.LAST:
        assert keys(first, K.MODE) == [size - 1]
    elif made.style == DeckStyle.COLUMN:
        assert keys(first, K.MODE) == [size - 1]
        assert all(i % grid.columns == grid.columns - 1 for i in made.fixed), "the right column"
        assert keys(first, K.ALARM) == [grid.columns - 1], "Larm och klocka at the top"
    else:
        assert keys(first, K.MODE) == [size - 1]
        bottom = range((grid.rows - 1) * grid.columns, size)
        assert all(i in bottom for i in made.fixed), "the fixed row at the bottom"
        assert len(keys(first, K.ACTION)) == 2, "Ankommit and Lös ut (SD27)"
    expected = {
        DeckStyle.NEXT: {DeckModelId.MINI, DeckModelId.MODULE_6},
        DeckStyle.LAST: {DeckModelId.NEO, DeckModelId.PLUS},
        DeckStyle.COLUMN: {DeckModelId.XL, DeckModelId.MODULE_32, DeckModelId.PLUS_XL},
        DeckStyle.ROW: {DeckModelId.FIFTEEN, DeckModelId.MODULE_15, DeckModelId.STUDIO},
    }
    assert model_id in expected[made.style]


@pytest.mark.parametrize("model_id", [m.id for m in MODELS])
def test_the_modes_per_model(model_id: DeckModelId) -> None:
    """SD76: Mini, Module 6 and Neo have Tågen and Platser (Bangård comes with #87); from 15 keys,
    or with dials, Spårplan too. Pedal has none."""
    made = profile(STATIONS[0], model_id)
    small = {DeckModelId.MINI, DeckModelId.MODULE_6, DeckModelId.NEO}
    if model_id == DeckModelId.PEDAL:
        assert made.modes == []
    elif model_id in small:
        assert made.modes == [DeckMode.TRAINS, DeckMode.PLACES]
    else:
        assert made.modes == [DeckMode.TRAINS, DeckMode.PLACES, DeckMode.TRACK_PLAN]
    if made.grid.dials:
        trains = [DeckDial.TRAIN, DeckDial.TRACK, DeckDial.PAGE, DeckDial.ROUTE]
        assert made.dials[DeckMode.TRAINS] == trains[: made.grid.dials], "SD83"
        assert len(made.dials[DeckMode.PLACES]) == min(4, made.grid.dials), "SD83"


@pytest.mark.parametrize("name", STATIONS)
def test_the_places_are_where_train_routes_start_or_end(name: str) -> None:
    """SD66: a key per exit and track part where a train route starts or ends, counted from the
    model; the parts west to east (SD2, SD79), each with its places top to bottom."""
    _, plant, panel = station(name)
    geo = geography_of(plant, panel)
    ends: set[str] = set()
    for way in plant.ways():
        if way.kind != RouteKind.TRAIN:
            continue
        if way.leaves:
            ends.add(way.leaves)
        track = plant.track_of.get(way.sections[-1][0])
        if track:
            ends.add(track)
    assert ends <= {p.name for p in geo.places}, "every goal of a train route is a place"
    parts = geo.parts
    assert parts[0].name == "Väster", "the west exits first"
    exits_east = any(p.kind == "exit" and p.part == len(parts) - 1 for p in geo.places)
    assert parts[-1].name == ("Öster" if exits_east and len(parts) > 1 else parts[-1].name)
    xs = [[p.x for p in geo.places if p.part == i] for i in range(len(parts))]
    assert [min(x) for x in xs[1:-1]] == sorted(min(x) for x in xs[1:-1]), "west to east"
    for i, part in enumerate(parts):
        ys = [p.y for p in geo.places if p.part == i]
        assert ys == sorted(ys), "top to bottom"
        assert part.said, part.name


def test_names_in_short() -> None:
    assert compressed(["A1", "A2", "A3", "A4"]) == "A1–A4"
    assert compressed(["1c", "2c", "11", "12", "13"]) == "1c 2c 11–13"
    assert compressed(["1b", "2b", "3", "4", "5b"]) == "1b 2b 3 4 5b"


@pytest.mark.parametrize("name", STATIONS)
def test_platser_on_the_15_is_a_row_per_part_and_half_the_station_per_page(name: str) -> None:
    """SD80: on the 15 a part starts a row of its own unless it fits after the one before, and
    each page holds the two rows above the fixed row."""
    made = profile(name, DeckModelId.FIFTEEN)
    part_of = {p.id: p.part for p in made.places}
    pages = [p for p in made.pages if p.kind == DeckPageKind.PLACES]
    assert pages
    for page in pages:
        assert not any(k is not None and k.type in (K.PLACE, K.TRACK) for k in page.keys[10:])
        for row in (page.keys[0:5], page.keys[5:10]):
            found = [part_of[k.place] for k in row if k is not None and k.place in part_of]
            assert found == sorted(found), "west to east in the row"


@pytest.mark.parametrize("name", STATIONS)
def test_small_decks_choose_a_part_and_then_the_place(name: str) -> None:
    """SD79: Mini, Neo and + choose the part first; a part's page is not among Sidor."""
    for model_id in (DeckModelId.MINI, DeckModelId.NEO, DeckModelId.PLUS):
        made = profile(name, model_id)
        parts = [p for p in made.pages if p.kind == DeckPageKind.PARTS]
        assert parts and all(p.listed for p in parts)
        opened = {k.page for p in parts for k in p.keys if k is not None and k.type == K.PART}
        assert all(made.pages[i].kind == DeckPageKind.PART for i in opened if i is not None)
        assert all(not p.listed for p in made.pages if p.kind == DeckPageKind.PART)
        assert len(opened) == len(made.parts), "a key per part"


@pytest.mark.parametrize("name", STATIONS)
def test_wide_decks_show_the_nearest_trains_in_the_keys_left_over(name: str) -> None:
    """SD84, SD85: on + XL the trains stand in the column left of the fixed one, and on Studio
    the places run from west to east along the top row first."""
    plus_xl = profile(name, DeckModelId.PLUS_XL)
    for page in (p for p in plus_xl.pages if p.kind == DeckPageKind.PLACES):
        trains = keys(page.keys, K.TRAIN)
        assert all(i % 9 == 7 for i in trains)
    studio = profile(name, DeckModelId.STUDIO)
    first = next(p for p in studio.pages if p.kind == DeckPageKind.PLACES)
    top = [k.place for k in first.keys[:16] if k is not None and k.type in (K.PLACE, K.TRACK)]
    order = [p.id for p in studio.places]
    assert top == order[: len(top)], "west to east on the top row"


@pytest.mark.parametrize("name", STATIONS)
@pytest.mark.parametrize("model_id", [DeckModelId.MINI, DeckModelId.FIFTEEN, DeckModelId.XL])
def test_every_route_is_reachable_from_the_deck(name: str, model_id: DeckModelId) -> None:
    """SD44, here for the default: every route's start is on Alla, and its goal among the
    interlocking's goals from there, so a start and a goal set it."""
    made = profile(name, model_id)
    _, plant, _ = station(name)
    on_alla = {
        k.point
        for p in made.pages
        if p.kind == DeckPageKind.ALL
        for k in p.keys
        if k is not None and k.type == K.SIGNAL
    }
    it = Interlocking(plant)
    goals: dict[str, set[tuple[str, str]]] = {}
    for way in plant.ways():
        assert way.start in on_alla, way.name
        if way.start not in goals:
            found = it.targets(way.start)
            goals[way.start] = {(t.end, t.kind.value) for t in found.targets}
        assert (way.end, way.kind.value) in goals[way.start], way.name


@pytest.mark.parametrize("name", STATIONS)
def test_no_code_names_the_station(name: str) -> None:
    """SD5, RS13: the deck's code has no station's name; a profile is computed from data."""
    model, _, _ = station(name)
    code = Path(__file__).resolve().parents[1] / "deck"
    for file in code.glob("*.py"):
        text = file.read_text("utf-8")
        assert model.name not in text, file.name
        assert f'"{model.station_id}"' not in text, file.name


def test_the_frames() -> None:
    """The frame of a grid: what is left for the modes."""
    fifteen = frame(model_of(DeckModelId.FIFTEEN).grid)
    assert fifteen.body == (5, 2) and fifteen.fixed["mode"] == 14
    xl = frame(model_of(DeckModelId.XL).grid)
    assert xl.body == (7, 4) and xl.fixed == {"alarm": 7, "arrived": 15, "release": 23, "mode": 31}
    plus_xl = frame(model_of(DeckModelId.PLUS_XL).grid)
    assert plus_xl.body == (8, 4), "the ninth column is fixed (SD84)"
    studio = frame(model_of(DeckModelId.STUDIO).grid)
    assert [len(r) for r in studio.rows] == [16, 11]
