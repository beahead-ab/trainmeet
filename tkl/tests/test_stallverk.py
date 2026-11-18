"""Ställverket at level 1–2 (#84) on small made-up stations: routes, levers, release, train
numbers and exits (STV-01, STV-03, STV-06, STV-14–STV-16, STV-24, STV-29, STV-33, STV-52,
STV-54, TKL28, TKL53, TKL104).

The tests marked "Ported" carry an old cda-tkl test's behaviour; the old test is named. Nothing
here names a station (RS13).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.station import ExitSignalAspect
from contracts.station_model import (
    Address,
    Lever,
    LineExit,
    NodeType,
    SignalType,
    StationModel,
    Switch,
    SwitchControl,
    SwitchPath,
    SwitchType,
    TrackCircuit,
)
from contracts.tkl import (
    TklAspect,
    TklInterlocking,
    TklNumberColour,
    TklPieceState,
    TklReportKind,
)
from tkl.stallverk import Interlocking, plant_of
from tkl.stallverk.plant import MINUS_SIGN
from tkl.standard import RouteKind
from tkl.tests.provstation import MINUS, PLUS, build, provby, signal, switch

TRAIN, SHUNTING = RouteKind.TRAIN, RouteKind.SHUNTING
HSI, HDVSI, DVSI = SignalType.HSI, SignalType.HDVSI, SignalType.DVSI
NOON = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def made(model: StationModel) -> Interlocking:
    return Interlocking(plant_of(model), now=lambda: NOON)


def state(it: Interlocking) -> TklInterlocking:
    return it.view()


def route_id(it: Interlocking, start: str, end: str) -> int:
    return next(r.id for r in it.view().routes if (r.start, r.end) == (start, end))


def yes(outcome: Any) -> Any:
    assert outcome.accepted, outcome.message
    return outcome


def no(outcome: Any, *said: str) -> None:
    assert not outcome.accepted, outcome.message
    for text in said:
        assert text in outcome.message, outcome.message


def locked(it: Interlocking) -> set[str]:
    return set(it.view().pieces) - occupied(it)


def occupied(it: Interlocking) -> set[str]:
    return {p for p, s in it.view().pieces.items() if s.state == TklPieceState.OCCUPIED}


# --- stations for the tests ---------------------------------------------------------------


def siding() -> StationModel:
    """A combined signal H before a siding that ends at a buffer stop.

    P -a- Q(H) -b- R -c- Stopp       track circuits T1 = a, T2 = b + c
    """
    return build(
        "a:P-Q b:Q-R c:R-Stopp",
        signals=[signal("H", HDVSI, "Q", "a")],
        track_circuits=[
            TrackCircuit(name="T1", pieces=["a"]),
            TrackCircuit(name="T2", pieces=["b", "c"]),
        ],
    )


def two_paths() -> StationModel:
    """Two ways from A to B: straight through 1 and 2, or over the loop on their diverging
    legs. No track circuits: the pieces between switches, signals and block boundaries are
    sections of their own; a joint (M) joins d and e into one.

    Q -z- J(A) -a- 1 -b1- K -b2- L -b3- 2 -c- E(B) -y- F
                    \\-d- M -e-------------/
    """
    return build(
        "z:Q-J a:J-1 b1:1-K b2:K-L b3:L-2 c:2-E y:E-F d:1-M e:M-2",
        switches=[switch("1", "a", "b1", "d"), switch("2", "c", "b3", "e")],
        signals=[signal("A", HSI, "J", "z"), signal("B", HSI, "E", "c")],
        types={"K": NodeType.BLOCK_BOUNDARY, "L": NodeType.BLOCK_BOUNDARY},
    )


def crossover() -> StationModel:
    """Two parallel tracks and a crossover between them, 95 on track 1 and 96 on track 2. 95 to
    diverging drags 96 along, and 96 to straight drags 95, so they never lie crossed (TKL104).
    161 on a third line drags 153 on a fourth to straight when it goes diverging.

    Q1 -z1- W1(A1) -a1- 95 -b1- E1(B1) -y1- F1
                         \\x
    Q2 -z2- W2(A2) -a2- 96 -b2- E2(B2) -y2- F2
    Q3 -z3- W3(A3) -a3- 161 -b3- E3(B3) -y3- F3,  161 -x3- X3
    Q4 -z4- W4(A4) -a4- 153 -b4- E4(B4) -y4- F4,  153 -x4- X4
    """
    return build(
        "z1:Q1-W1 a1:W1-s95 b1:s95-E1 y1:E1-F1 z2:Q2-W2 a2:W2-s96 b2:s96-E2 y2:E2-F2 x:s95-s96 "
        "z3:Q3-W3 a3:W3-s161 b3:s161-E3 y3:E3-F3 x3:s161-X3 "
        "z4:Q4-W4 a4:W4-s153 b4:s153-E4 y4:E4-F4 x4:s153-X4",
        switches=[
            switch("95", "a1", "b1", "x", node="s95"),
            switch("96", "b2", "a2", "x", node="s96"),
            switch("161", "a3", "b3", "x3", node="s161"),
            switch("153", "a4", "b4", "x4", node="s153"),
        ],
        signals=[
            signal("A1", HSI, "W1", "z1"),
            signal("B1", HSI, "E1", "b1"),
            signal("A2", HSI, "W2", "z2"),
            signal("B2", HSI, "E2", "b2"),
            signal("A3", HSI, "W3", "z3"),
            signal("B3", HSI, "E3", "b3"),
            signal("A4", HSI, "W4", "z4"),
            signal("B4", HSI, "E4", "b4"),
        ],
        levers=[
            Lever(id="95", plus={"95": PLUS}, minus={"95": MINUS, "96": MINUS}),
            Lever(id="96", plus={"96": PLUS, "95": PLUS}, minus={"96": MINUS}),
            Lever(id="161", plus={"161": PLUS}, minus={"161": MINUS, "153": PLUS}),
        ],
    )


def level_1() -> StationModel:
    """Level 1, without signals: a line exit, a switch and two tracks to stop points.

    A1 -p0- S -p1- Spår 1 -p3- Stopp 1
             \\p2- Spår 2 -p4- Stopp 2
    """
    return build(
        "p0:A1-S p1:S-Sp1 p3:Sp1-B1 p2:S-Sp2 p4:Sp2-B2",
        switches=[switch("1", "p0", "p1", "p2", node="S")],
        exits={"A1": "Grannby"},
        types={"Sp1": NodeType.STOP_POINT, "Sp2": NodeType.STOP_POINT},
        level=1,
    )


# --- routes: set and release (STV-01, STV-14) ----------------------------------------------


def test_set_and_release_a_train_route() -> None:
    it = made(provby())
    set_ = yes(it.set_route("In", "22"))
    shown = state(it)
    [route] = shown.routes
    assert (route.kind.value, route.start, route.end, route.id) == ("train", "In", "22", set_.route)
    assert [s.section for s in route.sections] == ["Vx1", "Spår 2"]
    assert route.positions == {"1": MINUS} and shown.switches["1"].position == MINUS
    assert shown.switches["1"].routes == [route.id]
    assert shown.signals["In"].aspect == TklAspect.PROCEED
    assert shown.signals["D"].aspect == TklAspect.PROCEED, "a passed signal shows proceed"
    assert shown.signals["22"].end and shown.signals["22"].aspect == TklAspect.STOP
    assert locked(it) == {"b", "d", "f1", "f2"}
    assert {p.state for p in shown.pieces.values()} == {TklPieceState.TRAIN}
    yes(it.release(route.id))
    shown = state(it)
    assert shown.routes == [] and shown.pieces == {}
    assert shown.signals["In"].aspect == TklAspect.STOP
    assert shown.switches["1"].position == MINUS, "the switch stays where it was laid"
    assert shown.switches["1"].routes == []


def test_unknown_names_are_a_no_never_a_guess() -> None:
    it = made(provby())
    no(it.set_route("Nowhere", "12"), "Nowhere")
    no(it.set_route("In", "Nowhere"), "Nowhere")
    no(it.set_route("In", "In"))
    no(it.set_route("12", "In"), "Ingen väg")
    no(it.lay_lever("99"), "finns inte")
    no(it.release(42), "finns inte längre")
    no(it.step(42), "finns inte längre")
    no(it.put_train("41", section="Nowhere"), "finns inte")
    no(it.put_train("41", exit="Nowhere"), "finns inte")
    no(it.remove_train(42), "finns inte")
    assert state(it).revision == 0, "a no changes nothing"


def test_ported_a_repeated_request_never_undoes_the_first() -> None:
    """Ported: 'with an intent a repeated request never undoes the first: build never cancels,
    cancel never builds' (cda-tkl test/engine.test.mjs)."""
    it = made(provby())
    first = yes(it.set_route("In", "12"))
    again = yes(it.set_route("In", "12"))
    assert again.route == first.route and "ligger redan" in again.message
    assert len(state(it).routes) == 1
    yes(it.release(first.route))
    no(it.release(first.route), "Ingenting löstes ut")
    assert state(it).routes == [], "a repeated release lays nothing"


