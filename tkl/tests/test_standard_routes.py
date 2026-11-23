"""The engine's routes on small made-up stations: §2 "Framräknat", RS9, TKL28, TKL53, TKL104.

The tests marked "Ported" carry an old cda-tkl test's behaviour; the old test is named.
"""

from __future__ import annotations

import random
from typing import Literal

from contracts.station_model import (
    Lever,
    NodeType,
    Position,
    SignalType,
    SlipPart,
    StationModel,
    Switch,
    SwitchControl,
    SwitchPath,
    SwitchType,
    TrackCircuit,
    Turntable,
    TurntableTrack,
)
from tkl.standard import (
    PointKind,
    Route,
    RouteKind,
    alternatives,
    chains,
    conflict,
    derive,
    hindrances,
    must_be_free,
    split,
)
from tkl.tests.provstation import MINUS, PLUS, build, provby, signal, switch

TRAIN, SHUNTING = RouteKind.TRAIN, RouteKind.SHUNTING
HSI, HDVSI, DVSI = SignalType.HSI, SignalType.HDVSI, SignalType.DVSI
STOP_LAMP = SignalType.STOP_LAMP


def routes(model: StationModel) -> dict[tuple[RouteKind, str, str], Route]:
    return {r.key: r for r in derive(model)}


def laid(route: Route) -> dict[str, Position]:
    """What the route's own switches and their levers lay, without its flank protection."""
    return {p: v for p, v in route.positions.items() if p not in route.flank}


def pairs(model: StationModel, kind: RouteKind) -> set[tuple[str, str]]:
    return {(a, b) for (k, a, b) in routes(model) if k == kind}


# --- train routes and shunting routes (§2, TKL28) ----------------------------------------


def test_train_routes_run_from_main_signal_to_the_next_main_signal() -> None:
    assert pairs(provby(), TRAIN) == {
        ("In", "12"),
        ("In", "22"),
        ("12", "Ut2"),
        ("22", "Ut2"),
        ("In2", "11"),
        ("In2", "21"),
        ("11", "Ut"),
        ("21", "Ut"),
    }


def test_a_train_route_passes_dwarf_signals_and_signals_facing_the_other_way() -> None:
    found = routes(provby())
    to_track_2 = found[(TRAIN, "In", "22")]
    assert to_track_2.passed == ("D",), "the dwarf in its direction shows proceed"
    assert "21" in to_track_2.guards, "the signal facing it must show stop"
    assert "11" in found[(TRAIN, "In", "12")].guards
    assert to_track_2.positions == {"1": MINUS}
    assert to_track_2.track_circuits == ("Vx1", "Spår 2"), "in order, for sectional release"


def test_shunting_routes_end_at_the_next_signal_of_any_kind() -> None:
    assert pairs(provby(), SHUNTING) == {("21", "Ut"), ("22", "Ut2"), ("D", "22")}


def test_a_combined_signal_starts_both_kinds_and_a_main_signal_only_train_routes() -> None:
    found = routes(provby())
    assert (TRAIN, "22", "Ut2") in found and (SHUNTING, "22", "Ut2") in found
    assert not any(k == SHUNTING and a in {"In", "11", "12"} for (k, a, _) in found)
    assert not any(k == TRAIN and a == "D" for (k, a, _) in found), "a dwarf starts no train route"


def stub() -> StationModel:
    """A siding off track 1: a stop lamp at its end, a buffer stop on another track.

    V -a- W -b- 1 -c- X -e- 3 -s- Q -t- S         (S: stop lamp L at the track's end)
                            \\u- R -v- B            (B: buffer stop)
    """
    return build(
        "a:V-W b:W-1 c:1-X e:X-3 s:3-Q t:Q-S u:3-R v:R-B d:1-Y w:Y-Z",
        switches=[switch("1", "b", "c", "d"), switch("3", "e", "s", "u")],
        signals=[
            signal("In", HSI, "W", "a"),
            signal("31", HDVSI, "X", "c"),
            signal("L", STOP_LAMP, "S", "t"),
            signal("32", DVSI, "R", "v"),
            signal("Z2", HSI, "Y", "w"),
        ],
        exits={"V": "Västby"},
        types={"S": NodeType.BUFFER_STOP},
    )


