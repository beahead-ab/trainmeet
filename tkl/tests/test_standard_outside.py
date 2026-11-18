"""The station's outside derived from its model (STD-08, TKL92): ids, sides and the tracks that
reach each exit, on Provby and Ekby, and on the four reference stations.

The reference stations' expected outsides are in tkl/tests/utsidor/, one file per station, so
that no code names a station (RS13): the exits' ids, sides, names, tracks and signals, and the
station tracks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.common import Side, canonical_json
from contracts.station_model import (
    LineExit,
    StationModel,
    StationTrack,
    SwitchControl,
    to_json,
)
from contracts.station_outside import StationOutside
from tkl.standard import OutsideError, checks, outside_of, problems
from tkl.standard.outside import outside_id
from tkl.tests.provstation import ekby, provby

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "tkl" / "referens"
EXPECTED = Path(__file__).resolve().parent / "utsidor"
STATIONS = sorted(p.name.removesuffix(".tkl.json") for p in MODELS.glob("*.tkl.json"))
NO_EXITS = (
    "Stationsmodellen har inga linjeutfarter. Stationens utsida räknas fram ur stationsspåren "
    "och linjeutfarterna (TKL92)."
)
NO_TRACKS = (
    "Stationsmodellen har inga stationsspår. Stationens utsida räknas fram ur stationsspåren "
    "och linjeutfarterna (TKL92)."
)


def model(station: str) -> StationModel:
    return StationModel.model_validate_json((MODELS / f"{station}.tkl.json").read_text("utf-8"))


def expected(station: str) -> StationOutside:
    text = (EXPECTED / f"{station}.utsida.json").read_text("utf-8")
    return StationOutside.model_validate_json(text)


def outside(found: StationModel) -> StationOutside:
    return outside_of(found, found.station_id, found.name)


def renamed(found: StationModel, *exits: LineExit) -> StationModel:
    return found.model_copy(update={"line_exits": list(exits)})


def test_each_reference_station_has_its_expected_outside() -> None:
    assert sorted(p.name.removesuffix(".utsida.json") for p in EXPECTED.glob("*.json")) == STATIONS


@pytest.mark.parametrize("station", STATIONS)
def test_a_reference_station_gives_a_valid_outside(station: str) -> None:
    """Every station track and line exit is in the outside, with the ids, sides and tracks the
    fixture says; the owner's text stays as the label and the name."""
    found = model(station)
    made = outside(found)
    StationOutside.model_validate(made.model_dump(mode="json"))
    assert made == expected(station)
    assert [t.label for t in made.tracks] == [t.label for t in found.station_tracks]
    assert [e.signals for e in made.exits] == [e.signals for e in found.line_exits]
    for line, exit_ in zip(found.line_exits, made.exits, strict=True):
        assert exit_.name is not None and exit_.name.startswith(line.id)
        assert exit_.id == outside_id(line.id)
    assert made.sides == [], "as at level 0"


def test_the_reference_stations_fold_their_exits_to_ids() -> None:
    """The model's free text, such as "Väst 1", is no id; the outside's id is folded from it."""
    folded = {
        (line.id, exit_.id)
        for found in (model(station) for station in STATIONS)
        for line, exit_ in zip(found.line_exits, outside(found).exits, strict=True)
        if line.id != exit_.id
    }
    assert folded == {
        ("Väst 1", "Vast-1"),
        ("Väst 2", "Vast-2"),
        ("Öst 1", "Ost-1"),
        ("Öst 2", "Ost-2"),
        ("Enkelspår", "Enkelspar"),
    }


def test_names_fold_to_ascii_ids() -> None:
    assert outside_id("Väst 1") == "Vast-1"
    assert outside_id("Öst 2") == "Ost-2"
    assert outside_id("Åby–Ärla") == "Aby-Arla"
    assert outside_id("Café é") == "Cafe-e"
    assert outside_id("Ærø") == "AEro"
    assert outside_id("Spår  31 (norr)") == "Spar-31-norr"
    assert outside_id("_Gren:2") == "Gren:2", "an id starts with a letter or a digit"
    assert outside_id("1a") == "1a", "an id stays as it is"
    assert outside_id("1-") == "1-"
    assert outside_id("→") == ""
    assert len(outside_id("Ö" * 100)) == 80


def test_two_exits_that_fold_to_the_same_id_get_2() -> None:
    found = provby()
    west, east = found.line_exits
    both = renamed(
        found,
        west.model_copy(update={"id": "Väst 1"}),
        east.model_copy(update={"id": "Vast 1"}),
    )
    assert problems(both) == []
    made = outside(both)
    assert [(e.id, e.name) for e in made.exits] == [
        ("Vast-1", "Väst 1 mot Västby"),
        ("Vast-1-2", "Vast 1 mot Östby"),
    ]


def test_an_own_outside_id_wins() -> None:
    """outside_id keeps an id stable when the owner renames; a derived id gives way to it."""
    found = provby()
    west, east = found.line_exits
    own = renamed(
        found,
        west.model_copy(update={"id": "Väst 1"}),
        east.model_copy(update={"id": "Öst", "outside_id": "Vast-1"}),
    )
    track_1, track_2 = found.station_tracks
    own = own.model_copy(
        update={"station_tracks": [track_1.model_copy(update={"outside_id": "upp"}), track_2]}
    )
    made = outside(own)
    assert [(e.id, e.name) for e in made.exits] == [
        ("Vast-1-2", "Väst 1 mot Västby"),
        ("Vast-1", "Öst mot Östby"),
    ]
    assert [(t.id, t.label) for t in made.tracks] == [("upp", "Spår 1"), ("2", "Spår 2")]
    assert [e.tracks for e in made.exits] == [["upp", "2"], ["upp", "2"]]