def test_ported_conflicting_routes_refuse_and_independent_routes_coexist() -> None:
    """Ported: 'conflicting routes refuse; independent routes coexist' (engine.test.mjs)."""
    it = made(provby())
    yes(it.set_route("In", "12"))
    no(it.set_route("In2", "11"), "Spår 1", "låst i vägen In → 12")
    no(it.set_route("11", "Ut"), "låst i vägen In → 12")
    yes(it.set_route("In2", "21"))
    assert len(state(it).routes) == 2


def test_refused_through_a_locked_switch_and_a_locked_part() -> None:
    it = made(provby())
    yes(it.set_route("In", "12"))
    # Through the switch the other way: Vx1 is the same track circuit, and switch 1 is locked.
    no(it.set_route("21", "Ut"), "Vx1 är låst")
    assert state(it).switches["1"].position == PLUS


# --- chains and the fewest diverging switches (STV-03, TKL53) ----------------------------------


def test_a_chain_through_the_signals_between() -> None:
    it = made(provby())
    laid = yes(it.set_route("In", "Ut2"))
    assert "genom 12" in laid.message and "2 delar" in laid.message
    first, second = state(it).routes
    assert (first.start, first.end, second.start, second.end) == ("In", "12", "12", "Ut2")
    assert first.chain == second.chain == first.id
    assert state(it).signals["12"].aspect == TklAspect.PROCEED
    assert state(it).signals["12"].end, "the end of one part and the start of the next"
    again = yes(it.set_route("In", "Ut2"))
    assert again.route == first.id and len(state(it).routes) == 2
    # Each part is an ordinary route and is released by itself.
    yes(it.release(second.id))
    assert [(r.start, r.end) for r in state(it).routes] == [("In", "12")]