def test_a_stop_lamp_ends_routes_but_never_starts_one() -> None:
    found = routes(stub())
    assert (TRAIN, "31", "L") in found and (SHUNTING, "31", "L") in found
    assert found[(TRAIN, "31", "L")].end.kind == PointKind.SIGNAL
    assert not any(a == "L" for (_, a, _) in found), "RS3"


def test_a_buffer_stop_ends_train_routes_and_shunting_routes() -> None:
    found = routes(stub())
    assert found[(TRAIN, "31", "B")].end.kind == PointKind.BUFFER_STOP
    assert found[(SHUNTING, "31", "B")].passed == (), "the dwarf 32 faces the other way"
    assert (TRAIN, "In", "31") in found


def test_a_shunting_route_may_go_towards_an_occupied_track() -> None:
    """TKL28: the track circuit it ends in may be occupied; a train route needs it free."""
    model = provby()
    found = routes(model)
    shunt, train = found[(SHUNTING, "21", "Ut")], found[(TRAIN, "21", "Ut")]
    assert shunt.track_circuits == train.track_circuits == ("Vx1",)
    found_d = found[(SHUNTING, "D", "22")]
    assert found_d.track_circuits == ("Spår 2",)
    assert must_be_free(found_d) == ()
    assert hindrances(found_d, {"Spår 2"}, {}) == []
    to_track = found[(TRAIN, "In", "22")]
    assert must_be_free(to_track) == ("Vx1", "Spår 2")
    assert hindrances(to_track, {"Spår 2"}, {}) == ["Spårledningen Spår 2 är belagd."]
    longer = found[(SHUNTING, "22", "Ut2")]
    assert hindrances(longer, {"Vx2"}, {}) == [], "the end circuit may be occupied"


# --- levers (STD-29, TKL104, RS2) ---------------------------------------------------------


def crossover(levers: list[Lever]) -> StationModel:
    """Two parallel tracks with a crossover of switches 1 and 2, signals facing west.

    A -a- 1 -b- B1 -c- B     track 1: A1 at B1, facing west
           \\x
    C -d- 2 -e- E1 -f- D     track 2: C1 at E1, facing west
    """
    return build(
        "a:A-1 b:1-B1 c:B1-B x:1-2 d:C-2 e:2-E1 f:E1-D",
        switches=[switch("1", "b", "a", "x"), switch("2", "d", "e", "x")],
        signals=[signal("A1", HSI, "B1", "c"), signal("C1", HSI, "E1", "f")],
        levers=levers,
    )


def test_coupled_switches_are_laid_together_also_the_one_off_the_path() -> None:
    """Ported: "every network route reserves the complete source-linked companion group" and
    "a route along one track locks the off-path crossover companion" (cda-tkl
    test/network.test.mjs)."""
    lever = Lever(id="1/2", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS, "2": MINUS})
    found = routes(crossover([lever]))
    along = found[(TRAIN, "A1", "A")]
    assert along.switches == {"1": PLUS}
    assert along.positions == {"1": PLUS, "2": PLUS}
    assert along.levers == {"1/2": PLUS}
    over = found[(TRAIN, "A1", "C")]
    assert over.positions == {"1": MINUS, "2": MINUS}


def test_a_reversed_switch_lies_the_other_way_on_its_lever() -> None:
    """omvänd: in the lever's +, switch 2 lies diverging. The crossover then needs 1 diverging
    and 2 straight, so the lever would be both ways and no route crosses over."""
    lever = Lever(id="1/2", plus={"1": PLUS, "2": MINUS}, minus={"1": MINUS, "2": PLUS})
    found = routes(crossover([lever]))
    assert found[(TRAIN, "A1", "A")].positions == {"1": PLUS, "2": MINUS}
    assert found[(TRAIN, "C1", "C")].positions == {"2": PLUS, "1": MINUS}
    assert (TRAIN, "A1", "C") not in found, "a route that needs a lever both ways is rejected"


