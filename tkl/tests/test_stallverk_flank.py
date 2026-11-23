"""Flank protection in the interlocking (STV-20, trainmeet #37): the switches a route locks
away from it are laid and locked with the route, shown as protection, refused to other routes
and levers, and released with the section at the node they protect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.station_model import SignalType, StationModel, TrackCircuit
from tkl.stallverk import Interlocking, plant_of
from tkl.tests.provstation import MINUS, PLUS, build, signal, switch

HSI, DVSI = SignalType.HSI, SignalType.DVSI
NOON = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def fan() -> StationModel:
    """Track 1 with switch 1, whose diverging leg goes to the trunk of 2; 2's legs go to 3 and 4.

    B -c- B1 -b- 1 -a1- A1s -a2- A    A1 at B1 facing west; the train stands on c
                  x- 2 -l1- L -l2- 3 -n- N    3: trunk n, straight l2, diverging o
                      m- 4 -p- P              4: trunk p, straight m, diverging q
    """
    return build(
        "a1:1-As a2:As-A b:1-B1 c:B1-B x:1-2 l1:2-L l2:L-3 m:2-4 n:3-N o:3-O p:4-P q:4-Q",
        switches=[
            switch("1", "b", "a1", "x"),
            switch("2", "x", "l1", "m"),
            switch("3", "n", "l2", "o"),
            switch("4", "p", "m", "q"),
        ],
        signals=[signal("A1", HSI, "B1", "c"), signal("L", DVSI, "L", "l1")],
        track_circuits=[
            TrackCircuit(name="Spår B", pieces=["c"]),
            TrackCircuit(name="Vx1", pieces=["b", "a1", "x"]),
            TrackCircuit(name="Ut", pieces=["a2"]),
        ],
    )


def made(model: StationModel) -> Interlocking:
    return Interlocking(plant_of(model), now=lambda: NOON)


def yes(outcome: Any) -> Any:
    assert outcome.accepted, outcome.message
    return outcome


def no(outcome: Any, *said: str) -> None:
    assert not outcome.accepted, outcome.message
    for text in said:
        assert text in outcome.message, outcome.message


def test_a_route_lays_and_locks_its_flank_protection_shown_as_protection() -> None:
    it = made(fan())
    route = yes(it.set_route("A1", "A")).route
    shown = it.view().switches
    assert (shown["3"].position, shown["4"].position) == (MINUS, MINUS)
    assert shown["3"].routes == [route] and shown["3"].protection
    assert shown["4"].routes == [route] and shown["4"].protection
    assert shown["1"].routes == [route] and not shown["1"].protection
    [laid] = it.view().routes
    assert laid.protection == ["3", "4"]
    no(it.lay_lever("3"), "låst")


def test_a_route_that_needs_a_protection_switch_the_other_way_waits() -> None:
    it = made(fan())
    yes(it.set_route("A1", "A"))
    no(it.set_route("L", "N"))
    assert it.view().switches["3"].position == MINUS


def test_the_protection_is_released_with_the_section_at_the_node_it_protects() -> None:
    it = made(fan())
    yes(it.put_train("41", section="Spår B"))
    route = yes(it.set_route("A1", "A")).route
    yes(it.step(route))
    assert it.view().switches["3"].routes == [route], "the train is at switch 1"
    yes(it.step(route))
    shown = it.view().switches
    assert shown["1"].routes == [] and shown["3"].routes == [] and shown["4"].routes == []
    yes(it.lay_lever("3", PLUS))
    yes(it.set_route("L", "N"))