def test_the_chain_with_the_fewest_diverging_switches_that_can_be_set() -> None:
    """TKL53: through 12 on track 1 (no diverging switch) before 22 on track 2 (two). With
    track 1 occupied, the chain through track 2 is the one that can be set."""
    it = made(provby())
    yes(it.set_route("In", "Ut2"))
    assert [r.end for r in state(it).routes] == ["12", "Ut2"]
    it = made(provby())
    yes(it.put_train("9103", section="Spår 1"))
    yes(it.set_route("In", "Ut2"))
    assert [r.end for r in state(it).routes] == ["22", "Ut2"]


def test_ported_alternative_search_obeys_locks_and_occupied_sections() -> None:
    """Ported: 'alternative search obeys locks and excludes occupied detector blocks'
    (cda-tkl test/route-selection.test.mjs). Of A → B's two paths the straight one comes
    first; when it is occupied, the loop is set; when both are, the reason is the first's."""
    it = made(two_paths())
    [straight_way], [loop_way] = it.plant.candidates(TRAIN, "A", "B")
    assert [s for s, _ in straight_way.sections] == ["a", "b1", "b2", "b3", "c"]
    assert [s for s, _ in loop_way.sections] == ["a", "d", "c"], "d and e join at the joint"
    yes(it.set_route("A", "B"))
    [straight] = state(it).routes
    assert straight.positions == {"1": PLUS, "2": PLUS}
    yes(it.release(straight.id))
    yes(it.put_train("9103", section="b2"))
    yes(it.set_route("A", "B"))
    [loop] = state(it).routes
    assert loop.positions == {"1": MINUS, "2": MINUS}
    yes(it.release(loop.id))
    yes(it.put_train("9104", section="d"))
    no(it.set_route("A", "B"), "Spårdelen b2 är belagd av tåg 9103")
    # A train next to a switch keeps it where it lies.
    no(it.lay_lever("1", PLUS), "Växel 1 kan inte läggas om: spårdelen d är belagd")
    assert state(it).switches["1"].position == MINUS


# --- train routes and shunting routes (STV-14, STV-24, TKL28) ---------------------------------


def test_a_train_route_where_there_is_one_and_a_shunting_route_on_request() -> None:
    """STV-24: both kinds between H and the buffer stop; a train route is set, and with the
    kind asked for (one click more on the start) a shunting route, shown as shunting."""
    it = made(siding())
    assert [k.value for k in it.targets("H").kinds] == ["train", "shunting"]
    yes(it.set_route("H", "Stopp"))
    [route] = state(it).routes
    assert route.kind.value == "train" and state(it).signals["H"].aspect == TklAspect.PROCEED
    yes(it.release(route.id))
    yes(it.set_route("H", "Stopp", SHUNTING))
    [route] = state(it).routes
    assert route.kind.value == "shunting" and state(it).signals["H"].aspect == TklAspect.SHUNT
    assert {p.state for p in state(it).pieces.values()} == {TklPieceState.SHUNTING}