def test_a_switch_drags_another_along_in_one_position_only() -> None:
    """95 to diverging drags 96 along, and 96 to straight drags 95 (TKL104)."""
    levers = [
        Lever(id="1", plus={"1": PLUS}, minus={"1": MINUS, "2": MINUS}),
        Lever(id="2", plus={"2": PLUS, "1": PLUS}, minus={"2": MINUS}),
    ]
    found = routes(crossover(levers))
    assert found[(TRAIN, "A1", "C")].positions == {"1": MINUS, "2": MINUS}
    assert found[(TRAIN, "A1", "C")].levers == {"1": MINUS, "2": MINUS}
    assert laid(found[(TRAIN, "A1", "A")]) == {"1": PLUS}, "1 straight drags nothing"
    assert found[(TRAIN, "C1", "C")].positions == {"2": PLUS, "1": PLUS}


def test_a_drag_that_meets_the_route_s_own_switch_rejects_the_route() -> None:
    """1 to diverging drags 2 straight, so the crossover, which needs both diverging, is gone."""
    levers = [Lever(id="1", plus={"1": PLUS}, minus={"1": MINUS, "2": PLUS})]
    found = routes(crossover(levers))
    assert (TRAIN, "A1", "C") not in found
    assert laid(found[(TRAIN, "A1", "A")]) == {"1": PLUS}
    assert laid(found[(TRAIN, "C1", "C")]) == {"2": PLUS}


def test_a_lever_with_three_parts_lays_them_all() -> None:
    """RS2: one number, three parts, as a switch 22 with 22a, 22b and 22c."""
    found = routes(_three_parts())
    straight = found[(TRAIN, "S", "B")]
    assert straight.switches == {"22a": PLUS, "22b": PLUS, "22c": PLUS}
    assert straight.levers == {"22": PLUS}
    off = found[(TRAIN, "S", "X")]
    assert off.positions == {"22a": MINUS, "22b": MINUS, "22c": MINUS}
    assert (TRAIN, "S", "Y") not in found, "22b diverging needs 22a straight: both ways"


def _three_parts() -> StationModel:
    """V -a- p -b- q -c- r -d- B, with 22a, 22b and 22c diverging to X, Y and Z."""
    parts = ["22a", "22b", "22c"]
    return build(
        "v:V-W a:W-p b:p-q c:q-r d:r-B x:p-X y:q-Y z:r-Z",
        switches=[
            switch("22a", "a", "b", "x", node="p"),
            switch("22b", "b", "c", "y", node="q"),
            switch("22c", "c", "d", "z", node="r"),
        ],
        signals=[signal("S", HSI, "W", "v")],
        levers=[
            Lever(
                id="22",
                plus=dict.fromkeys(parts, PLUS),
                minus=dict.fromkeys(parts, MINUS),
            )
        ],
    )


def test_no_route_crosses_a_switch_that_tkl_does_not_lay() -> None:
    """Manual (TKL26), planned and not laid switches: the route stops short of them."""
    for control in (SwitchControl.MANUAL, SwitchControl.PLANNED, SwitchControl.NOT_LAID):
        model = provby()
        manual = model.switches[1].model_copy(update={"control": control})
        model = model.model_copy(update={"switches": [model.switches[0], manual]})
        found = pairs(model, TRAIN)
        assert ("12", "Ut2") not in found and ("In2", "11") not in found, control
        assert ("In", "12") in found, control


# --- slips, crossings, Y-switches and the turntable (RS1, RS4, RS9) -----------------------


