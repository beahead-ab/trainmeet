"""The panel functions from the catalogue in the interlocking (#84 del c, STV-04, STV-53, TKL44,
TKL106, STD-14, FR41), on a small made-up station: signal stop, local release, traction
current, track out of service, emergency release per track circuit, the turntable and the
programming track.

The tests marked "Ported" carry an old cda-tkl test's behaviour; the old test is named. Nothing
here names a station (RS13).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.station import ExitSignalAspect
from contracts.station_model import PanelFunction, PanelFunctionType, Position, StationModel
from contracts.tkl import (
    TklAspect,
    TklFunctionAction,
    TklFunctionShown,
    TklInterlocking,
    TklPieceState,
    TklReportKind,
)
from tkl.stallverk import Interlocking, plant_of
from tkl.stallverk.plant import MINUS_SIGN
from tkl.tests.provstation import MINUS, PLUS, provby
from tkl.tests.test_standard_routes import turntable_station
from tkl.track_plan import REFERENCES, panel_of

NOON = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
ON, OFF, SET, LAY, RELEASE = (
    TklFunctionAction.ON,
    TklFunctionAction.OFF,
    TklFunctionAction.SET,
    TklFunctionAction.LAY,
    TklFunctionAction.RELEASE,
)
F = PanelFunctionType


def functions() -> list[PanelFunction]:
    """Every function in the catalogue, on provby (tkl/tests/provstation.py):

    V -a- W(In, Ut) -b- 1 -c- X1(11) -e- Y1(12) -g- 2 -i- Z(Ut2, In2) -j- O
                         \\d- X2(21) -f1- M(D) -f2- Y2(22) -h-/
    """
    return [
        PanelFunction(
            type=F.SIGNAL_STOP, name="Signalstopp", track_circuits=["Spår 1"], signals=["In"]
        ),
        PanelFunction(
            type=F.LOCAL_RELEASE,
            name="Lokal frigivning",
            track_circuits=["Spår 2"],
            switches=["2"],
            locked={"1": Position.PLUS},
            signals=["D", "21", "22"],
            codes={"59": "L1", "85": "L01", "95": "L01"},
        ),
        PanelFunction(type=F.TRACTION_CURRENT, name="Körström spår 1", track_circuits=["Spår 1"]),
        PanelFunction(type=F.OUT_OF_SERVICE, name="Spår 1 ur drift", track_circuits=["Spår 1"]),
        PanelFunction(type=F.EMERGENCY_RELEASE, name="Nödutlös Vx1", track_circuits=["Vx1"]),
        PanelFunction(type=F.PROGRAMMING_TRACK, name="Spår 2 prog", pieces=["f1", "f2"], at="M"),
    ]


def station(**more: Any) -> StationModel:
    return provby(functions=functions(), **more)


def made(model: StationModel | None = None) -> Interlocking:
    return Interlocking(plant_of(model or station()), now=lambda: NOON)


def yes(outcome: Any) -> Any:
    assert outcome.accepted, outcome.message
    return outcome


def no(outcome: Any, *said: str) -> None:
    assert not outcome.accepted, outcome.message
    for text in said:
        assert text in outcome.message, outcome.message


def shown(it: Interlocking, name: str) -> TklFunctionShown:
    return next(f for f in it.view().functions if f.name == name)


def route_of(state: TklInterlocking, route: int) -> Any:
    return next(r for r in state.routes if r.id == route)


def restarted(it: Interlocking, model: StationModel | None = None) -> Interlocking:
    """The interlocking read back from its saved state, as TKL's store does it."""
    saved = TklInterlocking.model_validate_json(it.view().model_dump_json())
    return Interlocking(plant_of(model or station()), saved, now=lambda: NOON)


# --- the catalogue in the model ---------------------------------------------------------------