def test_a_shunting_route_may_go_towards_an_occupied_track_a_train_route_may_not() -> None:
    it = made(siding())
    yes(it.put_train("9103", section="T2"))
    no(it.set_route("H", "Stopp", TRAIN), "T2 är belagd av tåg 9103")
    no(it.set_route("H", "Stopp"), "belagd")
    yes(it.set_route("H", "Stopp", SHUNTING))


# --- levers (STV-01, STV-52, TKL104) ---------------------------------------------------------


def test_ported_a_lever_lays_its_coupled_and_reversed_switches() -> None:
    """Ported: 'manual command expands coupled switches and respects source inversion'
    (engine.test.mjs). Switch 2 lies reversed on the lever: + is 1+ and 2 diverging."""
    model = provby(
        levers=[Lever(id="1/2", plus={"1": PLUS, "2": MINUS}, minus={"1": MINUS, "2": PLUS})]
    )
    it = made(model)
    assert state(it).levers["1/2"] == PLUS
    assert (state(it).switches["1"].position, state(it).switches["2"].position) == (PLUS, MINUS)
    said = yes(it.lay_lever("1"))
    assert f"Spaken 1/2 lagd i {MINUS_SIGN}" in said.message
    assert (state(it).switches["1"].position, state(it).switches["2"].position) == (MINUS, PLUS)
    assert state(it).levers["1/2"] == MINUS
    yes(it.lay_lever("1/2", PLUS))
    assert (state(it).switches["1"].position, state(it).switches["2"].position) == (PLUS, MINUS)
    assert "ligger redan" in yes(it.lay_lever("2", PLUS)).message


def test_a_switch_drags_another_so_that_they_never_lie_crossed() -> None:
    """TKL104: 95 to diverging drags 96, 96 to straight drags 95; 95 to straight and 96 to
    diverging move nothing else. 95 diverging with 96 straight is crossed and never happens."""
    it = made(crossover())

    def where() -> tuple[str, str]:
        shown = state(it).switches
        return (shown["95"].position or "?", shown["96"].position or "?")

    assert where() == ("+", "+")
    assert f"drar med 96 {MINUS_SIGN}" in yes(it.lay_lever("95")).message
    assert where() == ("-", "-")
    assert "drar med 95 +" in yes(it.lay_lever("96")).message
    assert where() == ("+", "+")
    yes(it.lay_lever("96", MINUS))
    assert where() == ("+", "-")
    yes(it.lay_lever("95", PLUS))
    assert where() == ("+", "-")
    for _ in range(3):
        for lever in ("95", "96", "96", "95", "95"):
            yes(it.lay_lever(lever))
            assert where() != ("-", "+")


def test_a_lever_is_refused_when_a_switch_that_must_follow_is_locked() -> None:
    """STV-52: 161 to diverging drags 153 to straight. With 153 locked diverging in a route on
    its own line, 161 may not go over; its own switch alone is free."""
    it = made(crossover())
    yes(it.set_route("A4", "X4"))
    assert state(it).switches["153"].position == MINUS
    no(it.lay_lever("161", MINUS), "Växel 153 är låst i vägen A4 → X4 och kan inte följa med")
    assert state(it).switches["161"].position == PLUS
    no(it.lay_lever("153"), "Växel 153 är låst i vägen A4 → X4")


def test_ported_same_position_locks_are_shared() -> None:
    """Ported: 'same-position coupling is shared without moving an already locked turnout'
    (engine.test.mjs). A1 → B1 locks 95 straight; A2 → B2 lays 96 straight and so drags and
    locks 95 straight as well. Both are set, and 95 stays locked until both are released."""
    it = made(crossover())
    one = yes(it.set_route("A1", "B1")).route
    two = yes(it.set_route("A2", "B2")).route
    assert state(it).switches["95"].routes == [one, two]
    assert state(it).switches["95"].protection, "two locks 95 without running over it"
    yes(it.release(one))
    assert state(it).switches["95"].routes == [two]
    no(it.lay_lever("95"), "låst")
    yes(it.release(two))
    yes(it.lay_lever("95"))