def double_slip() -> StationModel:
    """A double slip 5a/5b at K with legs ka, kb, kc, kd and a path through each pair."""
    paths = [
        SwitchPath(between=("ka", "kc"), positions={"5a": MINUS, "5b": MINUS}),
        SwitchPath(between=("ka", "kd"), positions={"5a": PLUS, "5b": MINUS}),
        SwitchPath(between=("kb", "kd"), positions={"5a": PLUS, "5b": PLUS}),
        SwitchPath(between=("kb", "kc"), positions={"5a": MINUS, "5b": PLUS}),
    ]
    slip = Switch(
        number="5a/5b",
        type=SwitchType.DOUBLE_SLIP,
        node="K",
        parts=[SlipPart(number="5a"), SlipPart(number="5b")],
        paths=paths,
    )
    return build(
        "a:A-P ka:P-K b:B-Q kb:Q-K kc:K-R c:R-C kd:K-S d:S-D",
        switches=[slip],
        signals=[
            signal("SA", HSI, "P", "a"),
            signal("SB", HSI, "Q", "b"),
            signal("SC", HSI, "R", "kc"),
            signal("SD", HSI, "S", "kd"),
        ],
        exits=dict.fromkeys("ABCD", "Grannby"),
    )


def test_routes_go_through_a_double_slip_with_both_parts_set() -> None:
    found = routes(double_slip())
    assert set(found) == {(TRAIN, a, b) for a in ("SA", "SB") for b in ("SC", "SD")}
    assert found[(TRAIN, "SA", "SC")].positions == {"5a": MINUS, "5b": MINUS}
    assert found[(TRAIN, "SA", "SD")].positions == {"5a": PLUS, "5b": MINUS}
    assert found[(TRAIN, "SB", "SD")].positions == {"5a": PLUS, "5b": PLUS}
    assert found[(TRAIN, "SB", "SC")].positions == {"5a": MINUS, "5b": PLUS}
    assert found[(TRAIN, "SA", "SC")].crossings == ("5a/5b",)
    reason = conflict(found[(TRAIN, "SA", "SC")], found[(TRAIN, "SB", "SD")])
    assert reason == "Båda går genom 5a/5b."


def test_routes_cross_a_crossing_without_a_switch_and_conflict_there() -> None:
    crossing = Switch(
        number="k1",
        type=SwitchType.CROSSING,
        node="K",
        paths=[SwitchPath(between=("ka", "kc")), SwitchPath(between=("kb", "kd"))],
    )
    model = build(
        "a:A-P ka:P-K b:B-Q kb:Q-K kc:K-R c:R-C kd:K-S d:S-D",
        switches=[crossing],
        signals=[
            signal("SA", HSI, "P", "a"),
            signal("SB", HSI, "Q", "b"),
            signal("SC", HSI, "R", "kc"),
            signal("SD", HSI, "S", "kd"),
        ],
        exits=dict.fromkeys("ABCD", "Grannby"),
    )
    found = routes(model)
    assert set(found) == {(TRAIN, "SA", "SC"), (TRAIN, "SB", "SD")}
    assert found[(TRAIN, "SA", "SC")].positions == {}
    assert conflict(found[(TRAIN, "SA", "SC")], found[(TRAIN, "SB", "SD")]) == "Båda går genom k1."


def test_a_y_switch_is_laid_like_any_switch() -> None:
    model = build(
        "a:V-W b:W-1 c:1-L d:1-R",
        switches=[switch("1", "b", "c", "d", type=SwitchType.Y)],
        signals=[signal("In", HSI, "W", "a")],
        exits={"V": "Västby"},
    )
    found = routes(model)
    assert found[(TRAIN, "In", "L")].positions == {"1": PLUS}
    assert found[(TRAIN, "In", "R")].positions == {"1": MINUS}


def turntable_station(level: Literal[1, 2, 3]) -> StationModel:
    """Level 1: track 4 with its stop point, a turntable, and a stall opposite track 4's ray.

    A -a- 4 -b- T(urntable) ... -s- Stall, and a third ray r to Stall 2 at 90 degrees.
    """
    table = Turntable(
        id="Vändskivan",
        node="T",
        tracks=[
            TurntableTrack(piece="b", angle=0.0),
            TurntableTrack(piece="s", angle=180.0),
            TurntableTrack(piece="r", angle=90.0),
        ],
    )
    return build(
        "a:A-4 b:4-T s:T-Stall r:T-Stall2",
        exits={"A": None},
        types={
            "4": NodeType.STOP_POINT,
            "T": NodeType.TURNTABLE,
            "Stall": NodeType.STOP_POINT,
            "Stall2": NodeType.STOP_POINT,
        },
        turntables=[table],
        level=level,
    )