def test_the_state_lists_every_function_with_its_parameters_and_state() -> None:
    state = made().view()
    assert [(f.name, f.type, f.on) for f in state.functions] == [
        ("Signalstopp", F.SIGNAL_STOP, False),
        ("Lokal frigivning", F.LOCAL_RELEASE, False),
        ("Körström spår 1", F.TRACTION_CURRENT, False),
        ("Spår 1 ur drift", F.OUT_OF_SERVICE, False),
        ("Nödutlös Vx1", F.EMERGENCY_RELEASE, False),
        ("Spår 2 prog", F.PROGRAMMING_TRACK, False),
    ]
    stop, local, traction, out, _, programming = state.functions
    assert stop.signals == ["In", "11", "12"], "the listed signal and those in the area"
    assert local.switches == ["2"] and local.locked == {"1": PLUS}
    assert local.pieces == ["f1", "f2"] and local.codes["95"] == "L01"
    assert set(local.blocked) >= {"In", "In2", "12"} and "11" not in local.blocked
    assert [m.value for m in traction.modes] == ["2R", "3R"] and traction.mode == "2R"
    assert out.pieces == ["e"] and programming.pieces == ["f1", "f2"]
    assert programming.at == "M"


def test_unknown_functions_and_actions_are_a_no() -> None:
    it = made()
    no(it.function("Finns inte", ON), "finns inte i stationsmodellen")
    no(it.function("Körström spår 1", ON), "går inte att manövrera så")
    no(it.function("Signalstopp", SET, "3R"), "går inte att manövrera så")
    no(it.function("Körström spår 1", SET, "5R"), "Lägena är 2R och 3R")
    assert it.view().revision == 0, "a no changes nothing"


def test_a_turntable_in_the_model_has_a_function_of_its_own() -> None:
    it = made(turntable_station(level=1))
    [table] = it.view().functions
    assert (table.name, table.type, table.at) == ("Vändskivan", F.TURNTABLE, "Vändskivan")
    assert [(m.value, m.label) for m in table.modes] == [
        ("b", "4"),
        ("s", "Stall"),
        ("r", "Stall2"),
    ]


# --- signal stop ------------------------------------------------------------------------------


def test_ported_signal_stop_holds_routes_at_stop_and_an_independent_route_runs() -> None:
    """Ported: 'line barrier stops affected active route while retaining locks; an independent
    route can still run' and 'seven source line controls preserve independent barriers without
    falsifying detector reports' (cda-tkl test/operating-controls.test.mjs)."""
    it = made()
    yes(it.put_train("41", exit="V"))
    kept = yes(it.set_route("In", "12")).route
    other = yes(it.set_route("In2", "21")).route
    trains = it.view().trains
    said = yes(it.function("Signalstopp", ON)).message
    assert "In, 11 och 12 visar stopp" in said and "In → 12 ligger kvar" in said
    state = it.view()
    held = route_of(state, kept)
    assert held.held == "Signalstopp" and held.aspect == TklAspect.STOP
    assert state.switches["1"].routes == [kept], "the route keeps its locks"
    assert state.signals["In"].aspect == TklAspect.STOP and state.signals["In"].blocked
    assert state.signals["12"].blocked and not state.signals["In2"].blocked
    assert route_of(state, other).aspect == TklAspect.PROCEED, "an independent route runs"
    assert state.trains == trains, "a stop never moves a train number"
    no(it.step(kept), "står i stopp (Signalstopp)")
    no(it.set_route("12", "Ut2"), "Signalen 12 är i signalstopp (Signalstopp)")
    target = next(t for t in it.targets("12").targets if t.end == "Ut2")
    assert not target.possible and "signalstopp" in (target.reason or "")


def test_ported_signal_stop_survives_a_restart_and_never_resumes_a_route() -> None:
    """Ported: 'AIS requires new STOP acknowledgements, survives restart and never resumes old
    routes' (cda-tkl test/network.test.mjs). Here the operator sets the route again when the
    stop is off, and only then does its signal clear."""
    it = made()
    kept = yes(it.set_route("In", "12")).route
    yes(it.function("Signalstopp", ON))
    again = restarted(it)
    assert shown(again, "Signalstopp").on and route_of(again.view(), kept).held == "Signalstopp"
    no(again.set_route("In", "12"), "står i stopp: Signalstopp är på")
    said = yes(again.function("Signalstopp", OFF)).message
    assert "visar stopp tills de läggs på nytt" in said
    assert route_of(again.view(), kept).aspect == TklAspect.STOP, "never resumed by itself"
    assert "lagd på nytt" in yes(again.set_route("In", "12")).message
    state = again.view()
    assert route_of(state, kept).held is None and state.signals["In"].aspect == TklAspect.PROCEED
    assert "redan" in yes(again.function("Signalstopp", OFF)).message