def test_two_own_outside_ids_that_are_the_same_are_a_problem() -> None:
    found = provby()
    west, east = found.line_exits
    twice = renamed(
        found,
        west.model_copy(update={"outside_id": "A"}),
        east.model_copy(update={"outside_id": "A"}),
    )
    assert problems(twice) == ["Två linjeutfarter har samma id i utsidan: A."]
    with pytest.raises(OutsideError):
        outside(twice)


def test_an_exit_name_without_letters_or_digits_needs_an_own_id() -> None:
    found = provby()
    west, east = found.line_exits
    arrow = renamed(found, west.model_copy(update={"id": "→"}), east)
    assert problems(arrow) == [
        "Linjeutfarten → ger inget id i utsidan: namnet har inga bokstäver eller siffror som "
        "går att använda. Ge den ett eget id för utsidan."
    ]
    given = renamed(found, west.model_copy(update={"id": "→", "outside_id": "V"}), east)
    assert [e.id for e in outside(given).exits] == ["V", "O"]


@pytest.mark.parametrize("station", STATIONS)
def test_the_same_model_always_gives_the_same_outside(station: str) -> None:
    found = model(station)
    again = StationModel.model_validate_json(to_json(found))
    first, second = outside(found), outside(again)
    assert first == second
    assert canonical_json(first.model_dump(mode="json")) == canonical_json(
        second.model_dump(mode="json")
    )


def test_the_sides_follow_west_and_east() -> None:
    """Ekby's drawing has W in the west and O in the east; drawn the other way round, the
    sides turn too. Provby's exits follow its pieces, which run from west to east."""
    drawn = ekby()
    assert [(e.id, e.side) for e in outside(drawn).exits] == [("W", Side.LEFT), ("O", Side.RIGHT)]
    mirrored = drawn.model_copy(
        update={
            "pieces": [
                p.model_copy(update={"geometry": [(-x, y) for x, y in p.geometry]})
                for p in drawn.pieces
            ]
        }
    )
    assert checks(mirrored) == ([], [])
    assert [(e.id, e.side) for e in outside(mirrored).exits] == [
        ("W", Side.RIGHT),
        ("O", Side.LEFT),
    ]
    assert [(e.id, e.side) for e in outside(provby()).exits] == [
        ("V", Side.LEFT),
        ("O", Side.RIGHT),
    ]


def test_an_exit_reaches_the_nearest_station_tracks_through_the_graph() -> None:
    """The model gives no tracks for the exits: the walk from each exit stops at the first
    station track on each way into the station."""
    made = outside(provby())
    assert [(e.id, e.tracks, e.signals) for e in made.exits] == [
        ("V", ["1", "2"], ["In", "Ut"]),
        ("O", ["1", "2"], ["Ut2", "In2"]),
    ]


def test_the_model_s_own_tracks_for_an_exit_are_used() -> None:
    found = provby()
    west, east = found.line_exits
    given = renamed(found, west.model_copy(update={"tracks": ["2"]}), east)
    assert [e.tracks for e in outside(given).exits] == [["2"], ["1", "2"]]
    unknown = renamed(found, west.model_copy(update={"tracks": ["Spår 9"]}), east)
    assert [e.tracks for e in outside(unknown).exits] == [["1", "2"], ["1", "2"]], (
        "not a station track: through the graph"
    )


def test_the_walk_does_not_pass_a_planned_switch() -> None:
    found = provby()
    first, second = found.switches
    planned = found.model_copy(
        update={"switches": [first.model_copy(update={"control": SwitchControl.PLANNED}), second]}
    )
    assert [e.tracks for e in outside(planned).exits] == [[], ["1", "2"]]


def test_a_station_track_stops_the_walk() -> None:
    """Track 1 lies between the exit and the siding beyond it: the siding is not reached."""
    found = provby()
    siding = StationTrack(id="9", label="Spår 9", pieces=["e"])
    one = StationTrack(id="1", label="Spår 1", pieces=["c"])
    behind = found.model_copy(update={"station_tracks": [one, siding]})
    assert [e.tracks for e in outside(behind).exits] == [["1"], ["9"]]


def test_a_model_without_exits_or_station_tracks_gives_a_problem() -> None:
    no_exits = provby(line_exits=[])
    assert NO_EXITS in problems(no_exits)
    with pytest.raises(OutsideError) as error:
        outside(no_exits)
    assert NO_EXITS in error.value.problems
    no_tracks = provby(station_tracks=[])
    assert problems(no_tracks) == [NO_TRACKS]
    with pytest.raises(OutsideError) as error:
        outside(no_tracks)
    assert error.value.problems == [NO_TRACKS]


def test_the_exit_s_name_keeps_within_a_line_of_text() -> None:
    found = provby()
    west, east = found.line_exits
    far = renamed(found, west.model_copy(update={"neighbour": "Långby" * 83}), east)
    name = outside(far).exits[0].name
    assert name is not None and name.startswith("V mot Långby") and len(name) <= 500