def test_a_route_lays_the_lever_with_its_coupled_switch() -> None:
    """STV-52: a route lays and locks the coupled switches too."""
    it = made(crossover())
    yes(it.set_route("A1", "B2"))
    [route] = state(it).routes
    assert route.positions == {"95": MINUS, "96": MINUS}
    assert state(it).levers == {"95": MINUS, "96": MINUS, "161": PLUS, "153": PLUS}
    no(it.lay_lever("96"), "låst")


def test_manual_planned_and_not_laid_switches_are_never_laid() -> None:
    model = provby()
    model = model.model_copy(
        update={
            "switches": [
                model.switches[0].model_copy(update={"control": SwitchControl.MANUAL}),
                model.switches[1].model_copy(update={"control": SwitchControl.PLANNED}),
            ]
        }
    )
    it = made(model)
    no(it.lay_lever("1"), "läggs för hand")
    no(it.lay_lever("2"), "planerad")
    assert state(it).switches["1"].position is None, "TKL does not know where it lies"
    no(it.set_route("In", "12"), "Inga vägar")


# --- Kör, sectional release, arrival and the train number (STV-06, STV-15, STV-16, STV-29) ----


def test_kor_steps_the_train_number_and_releases_behind_it_section_by_section() -> None:
    it = made(provby())
    yes(it.put_train("41", exit="V"))
    route = yes(it.set_route("In", "22")).route
    shown = state(it)
    assert [(n.colour, n.exit, n.section) for n in shown.numbers] == [
        (TklNumberColour.RED, "V", None),
        (TklNumberColour.GREEN, None, "Spår 2"),
    ], "red where the train is, green in the route's last section (STV-21)"
    assert shown.routes[0].train == shown.trains[0].id
    yes(it.step(route))
    shown = state(it)
    assert shown.trains[0].section == "Vx1" and shown.signals["In"].aspect == TklAspect.STOP
    assert shown.signals["D"].aspect == TklAspect.PROCEED, "not passed yet (STV-19)"
    assert occupied(it) == {"b", "c", "d"}, "the whole track circuit"
    assert locked(it) == {"f1", "f2"}
    assert shown.switches["1"].routes == [route]
    said = yes(it.step(route))
    assert "Vx1 utlöst" in said.message
    shown = state(it)
    assert [s.released for s in shown.routes[0].sections] == [True, False]
    assert shown.switches["1"].routes == [], "released with its section"
    assert shown.signals["D"].aspect == TklAspect.STOP
    assert occupied(it) == {"f1", "f2"}
    assert [n.colour for n in shown.numbers] == [TklNumberColour.RED]
    # Vx1 is free again: a route through it can be set behind the train.
    yes(it.set_route("11", "Ut"))
    no(it.step(route), "står vid målet 22")


def test_ported_occupancy_holds_the_route_and_never_frees_anything() -> None:
    """Ported: 'occupied block holds route and prevents releasing locks until clear and
    stopped' (engine.test.mjs). STV-16: a train in the route holds it, and only the buttons
    free anything; numbers put and taken away elsewhere free nothing."""
    it = made(provby())
    yes(it.put_train("41", exit="V"))
    route = yes(it.set_route("In", "12")).route
    yes(it.step(route))
    no(it.release(route), "Tåg 41 är i vägen In → 12", "nödutlös")
    no(it.remove_train(state(it).trains[0].id), "är i vägen")
    yes(it.put_train("9103", section="Spår 2"))
    yes(it.remove_train(state(it).trains[1].id))
    assert locked(it) == {"e"} and occupied(it) == {"b", "c", "d"}
    yes(it.step(route))
    assert [r.id for r in state(it).routes] == [route], "at the end the route is still set"
    assert locked(it) == set() and occupied(it) == {"e"}
    assert state(it).signals["12"].end
    yes(it.release(route))
    assert occupied(it) == {"e"}, "the train number stays"


def test_emergency_release_is_confirmed_and_logged() -> None:
    it = made(provby())
    yes(it.put_train("41", exit="V"))
    route = yes(it.set_route("In", "12")).route
    yes(it.step(route))
    no(it.emergency_release(route, False), "Bekräfta")
    assert state(it).routes
    said = yes(it.emergency_release(route, True))
    assert "Nödutlösning av vägen In → 12, bekräftad" in said.message
    assert "Tåg 41 står kvar i spårledningen Vx1" in said.message
    shown = state(it)
    assert shown.routes == [] and shown.trains[0].section == "Vx1"
    assert shown.events[0].text == said.message and shown.events[0].at == NOON