def test_signal_stop_on_a_route_out_sets_the_exit_signal_to_stop_for_the_hub() -> None:
    it = made(provby(functions=[PanelFunction(type=F.SIGNAL_STOP, name="Ut", signals=["12"])]))
    yes(it.set_route("12", "Ut2"))
    assert it.exit_aspects()["O"] == ExitSignalAspect.PROCEED
    stopped = yes(it.function("Ut", ON))
    assert [(r.kind, r.aspect) for r in stopped.reports] == [
        (TklReportKind.EXIT_SIGNAL, ExitSignalAspect.STOP)
    ]


# --- local release (TKL44, STD-14, FR41) --------------------------------------------------------


def test_ported_local_release_is_refused_while_a_route_touches_the_area() -> None:
    """Ported in part: 'a route over the group answers the ranger at once; no request reaches
    TKL' (cda-tkl test/yard-control.test.mjs): the area cannot be released under a route."""
    it = made()
    route = yes(it.set_route("12", "Ut2")).route  # lays local switch 2
    no(it.function("Lokal frigivning", ON), "Lös ut vägarna i området först: 12 → Ut2")
    yes(it.release(route))
    yes(it.set_route("In", "12"))  # outside the area, switch 1 in its locked position
    yes(it.function("Lokal frigivning", ON))


def test_local_release_locks_protection_frees_local_switches_and_shows_shunting() -> None:
    """TKL44 and FR41: the protection lever is laid and locked, the local switch is laid with
    the module's button and never by the interlocking, the area's dwarf signals show shunting,
    its entry signals are blocked, and the area is blue on the panel."""
    it = made()
    yes(it.lay_lever("1", MINUS))
    said = yes(it.function("Lokal frigivning", ON)).message
    assert said == (
        "Lokal frigivning kopplades in: 1 + låsta, 2 läggs om med knapparna på modulerna."
    )
    state = it.view()
    assert state.switches["1"].position == PLUS and state.switches["1"].protection
    assert state.switches["1"].function == "Lokal frigivning"
    assert state.switches["2"].local and state.switches["2"].function == "Lokal frigivning"
    assert state.signals["D"].aspect == TklAspect.LOCAL
    assert state.signals["21"].aspect == state.signals["22"].aspect == TklAspect.LOCAL
    assert state.signals["In"].blocked and state.signals["In2"].blocked
    assert not state.signals["11"].blocked
    assert {p: s.state for p, s in state.pieces.items()} == {
        "f1": TklPieceState.LOCAL,
        "f2": TklPieceState.LOCAL,
    }
    no(it.lay_lever("1"), "Växel 1 är låst av Lokal frigivning")
    no(it.lay_lever("2"), "lokalt frigiven", "knappen på modulen")
    laid = yes(it.function("Lokal frigivning", LAY, "2")).message
    assert laid == f"Växel 2 lagd i {MINUS_SIGN} med knappen på modulen."
    assert it.view().switches["2"].position == MINUS
    no(it.function("Lokal frigivning", LAY, "1"), "inte lokal")


def test_ported_no_route_touches_a_released_area_and_routes_come_back_when_it_is_taken_back() -> (
    None
):
    """Ported in part: 'TKL approves: the group is laid and locked, routes over it wait, and the
    ranger lays it back' (cda-tkl test/yard-control.test.mjs)."""
    it = made()
    yes(it.function("Lokal frigivning", ON))
    area = "Området för Lokal frigivning är lokalt frigivet för växling"
    no(it.set_route("In", "22"), area)  # over the area
    no(it.set_route("21", "Ut"), area)  # from one of its signals
    no(it.set_route("12", "Ut2"), area)  # lays a local switch
    no(it.set_route("In2", "11"), area)
    yes(it.set_route("In", "12"))  # needs switch 1 in its locked position, and touches nothing
    said = yes(it.function("Lokal frigivning", OFF)).message
    assert said == "Lokal frigivning kopplades ur: 2 läggs åter från ställverket."
    state = it.view()
    assert not state.switches["2"].local and not state.signals["In2"].blocked
    assert state.signals["D"].aspect == TklAspect.STOP and "f1" not in state.pieces
    yes(it.set_route("12", "Ut2"))