def test_level_1_routes_go_track_to_track_and_over_the_turntable() -> None:
    """Level 1 without signals: every end the walk reaches, over stop points, and over the
    turntable where the bridge joins two opposite tracks (RS4, RS9)."""
    found = routes(turntable_station(level=1))
    assert set(found) == {
        (TRAIN, "A", "4"),
        (TRAIN, "A", "Vändskivan"),
        (TRAIN, "A", "Stall"),
        (TRAIN, "4", "A"),
        (TRAIN, "4", "Vändskivan"),
        (TRAIN, "4", "Stall"),
        (TRAIN, "Vändskivan", "4"),
        (TRAIN, "Vändskivan", "A"),
        (TRAIN, "Vändskivan", "Stall"),
        (TRAIN, "Vändskivan", "Stall2"),
        (TRAIN, "Stall", "Vändskivan"),
        (TRAIN, "Stall", "4"),
        (TRAIN, "Stall", "A"),
        (TRAIN, "Stall2", "Vändskivan"),
    }
    assert found[(TRAIN, "4", "Stall")].turntable == "b", "the bridge points at the first ray"
    assert found[(TRAIN, "Stall", "4")].turntable == "s"
    assert found[(TRAIN, "Vändskivan", "Stall2")].turntable == "r"


def test_at_level_2_the_turntable_ends_shunting_routes_and_starts_them() -> None:
    found = routes(turntable_station(level=2))
    assert (SHUNTING, "4", "Vändskivan") in found
    assert (SHUNTING, "Vändskivan", "Stall") in found and (SHUNTING, "Stall", "Vändskivan") in found
    assert (SHUNTING, "4", "Stall") not in found, "the turntable is turned between two routes"
    assert not any(k == TRAIN for (k, _, _) in found)


# --- choosing between paths (TKL53) -------------------------------------------------------


def two_crossovers() -> StationModel:
    """Two parallel tracks with two crossovers, 1/2 and 3/4, and two dwarfs M and N on track 2.

    S1 -a- 1 -b- 3 -c- E1                track 1
            \\x     \\y
    S2 -d- 2 -e1- M -e2- N -e3- 4 -f- E2   track 2

    S1 → E2 crosses over at 1/2 or at 3/4, two diverging switches either way, and both are
    600 mm. Only the one at 1/2 runs over e2, which the shunting route M → N needs.
    """
    return build(
        "a0:A0-A a:A-1 b:1-3 c:3-B c0:B-B0 x:1-2 y:3-4 "
        "d0:C0-C d:C-2 e1:2-M e2:M-N e3:N-4 f:4-D f0:D-D0",
        switches=[
            switch("1", "a", "b", "x"),
            switch("2", "e1", "d", "x"),
            switch("3", "b", "c", "y"),
            switch("4", "f", "e3", "y"),
        ],
        signals=[
            signal("S1", HSI, "A", "a0"),
            signal("S2", HSI, "C", "d0"),
            signal("E1", HSI, "B", "c"),
            signal("E2", HSI, "D", "f"),
            signal("M", DVSI, "M", "e1"),
            signal("N", DVSI, "N", "e2"),
        ],
        levers=[
            Lever(id="1/2", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS, "2": MINUS}),
            Lever(id="3/4", plus={"3": PLUS, "4": PLUS}, minus={"3": MINUS, "4": MINUS}),
        ],
        lengths={"b": 200.0, "y": 200.0},
    )