def test_arrival_at_levels_1_and_2_is_a_button() -> None:
    """STV-16: Ankommit at the route's end releases it and reports the arrival, with the
    track the train stands on; before that it is a no."""
    it = made(provby())
    yes(it.put_train("41", call="c41", exit="O"))
    route = yes(it.set_route("In2", "21")).route
    no(it.arrive(route), "Inget tåg har inte kommit fram")
    yes(it.step(route))
    no(it.arrive(route), "Tåg 41 har inte kommit fram till 21")
    yes(it.step(route))
    arrived = yes(it.arrive(route))
    assert "Tåg 41 har kommit fram till spår 2" in arrived.message
    [report] = arrived.reports
    assert (report.kind, report.train_number, report.call, report.track) == (
        TklReportKind.ARRIVED,
        "41",
        "c41",
        "2",
    )
    assert state(it).routes == [] and state(it).trains[0].section == "Spår 2"


def test_ported_a_train_on_the_line_comes_in_stops_and_runs_on_out() -> None:
    """Ported: 'ett tåg på linjen kör in när signalen visar kör, stannar på spåret, tågvägen
    löses upp vid ankomst och tåget kör vidare ut' (cda-tkl test/simulated-trains.test.mjs).
    Without detection the buttons move it (STV-15)."""
    it = made(provby())
    yes(it.put_train("401", exit="V"))
    no(it.put_train("402", exit="V"), "redan ett tåg på linjen vid V")
    entry = yes(it.set_route("In", "12")).route
    yes(it.step(entry))
    yes(it.step(entry))
    yes(it.arrive(entry))
    no(
        it.set_route("In", "12"),
        "Spår 1 är belagd av tåg 401",
    )
    out = yes(it.set_route("12", "Ut2"))
    assert [r.kind for r in out.reports] == [TklReportKind.EXIT_SIGNAL]
    assert out.reports[0].aspect == ExitSignalAspect.PROCEED
    assert out.reports[0].train_number == "401"
    yes(it.step(out.route))
    left = yes(it.step(out.route))
    assert "Tåg 401 har lämnat mot O" in left.message
    [departed] = [r for r in left.reports if r.kind == TklReportKind.DEPARTED]
    assert (departed.train_number, departed.exit) == ("401", "O")
    assert state(it).trains == [] and state(it).routes == []


def test_a_train_runs_through_a_chain_and_leaves() -> None:
    """STV-03 and STV-06: on a chain the train takes the next part from the end of the one
    before, which is then done; the green number stands in the last section of each part."""
    it = made(provby())
    yes(it.put_train("41", exit="V"))
    yes(it.set_route("In", "Ut2"))
    first, second = (r.id for r in state(it).routes)
    greens = [n.section for n in state(it).numbers if n.colour == TklNumberColour.GREEN]
    assert greens == ["Spår 1", "Vx2"]
    yes(it.step(first))
    yes(it.step(first))
    entered = yes(it.step(first))
    assert "Tåg 41 kör 12 → Ut2" in entered.message
    assert [r.id for r in state(it).routes] == [second]
    left = yes(it.step(second))
    assert any(r.kind == TklReportKind.DEPARTED for r in left.reports)
    assert state(it).routes == [] and state(it).trains == []


def test_depart_is_the_operators_button_for_a_route_out() -> None:
    it = made(provby())
    yes(it.put_train("41", section="Spår 1"))
    inward = yes(it.set_route("In", "22")).route
    no(it.depart(inward), "går inte ut på linjen")
    out = yes(it.set_route("12", "Ut2")).route
    left = yes(it.depart(out))
    assert left.reports[0].kind == TklReportKind.DEPARTED
    assert [t.number for t in state(it).trains] == []
    assert [r.id for r in state(it).routes] == [inward]


def test_kor_needs_one_train_at_the_start() -> None:
    it = made(provby())
    route = yes(it.set_route("In", "12")).route
    no(it.step(route), "Inget tåg står vid In")
    yes(it.put_train(None, exit="V"))
    said = yes(it.step(route))
    assert said.message.startswith("Tåget utan nummer kör In → 12")


def test_ported_trains_are_put_only_on_a_free_track_or_line_with_a_valid_number() -> None:
    """Ported: 'simulatorn ställer bara tåg på en fri linje eller ett fritt spår, med giltigt
    nummer' (simulated-trains.test.mjs)."""
    it = made(provby())
    yes(it.put_train("401", exit="V"))
    no(it.put_train("403", exit="V"), "redan ett tåg")
    no(it.put_train("401", exit="O"), "Tåg 401 står redan")
    no(it.put_train("405", section="Okänt"), "finns inte")
    no(it.put_train("405"), "Ange ett spår eller en utfart")
    yes(it.set_route("In2", "11"))
    no(it.put_train("405", section="Spår 1"), "låst i vägen In2 → 11")
    yes(it.put_train("405", section="Spår 2"))
    no(it.put_train("407", section="Spår 2"), "redan ett tåg")
    # A section on the line outside the entry signal is the exit's box.
    yes(it.remove_train(state(it).trains[0].id))
    yes(it.put_train("409", section="Infart V"))
    assert state(it).trains[-1].exit == "V"


