"""Flank protection (sidoskydd) on small made-up stations: STV-20, trainmeet #37.

The switches and derailers that could let vehicles in on a laid route are locked away from it
(Benny 15 November). The nearest object on each joining track protects, as in TDOK 2013:0623:
a switch laid to its other leg, or a signal facing the route, a stop point, a buffer stop or
the line.
"""

from __future__ import annotations

from contracts.station_model import Lever, SignalType, StationModel, SwitchControl
from tkl.standard import Route, RouteKind, conflict, derive
from tkl.tests.provstation import MINUS, PLUS, build, signal, switch

TRAIN, SHUNTING = RouteKind.TRAIN, RouteKind.SHUNTING
HSI, DVSI = SignalType.HSI, SignalType.DVSI


def routes(model: StationModel) -> dict[tuple[RouteKind, str, str], Route]:
    return {r.key: r for r in derive(model)}


def crossover(**more: object) -> StationModel:
    """Two parallel tracks with a crossover of switches 1 and 2, signals facing west.

    A -a- 1 -b- B1 -c- B     track 1: A1 at B1, facing west
           \\x
    C -d- 2 -e- E1 -f- D     track 2: C1 at E1, facing west

    1 and 2 are on levers of their own: nothing couples them.
    """
    settings: dict[str, object] = {
        "switches": [switch("1", "b", "a", "x"), switch("2", "d", "e", "x")],
        "signals": [signal("A1", HSI, "B1", "c"), signal("C1", HSI, "E1", "f")],
    }
    settings.update(more)
    return build("a:A-1 b:1-B1 c:B1-B x:1-2 d:C-2 e:2-E1 f:E1-D", **settings)  # type: ignore[arg-type]


def test_the_other_half_of_a_crossover_protects_a_route_along_the_track() -> None:
    """Along track 1 over 1 straight, a vehicle on track 2 could come over the crossover: 2 is
    laid straight, away from it, and locked as protection for 1."""
    along = routes(crossover())[(TRAIN, "A1", "A")]
    assert along.switches == {"1": PLUS}
    assert along.positions == {"1": PLUS, "2": PLUS}
    assert along.flank == {"2": "1"}
    other = routes(crossover())[(TRAIN, "C1", "C")]
    assert other.positions == {"2": PLUS, "1": PLUS}
    assert other.flank == {"1": "2"}


def test_a_route_over_the_crossover_needs_no_protection_there() -> None:
    over = routes(crossover())[(TRAIN, "A1", "C")]
    assert over.positions == {"1": MINUS, "2": MINUS}
    assert over.flank == {}


def test_a_coupled_other_half_is_the_lever_s_and_not_flank() -> None:
    """With 1 and 2 on one lever, the lever already lays 2 straight: nothing more to add."""
    lever = Lever(id="1/2", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS, "2": MINUS})
    along = routes(crossover(levers=[lever]))[(TRAIN, "A1", "A")]
    assert along.positions == {"1": PLUS, "2": PLUS}
    assert along.flank == {}


def fan(**more: object) -> StationModel:
    """Track 1 with switch 1, whose diverging leg goes to the trunk of 2; 2's legs go to 3 and 4,
    which end at buffer stops. A dwarf signal L on 2's straight leg faces away from track 1.

    A -a- 1 -b- B1 -c- B
           \\x- 2 -l1- L -l2- 3 -n- N   (3: trunk n, straight l2, diverging o -> O)
                \\m- 4 -p- P            (4: trunk p, straight m, diverging q -> Q)
    """
    settings: dict[str, object] = {
        "switches": [
            switch("1", "b", "a", "x"),
            switch("2", "x", "l1", "m"),
            switch("3", "n", "l2", "o"),
            switch("4", "p", "m", "q"),
        ],
        "signals": [signal("A1", HSI, "B1", "c"), signal("L", DVSI, "L", "l1")],
    }
    settings.update(more)
    return build(
        "a:A-1 b:1-B1 c:B1-B x:1-2 l1:2-L l2:L-3 m:2-4 n:3-N o:3-O p:4-P q:4-Q",
        **settings,  # type: ignore[arg-type]
    )