def test_of_two_paths_the_one_with_fewest_diverging_switches_is_taken() -> None:
    """TKL53, before the length: the loop over track 1 is longer but goes straight."""
    model = build(
        "a:V-W b:W-1 c:1-P c2:P-Q c3:Q-2 d:1-2 g:2-Z j:Z-O",
        switches=[switch("1", "b", "c", "d"), switch("2", "g", "c3", "d")],
        signals=[signal("In", HSI, "W", "a"), signal("Ut", HSI, "Z", "g")],
        exits={"V": "Västby", "O": "Östby"},
    )
    paths = alternatives(model)[(TRAIN, "In", "Ut")]
    assert [p.diverging for p in paths] == [0, 2]
    assert paths[0].length > paths[1].length
    assert derive(model)[0].positions == {"1": PLUS, "2": PLUS}


def test_capacity_preference_leaves_more_movements_and_ignores_the_lists_order() -> None:
    """Ported: "capacity preference retains more physical movements, independent of duplicate
    controls" (cda-tkl test/route-selection.test.mjs). Of two equal paths the one that leaves
    the shunting route M → N free is taken, even when it is the longer one; shuffling the
    model's lists changes nothing."""
    model = two_crossovers()
    first, second = alternatives(model)[(TRAIN, "S1", "E2")]
    assert first.diverging == second.diverging == 2
    assert first.positions == {"1": PLUS, "2": PLUS, "3": MINUS, "4": MINUS}
    shunt = routes(model)[(SHUNTING, "M", "N")]
    assert conflict(first, shunt) is None and conflict(second, shunt) is not None
    longer = model.model_copy(
        update={
            "pieces": [
                p.model_copy(update={"geometry": [(0.0, 0.0), (300.0, 0.0)]}) if p.id == "b" else p
                for p in model.pieces
            ]
        }
    )
    chosen = alternatives(longer)[(TRAIN, "S1", "E2")][0]
    assert chosen.length > alternatives(longer)[(TRAIN, "S1", "E2")][1].length
    assert chosen.positions["3"] == MINUS
    rng = random.Random(83)
    for _ in range(5):
        shuffled = model.model_copy(
            update={
                name: rng.sample(getattr(model, name), len(getattr(model, name)))
                for name in ("nodes", "pieces", "switches", "signals", "levers")
            }
        )
        assert alternatives(shuffled)[(TRAIN, "S1", "E2")][0].steps == first.steps


def test_paths_can_be_filtered_by_locks_and_occupied_track() -> None:
    """Ported: "alternative search obeys locks and excludes occupied detector blocks"
    (cda-tkl test/route-selection.test.mjs)."""
    model = two_crossovers().model_copy(
        update={
            "track_circuits": [
                TrackCircuit(name="T1", pieces=["a", "b", "c"]),
                TrackCircuit(name="X12", pieces=["x"]),
                TrackCircuit(name="X34", pieces=["y"]),
                TrackCircuit(name="T2", pieces=["d", "e1", "e2", "e3", "f"]),
            ]
        }
    )
    paths = alternatives(model)[(TRAIN, "S1", "E2")]
    free = [p for p in paths if not hindrances(p, set(), {"1": PLUS})]
    assert len(free) == 1 and free[0].positions["3"] == MINUS
    assert [p for p in paths if not hindrances(p, {"X34"}, {"1": PLUS})] == []
    assert hindrances(paths[0], {"X34", "X12"}, {"1": PLUS, "3": PLUS}) != []


# --- conflicts ----------------------------------------------------------------------------


