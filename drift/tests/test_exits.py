"""Stationens utfarter mot sträckorna (H26, PLAN-31): Hubben gissar på grannens namn, sidan och
förra träffens svar, och frågar när den är osäker."""

from __future__ import annotations

from pathlib import Path

from contracts import station
from contracts.common import Side
from contracts.meet import ClearanceMode, TrackKind
from contracts.station_outside import Exit, StationOutside, StationTrack
from drift.exits import ExitMemory, couple

LEFT, RIGHT = Side.LEFT, Side.RIGHT
NEIGHBOURS = {
    "vby": station.Neighbour(place="vby", code="Vby", name="Västby"),
    "oby": station.Neighbour(place="oby", code="Öby", name="Östby"),
    "lmn": station.Neighbour(place="lmn", code="Lmn", name="Lillmon"),
}


def outside(*exits: Exit) -> StationOutside:
    return StationOutside(
        station_id="exempelby",
        name="Exempelby",
        tracks=[StationTrack(id="1", label="Spår 1"), StationTrack(id="2", label="Spår 2")],
        exits=list(exits),
    )


def here(
    section: str, other: str, side: Side | None, tracks: str = "single"
) -> station.SectionHere:
    return station.SectionHere(
        section=section,
        other_place=other,
        other_code=NEIGHBOURS[other].code,
        tracks=TrackKind(tracks),
        clearance_mode=ClearanceMode.REQUESTED,
        side=side,
    )


def test_the_neighbours_name_the_side_and_a_single_exit() -> None:
    """Väster is A mot Västby; Öster has BU and BN, both mot Östby: a question, with the two."""
    station_ = outside(
        Exit(id="A", side=LEFT, name="Mot Västby"),
        Exit(id="BU", side=RIGHT, name="Östby uppspår"),
        Exit(id="BN", side=RIGHT, name="Östby nedspår"),
    )
    found, asked = couple(
        station_,
        "exb",
        [here("s-vby", "vby", None), here("s-oby", "oby", RIGHT, "double")],
        NEIGHBOURS,
    )
    assert found == {"s-vby": "A"}, "the name alone is enough, without a side"
    assert [(q.section, q.other_name, [a.exit for a in q.alternatives]) for q in asked] == [
        ("s-oby", "Östby", ["BU", "BN"])
    ]
    # Answered this meet, or last meet with Östby: no question.
    assert couple(
        station_, "exb", [here("s-oby", "oby", RIGHT)], NEIGHBOURS, answered={"s-oby": "BN"}
    )[0] == {"s-oby": "BN"}
    assert couple(
        station_, "exb", [here("s-x", "oby", RIGHT)], NEIGHBOURS, remembered={"östby": "BU"}
    )[0] == {"s-x": "BU"}


def test_the_side_decides_when_one_exit_is_there() -> None:
    station_ = outside(Exit(id="V", side=LEFT), Exit(id="O", side=RIGHT))
    found, asked = couple(
        station_, "exb", [here("a", "vby", LEFT), here("b", "oby", RIGHT)], NEIGHBOURS
    )
    assert (found, asked) == ({"a": "V", "b": "O"}, [])
    # Without a side and without names, Hubben is not sure.
    found, asked = couple(station_, "exb", [here("a", "vby", None)], NEIGHBOURS)
    assert found == {} and [a.exit for a in asked[0].alternatives] == ["V", "O"]
    # A station with one exit has no choice to make.
    assert couple(outside(Exit(id="A", side=LEFT)), "exb", [here("a", "vby", None)], NEIGHBOURS)[
        0
    ] == {"a": "A"}


def test_two_sections_guessed_onto_one_exit_are_both_asked() -> None:
    """A junction: Västby and Lillmon both leave to the left, and the station has one exit
    there. Neither guess is sure."""
    station_ = outside(Exit(id="V", side=LEFT), Exit(id="O", side=RIGHT))
    found, asked = couple(
        station_, "exb", [here("a", "vby", LEFT), here("c", "lmn", LEFT)], NEIGHBOURS
    )
    assert found == {} and sorted(q.section for q in asked) == ["a", "c"]


def test_planerings_table_and_an_unknown_exit() -> None:
    station_ = outside(Exit(id="V", side=LEFT), Exit(id="O", side=RIGHT))
    found, _ = couple(station_, "exb", [here("a", "vby", None)], NEIGHBOURS, pinned={"a": "O"})
    assert found == {"a": "O"}, "coupled in advance: used as it is"
    found, asked = couple(
        station_, "exb", [here("a", "vby", None)], NEIGHBOURS, answered={"a": "X"}
    )
    assert found == {} and len(asked) == 1, "an exit the station no longer has is asked again"


def test_the_memory_is_kept_across_meets(tmp_path: Path) -> None:
    memory = ExitMemory(tmp_path / "utfarter.sqlite3")
    assert memory.remembered("exempelby") == {}
    memory.remember("exempelby", "Östby ", "BN")
    memory.remember("exempelby", "östby", "BU")
    assert ExitMemory(tmp_path / "utfarter.sqlite3").remembered("exempelby") == {"östby": "BU"}
    assert memory.remembered("annanby") == {}