def lf(position: Position) -> StationModel:
    """A local release of switch 2 alone, with switch 1 locked in `position`."""
    locked = {"1": position}
    return provby(
        functions=[PanelFunction(type=F.LOCAL_RELEASE, name="LF", switches=["2"], locked=locked)]
    )


def test_local_release_refuses_a_route_needing_a_protection_switch_the_other_way() -> None:
    it = made(lf(MINUS))
    yes(it.function("LF", ON))
    no(it.set_route("In", "12"), f"Växel 1 är låst i läget {MINUS_SIGN} av LF")
    assert it.view().switches["1"].position == MINUS
    yes(it.set_route("In", "22"))


def test_local_release_cannot_lay_a_protection_switch_that_is_locked_or_under_a_train() -> None:
    it = made(lf(PLUS))
    route = yes(it.set_route("In", "22")).route  # switch 1 in -, the area untouched
    no(it.function("LF", ON), "Växel 1 är låst i vägen In → 22")
    yes(it.release(route))
    yes(it.put_train("7", section="Vx1"))
    no(it.function("LF", ON), "Växel 1 kan inte läggas om: spårledningen Vx1 är belagd")
    assert not shown(it, "LF").on and it.view().switches["1"].position == MINUS


# --- traction current, out of service, emergency release ---------------------------------------


def test_traction_current_switches_the_tracks_mode_and_touches_no_route() -> None:
    it = made()
    route = yes(it.set_route("In", "12")).route
    assert yes(it.function("Körström spår 1", SET, "3R")).message == "Körström spår 1: 3R."
    assert shown(it, "Körström spår 1").mode == "3R"
    assert route_of(it.view(), route).aspect == TklAspect.PROCEED
    assert "redan 3R" in yes(it.function("Körström spår 1", SET, "3R")).message
    assert shown(restarted(it), "Körström spår 1").mode == "3R"


def test_ported_a_track_out_of_service_takes_no_route_and_holds_one_already_there() -> None:
    """Ported: 'administrative blocks persist independently of FREE reports and stop existing
    routes without releasing locks' (cda-tkl test/network.test.mjs)."""
    it = made()
    yes(it.function("Spår 1 ur drift", ON))
    no(it.set_route("In", "12"), "Spårledningen Spår 1 är ur drift (Spår 1 ur drift)")
    yes(it.put_train("7", section="Spår 1"))  # a train number is no detector report
    state = it.view()
    assert state.pieces["e"].state == TklPieceState.OCCUPIED, "occupied goes before the mark"
    again = restarted(it)
    assert shown(again, "Spår 1 ur drift").on
    yes(again.remove_train(again.view().trains[0].id))
    assert again.view().pieces["e"].state == TklPieceState.OUT_OF_SERVICE
    yes(again.function("Spår 1 ur drift", OFF))
    route = yes(again.set_route("In", "12")).route
    yes(again.function("Spår 1 ur drift", ON))
    state = again.view()
    assert route_of(state, route).held == "Spår 1 ur drift"
    assert state.switches["1"].routes == [route], "the route keeps its locks"
    yes(again.function("Spår 1 ur drift", OFF))
    assert route_of(again.view(), route).aspect == TklAspect.STOP, "never resumed by itself"


def test_emergency_release_of_a_track_circuit_is_confirmed_and_frees_its_locks() -> None:
    it = made()
    yes(it.put_train("41", exit="V"))
    route = yes(it.set_route("In", "22")).route
    yes(it.step(route))
    no(it.function("Nödutlös Vx1", RELEASE), "Bekräfta nödutlösningen av Vx1")
    said = yes(it.function("Nödutlös Vx1", RELEASE, confirm=True)).message
    assert said.startswith("Nödutlösning av Vx1 (Nödutlös Vx1), bekräftad: 1 sektioner")
    state = it.view()
    assert [s.released for s in route_of(state, route).sections] == [True, False]
    assert state.switches["1"].routes == [], "switch 1's lock was held by Vx1"
    assert state.events[0].text == said