def test_conflicts_count_detectors_couplings_crossings_and_signals_at_stop() -> None:
    """Ported: "resource compatibility includes detector aliases, companion locks, crossings and
    stop guards" (cda-tkl test/route-selection.test.mjs)."""
    found = routes(provby())
    track_1, track_2 = found[(TRAIN, "In", "12")], found[(TRAIN, "In2", "21")]
    assert conflict(track_1, track_2) is None, "different tracks, different switches' circuits"
    assert conflict(track_1, found[(TRAIN, "12", "Ut2")]) is None, "a continuation"
    assert conflict(track_1, found[(TRAIN, "In", "22")]) == "Båda går över spårledningen Vx1."
    assert conflict(found[(TRAIN, "11", "Ut")], found[(TRAIN, "21", "Ut")]) is not None
    # Two circuits on one detector are one circuit.
    aliases = {"Spår 1": "LocoNet:5", "Vx2": "LocoNet:5"}
    assert conflict(track_1, track_2, aliases) == "Båda går över spårledningen Vx2."
    # Coupled switches: the lever makes 1 follow 2, so the two routes need 1 both ways.
    lever = Lever(id="1/2", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS, "2": MINUS})
    coupled = routes(provby(levers=[lever]))
    assert (
        conflict(coupled[(TRAIN, "In", "12")], coupled[(TRAIN, "In2", "21")])
        == "De behöver växel 1 i olika lägen."
    )


def test_a_route_that_clears_a_signal_another_needs_at_stop_conflicts() -> None:
    found = routes(provby())
    into_track_2 = found[(TRAIN, "In", "22")]
    shunt = found[(SHUNTING, "D", "22")]
    assert "D" in into_track_2.passed
    assert conflict(into_track_2, shunt) is not None
    outward = found[(SHUNTING, "21", "Ut")]
    assert "21" in into_track_2.guards
    assert conflict(into_track_2, outward) is not None


# --- chains and splitting them (TKL53, route-sections) ------------------------------------


def _sections() -> StationModel:
    """A straight track through six combined signals in a row, S0 to S5."""
    nodes, pieces = "ABCDEFG", "abcdef"
    spec = " ".join(f"{p}:{a}-{b}" for p, a, b in zip(pieces, nodes, nodes[1:], strict=False))
    return build(
        "s:X-A " + spec + " t:G-Y",
        signals=[
            signal(f"S{i}", HDVSI, node, piece)
            for i, (node, piece) in enumerate(zip(nodes, "s" + pieces, strict=True))
        ],
    )


def test_a_train_traverses_four_joined_sections() -> None:
    """Ported: "a train traverses four joined sections without holding or losing the earlier
    reservations" (cda-tkl test/network.test.mjs): S0 → S4 is laid as four routes."""
    found = derive(_sections())
    whole = chains(found, TRAIN, "S0", "S4")
    assert [[r.name for r in c] for c in whole] == [["S0 → S1", "S1 → S2", "S2 → S3", "S3 → S4"]]
    assert chains(found, SHUNTING, "S0", "S4")[0][-1].end.name == "S4"


def test_a_chain_splits_only_where_one_route_ends_and_the_next_begins() -> None:
    """Ported: "partial cancellation works at reviewed boundaries in both directions for main and
    shunt routes" and "an alternative path is split only where both reviewed parts match that
    actual path" (cda-tkl test/network.test.mjs)."""
    found = derive(_sections())
    for kind in (TRAIN, SHUNTING):
        (whole,) = chains(found, kind, "S0", "S3")
        parts = split(whole, "S1")
        assert parts is not None
        head, tail = parts
        assert [r.name for r in head] == ["S0 → S1"]
        assert [s for r in head + tail for s in r.steps] == [s for r in whole for s in r.steps]
        assert split(whole, "S0") is None and split(whole, "S3") is None, "not at its own ends"
        assert split(whole, "S5") is None, "not where the chain does not go"
    track_2 = chains(derive(provby()), TRAIN, "In", "Ut2")
    assert [[r.name for r in c] for c in track_2] == [
        ["In → 12", "12 → Ut2"],
        ["In → 22", "22 → Ut2"],
    ]
    assert split(track_2[1], "D") is None, "the dwarf is passed, not a boundary"


def test_derive_does_not_depend_on_the_order_of_the_model_s_lists() -> None:
    model = provby()
    rng = random.Random(4)
    shuffled = model.model_copy(
        update={
            name: rng.sample(getattr(model, name), len(getattr(model, name)))
            for name in ("nodes", "pieces", "switches", "signals", "track_circuits")
        }
    )
    assert derive(shuffled) == derive(model)