def test_ported_reset_releases_every_route_and_keeps_switches_and_numbers() -> None:
    """Ported: 'explicit panel reset releases occupied routes after fresh STOP, preserving
    detectors and turnout positions' (engine.test.mjs). With trains, the numbers go too."""
    it = made(provby())
    yes(it.put_train("41", exit="V"))
    route = yes(it.set_route("In", "22")).route
    yes(it.step(route))
    no(it.reset(False), "Bekräfta")
    said = yes(it.reset(True))
    assert "1 vägar utlösta" in said.message
    shown = state(it)
    assert shown.routes == [] and shown.switches["1"].position == MINUS
    assert [t.section for t in shown.trains] == ["Vx1"]
    yes(it.reset(True, trains=True))
    assert state(it).trains == []


# --- resources (cda-tkl's compatible) -----------------------------------------------------------


def test_ported_resource_compatibility_detector_aliases_companions_crossings() -> None:
    """Ported: 'resource compatibility includes detector aliases, companion locks, crossings
    and stop guards' (route-selection.test.mjs)."""
    # Two track circuits on one detector are one for locking.
    model = provby(
        track_circuits=[
            TrackCircuit(name="Spår 1", pieces=["e"], detection=Address(number=7)),
            TrackCircuit(name="Spår 2", pieces=["f1", "f2"], detection=Address(number=7)),
            TrackCircuit(name="Vx1", pieces=["b", "c", "d"]),
            TrackCircuit(name="Vx2", pieces=["g", "h", "i"]),
        ]
    )
    it = made(model)
    yes(it.set_route("In", "12"))
    no(it.set_route("D", "22"), "Spår 2 är låst i vägen In → 12")
    # A companion: the switch a route locks on its lever without running over it.
    it = made(crossover())
    yes(it.set_route("A2", "B2"))
    no(it.lay_lever("95"), "Växel 95 är låst i vägen A2 → B2")
    no(it.set_route("A1", "B2"), "låst i vägen A2 → B2")
    # A crossing without a switch: two routes over it never at once.
    crossing = build(
        "zn:QN-N n1:N-K s1:K-S ys:S-FS zw:QW-W w1:W-K e1:K-E ye:E-FE",
        switches=[
            Switch(
                number="k1",
                type=SwitchType.CROSSING,
                node="K",
                paths=[SwitchPath(between=("n1", "s1")), SwitchPath(between=("w1", "e1"))],
            )
        ],
        signals=[
            signal("N1", HSI, "N", "zn"),
            signal("S1", HSI, "S", "s1"),
            signal("W1", HSI, "W", "zw"),
            signal("E1", HSI, "E", "e1"),
        ],
    )
    it = made(crossing)
    yes(it.set_route("N1", "S1"))
    no(it.set_route("W1", "E1"), "Korsningen k1 är låst i vägen N1 → S1")
    # A guard: the end signal of one route may start the next (a continuation), never more.
    it = made(provby())
    yes(it.set_route("12", "Ut2"))
    yes(it.set_route("In", "12"))
    assert state(it).signals["12"].aspect == TklAspect.PROCEED


# --- exits: STV-33 and STV-54 ---------------------------------------------------------------


def test_a_train_route_ends_at_the_exit_and_no_further() -> None:
    """STV-33: a route out ends at the station's last signal; past it is the line and the
    clearance. No route starts at that signal, and Kör past it is the departure. At level 1
    the route ends at the line exit itself."""
    it = made(provby())
    shown = {r.end: r for r in it.plant.preferred() if r.start == "12"}
    assert shown["Ut2"].leaves == "O"
    assert not [w for w in it.plant.preferred() if w.start == "Ut2"]
    assert it.targets("12").targets[0].end == "Ut2"
    one = made(level_1())
    out = {(w.start, w.end): w for w in one.plant.preferred()}
    assert out[("Sp1", "A1")].leaves == "A1" and out[("A1", "Sp1")].enters == "A1"
    yes(one.put_train("7", section="p1"))
    route = yes(one.set_route("Sp1", "A1")).route
    yes(one.step(route))
    left = yes(one.step(route))
    assert "har lämnat mot A1" in left.message
    assert [r.kind for r in left.reports] == [TklReportKind.DEPARTED], "no signals at level 1"