def test_from_a_switch_s_trunk_the_walk_goes_on_along_both_legs() -> None:
    """The joining track comes to 2 from its trunk, so vehicles can come from both legs. The
    nearest switches out on them, 3 and 4, are laid away; L faces away and does not protect."""
    along = routes(fan())[(TRAIN, "A1", "A")]
    assert along.flank == {"3": "1", "4": "1"}
    assert along.positions == {"1": PLUS, "3": MINUS, "4": MINUS}


def test_two_routes_that_need_the_protection_both_ways_conflict() -> None:
    """A1 → A locks 3 diverging. The shunting route L → N, away from track 1 over 3 straight,
    now conflicts with it, though the two share no track."""
    found = routes(fan())
    along = found[(TRAIN, "A1", "A")]
    away = found[(SHUNTING, "L", "N")]
    assert away.positions == {"3": PLUS}
    assert conflict(along, away) == "De behöver växel 3 i olika lägen."


def test_a_signal_facing_the_route_protects_it() -> None:
    """A dwarf signal on the crossover facing track 1 shows stop: no switch is locked."""
    model = build(
        "a:A-1 b:1-B1 c:B1-B x1:1-X x2:X-2 d:C-2 e:2-E1 f:E1-D",
        switches=[switch("1", "b", "a", "x1"), switch("2", "d", "e", "x2")],
        signals=[
            signal("A1", HSI, "B1", "c"),
            signal("C1", HSI, "E1", "f"),
            signal("X2", DVSI, "X", "x2"),
        ],
    )
    along = routes(model)[(TRAIN, "A1", "A")]
    assert along.positions == {"1": PLUS}
    assert along.flank == {}


def test_a_buffer_stop_or_the_line_protects_it() -> None:
    """A siding off track 1 that ends at a buffer stop: nothing can come from it."""
    model = build(
        "a:A-1 b:1-B1 c:B1-B s:1-S",
        switches=[switch("1", "b", "a", "s")],
        signals=[signal("A1", HSI, "B1", "c")],
    )
    along = routes(model)[(TRAIN, "A1", "A")]
    assert along.flank == {}


def test_a_switch_tkl_does_not_lay_cannot_protect_so_the_walk_goes_past_it() -> None:
    """2 is laid by hand. The walk goes on from its trunk to 3, which TKL lays."""
    model = build(
        "a:A-1 b:1-B1 c:B1-B x:1-2 y:2-Y d:2-3 e:3-E f:3-F",
        switches=[
            switch("1", "b", "a", "x"),
            switch("2", "d", "x", "y", control=SwitchControl.MANUAL),
            switch("3", "e", "d", "f"),
        ],
        signals=[signal("A1", HSI, "B1", "c")],
    )
    along = routes(model)[(TRAIN, "A1", "A")]
    assert along.flank == {"3": "1"}
    assert along.positions == {"1": PLUS, "3": MINUS}


def test_a_switch_the_route_s_lever_needs_the_other_way_cannot_protect() -> None:
    """1 straight drags 2 diverging, towards track 1. 2 then cannot protect, and the walk goes on
    from its trunk to 3."""
    model = build(
        "a:A-1 b:1-B1 c:B1-B x:1-2 e:2-E d:2-3 g:3-G h:3-H",
        switches=[
            switch("1", "b", "a", "x"),
            switch("2", "d", "e", "x"),
            switch("3", "g", "d", "h"),
        ],
        signals=[signal("A1", HSI, "B1", "c")],
        levers=[Lever(id="1", plus={"1": PLUS, "2": MINUS}, minus={"1": MINUS})],
    )
    along = routes(model)[(TRAIN, "A1", "A")]
    assert along.positions == {"1": PLUS, "2": MINUS, "3": MINUS}
    assert along.flank == {"3": "1"}


def test_the_same_walk_gives_the_same_protection_every_time() -> None:
    first = [(r.key, dict(r.flank)) for r in derive(crossover())]
    assert first == [(r.key, dict(r.flank)) for r in derive(crossover())]