# --- the turntable and the programming track -------------------------------------------------


def test_the_turntable_turns_to_a_track_unless_a_route_holds_it_elsewhere() -> None:
    it = made(turntable_station(level=1))
    assert it.view().functions[0].mode is None
    assert yes(it.function("Vändskivan", SET, "r")).message == "Vändskivan vriden mot Stall2."
    assert it.view().turntables == {"Vändskivan": "r"}
    yes(it.function("Vändskivan", SET, "Stall"))  # by the track's name too
    assert it.view().functions[0].mode == "s"
    route = yes(it.set_route("4", "Stall")).route
    assert it.view().turntables == {"Vändskivan": "b"}, "the route turns the bridge"
    no(it.function("Vändskivan", SET, "r"), "låst i vägen 4 → Stall")
    assert "står redan mot Stall" in yes(it.function("Vändskivan", SET, "s")).message
    no(it.function("Vändskivan", SET, "x"), "har inget spår x")
    yes(it.release(route))
    yes(it.function("Vändskivan", SET, "r"))


def test_ported_the_programming_track_switches_over_and_blocks_no_route() -> None:
    """STV-53, TKL106: the button only switches the track over; the interlocking blocks no
    route. Ported in part: 'disconnect and restart preserve program lock' (cda-tkl
    test/operating-controls.test.mjs) - the state survives a restart; cda-tkl's lock on the
    routes is not ported, since TKL106 decided that no route is blocked."""
    it = made()
    said = yes(it.function("Spår 2 prog", ON)).message
    assert said == "Spår 2 prog kopplades om till programmeringsspår."
    assert it.view().pieces["f1"].state == TklPieceState.PROGRAMMING
    route = yes(it.set_route("In", "22")).route
    assert it.view().pieces["f1"].state == TklPieceState.TRAIN, "the route's colour goes first"
    yes(it.release(route))
    again = restarted(it)
    assert shown(again, "Spår 2 prog").on
    assert yes(again.function("Spår 2 prog", OFF)).message == (
        "Spår 2 prog kopplades tillbaka till körström."
    )
    assert again.view().pieces == {}


def test_ported_a_saved_function_the_model_does_not_have_fails_closed() -> None:
    """Ported: 'two panels cannot overwrite newer line/program choices; corrupt persisted
    controls fail closed' (cda-tkl test/operating-controls.test.mjs)."""
    it = made()
    yes(it.function("Signalstopp", ON))
    saved = it.view()
    broken = saved.model_copy(
        update={"functions": [f.model_copy(update={"name": "Okänd"}) for f in saved.functions]}
    )
    stale = Interlocking(plant_of(station()), broken)
    assert stale.view().problem is not None
    no(stale.function("Signalstopp", OFF), "Nollställ")


# --- the buttons in the track plan (STV-53) ---------------------------------------------------


def test_a_function_with_a_node_gets_its_button_beside_it_under_the_track() -> None:
    panel = panel_of(station())
    assert panel is not None
    [button] = panel.functions
    node = next(n.cell for n in panel.nodes if n.id == "M")
    assert (button.name, button.type, button.node, button.side) == (
        "Spår 2 prog",
        F.PROGRAMMING_TRACK,
        "M",
        "under",
    )
    assert button.cell[0] == node[0] and button.cell[1] > node[1], "under the track"


def test_the_plans_function_sides_place_the_reference_stations_buttons() -> None:
    for path in sorted(REFERENCES.glob("*.tkl.json")):
        model = StationModel.model_validate_json(path.read_text("utf-8"))
        panel = panel_of(model)
        assert panel is not None
        nodes = {n.id: n.cell for n in panel.nodes}
        sides = model.panel.function_sides if model.panel is not None else {}
        placed = {b.name: b for b in panel.functions}
        for function in model.functions:
            if function.at is None or function.at not in nodes:
                assert function.name not in placed
                continue
            button = placed[function.name]
            side = sides.get(function.name, "under")
            assert button.side == side
            assert (button.cell[1] < nodes[function.at][1]) == (side == "over"), function.name