def test_the_piece_outside_the_entry_signal_belongs_to_the_line() -> None:
    """STV-54: the route begins at the signal, so the piece outside it never turns green;
    it shows the line's state: a train on its way stands there."""
    it = made(provby())
    [west] = [e for e in state(it).exits if e.exit == "V"]
    assert west.pieces == ["a"] and west.aspect == ExitSignalAspect.STOP
    yes(it.set_route("In", "12"))
    assert "a" not in state(it).pieces
    yes(it.put_train("41", exit="V"))
    assert state(it).pieces["a"].state == TklPieceState.OCCUPIED
    out = made(provby())
    yes(out.set_route("11", "Ut"))
    assert "a" not in out.view().pieces
    assert [e.aspect for e in out.view().exits if e.exit == "V"] == [ExitSignalAspect.PROCEED]


def test_where_the_numbers_stand_for_the_panel() -> None:
    """STV-57: the panel hides a track's name where a number stands, so the API says the
    section, its pieces and the station track."""
    it = made(provby())
    yes(it.put_train("41", section="Spår 2"))
    [number] = state(it).numbers
    assert (number.section, number.pieces, number.track, number.estimated) == (
        "Spår 2",
        ["f1", "f2"],
        "2",
        True,
    )


def test_the_panel_knows_where_a_train_can_be_put_on_a_track() -> None:
    """The panel offers the station tracks' sections for a typed train number."""
    it = made(provby())
    assert state(it).tracks == {"Spår 1": "1", "Spår 2": "2"}
    for section, track in state(it).tracks.items():
        yes(it.put_train(f"4{track}", section=section))
    assert {n.track for n in state(it).numbers} == {"1", "2"}


# --- goals from a start ----------------------------------------------------------------------


def test_ported_targets_say_what_can_be_set_now() -> None:
    """Ported: 'targets stay disabled until checked; refresh removes unavailable targets and
    fails closed' (cda-tkl test/route-targets.test.mjs)."""
    it = made(provby())
    goals = {(t.kind.value, t.end): t for t in it.targets("In").targets}
    assert set(goals) == {("train", "12"), ("train", "22"), ("train", "Ut2")}
    assert goals[("train", "Ut2")].via == ["12"] and all(t.possible for t in goals.values())
    yes(it.put_train("9103", section="Spår 1"))
    goals = {(t.kind.value, t.end): t for t in it.targets("In").targets}
    assert not goals[("train", "12")].possible
    assert goals[("train", "12")].reason == "Spårledningen Spår 1 är belagd av tåg 9103."
    assert goals[("train", "Ut2")].via == ["22"], "the chain that can be set now"
    blocking = yes(it.set_route("In2", "21")).route
    goals = {(t.kind.value, t.end): t for t in it.targets("In").targets}
    assert not goals[("train", "Ut2")].possible, "both chains are blocked now"
    yes(it.release(blocking))
    set_ = yes(it.set_route("In", "22")).route
    assert {t.end: t.route for t in it.targets("In").targets}["22"] == set_


def test_a_level_1_station_routes_track_to_track() -> None:
    it = made(level_1())
    assert state(it).signals == {} and [e.aspect for e in state(it).exits] == [
        ExitSignalAspect.UNKNOWN
    ]
    yes(it.put_train("7", exit="A1"))
    route = yes(it.set_route("A1", "Sp2")).route
    assert state(it).switches["1"].position == MINUS
    yes(it.step(route))
    yes(it.step(route))
    assert state(it).trains[0].section == "p2"
    yes(it.arrive(route))


def test_a_saved_state_comes_back_and_a_changed_model_fails_closed() -> None:
    """Ported: 'durable locks survive process restart; corrupt or changed state fails closed'
    (engine.test.mjs). The store and the API are tested in test_app_stallverk.py."""
    it = made(provby())
    yes(it.put_train("41", exit="V"))
    route = yes(it.set_route("In", "22")).route
    yes(it.step(route))
    saved = it.view()
    again = Interlocking(plant_of(provby()), saved)
    assert again.view() == saved
    yes(again.step(route))
    other = provby(line_exits=[LineExit(id="V", node="V"), LineExit(id="O", node="O")])
    stale = Interlocking(plant_of(other), saved)
    assert stale.view().problem is not None and stale.view().routes == saved.routes
    no(stale.set_route("In", "12"), "Nollställ")
    yes(stale.reset(True))
    assert stale.view().problem is None and stale.view().routes == []
