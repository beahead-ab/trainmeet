"""The checks before a model file may run (STD-04, §6), each with a broken copy of Provby."""

from __future__ import annotations

from typing import Any

from contracts.station_model import (
    WITHOUT,
    Address,
    Lever,
    SignalType,
    StationModel,
    Switch,
    SwitchControl,
    SwitchPath,
    SwitchType,
    TrackCircuit,
)
from tkl.standard import checks, notes, problems
from tkl.tests.provstation import MINUS, PLUS, provby, switch


def changed(model: StationModel, field: str, index: int, **update: Any) -> StationModel:
    items = list(getattr(model, field))
    items[index] = items[index].model_copy(update=update)
    return model.model_copy(update={field: items})


def test_a_whole_station_passes_every_check() -> None:
    assert problems(provby()) == []


def test_every_switch_has_trunk_straight_and_diverging_legs() -> None:
    model = provby()
    assert problems(changed(model, "switches", 0, diverging=None)) == [
        "Växel 1 saknar avvikande ben."
    ]
    assert problems(changed(model, "switches", 0, trunk=None)) == ["Växel 1 saknar stam."]
    assert problems(changed(model, "switches", 0, straight="j")) == [
        "Växel 1: benet j når inte växeln."
    ]
    assert "Växel 1 har samma spårbit på två ben." in problems(
        changed(model, "switches", 0, straight="b")
    )


def test_a_crossing_s_paths_go_through_it() -> None:
    crossing = Switch(
        number="k1",
        type=SwitchType.CROSSING,
        node="1",
        paths=[SwitchPath(between=("b", "x"))],
    )
    model = provby().model_copy(update={"switches": [crossing, provby().switches[1]]})
    assert "Korsningen k1: vägen b–x går inte genom korsningen." in problems(model)
    assert "Korsningen k1 ska ha fyra spårbitar men har 3." in problems(model)


def test_every_train_route_ends_at_a_signal_or_a_buffer_stop() -> None:
    """Without the exit signal Ut, the train routes towards the west run out onto the line."""
    model = provby()
    without = model.model_copy(update={"signals": [s for s in model.signals if s.name != "Ut"]})
    assert problems(without) == [
        "Tågvägen från 11 slutar inte vid en signal eller en stoppbock: den når linjeutfarten V.",
        "Tågvägen från 21 slutar inte vid en signal eller en stoppbock: den når linjeutfarten V.",
    ]


def test_an_exit_signal_leads_onto_the_line() -> None:
    """Ut faces the line exit V and stands at its boundary: no problem."""
    model = provby()
    assert [e.signals for e in model.line_exits] == [["In", "Ut"], ["Ut2", "In2"]]
    assert problems(model) == []


def test_every_track_circuit_has_a_name_and_a_piece() -> None:
    model = provby()
    assert problems(changed(model, "track_circuits", 2, pieces=[])) == [
        "Spårledningen Spår 1 har ingen spårbit."
    ]
    assert problems(changed(model, "track_circuits", 2, pieces=["e", "q"])) == [
        "Spårledningen Spår 1: spårbiten q finns inte."
    ]
    twice = model.model_copy(
        update={"track_circuits": [*model.track_circuits, TrackCircuit(name="Ny", pieces=["e"])]}
    )
    assert problems(twice) == ["Spårbiten e ligger i två spårledningar: Spår 1 och Ny."]


def test_levers_have_unambiguous_positions() -> None:
    model = provby()

    def with_levers(*levers: Lever) -> list[str]:
        return problems(model.model_copy(update={"levers": list(levers)}))

    good = Lever(id="1/2", plus={"1": PLUS, "2": MINUS}, minus={"1": MINUS, "2": PLUS})
    assert with_levers(good) == [], "a reversed switch is unambiguous"
    same = Lever(id="1/2", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS, "2": PLUS})
    assert with_levers(same) == ["Spaken 1/2: växel 2 får samma läge i + och -."]
    one = Lever(id="1", plus={"1": PLUS}, minus={"1": MINUS})
    assert with_levers(good, one) == ["Växel 1 ligger på två spakar: 1/2 och 1."]
    ghost = Lever(id="9", plus={"9": PLUS}, minus={"9": MINUS})
    assert with_levers(ghost) == ["Spaken 9: växel 9 finns inte."]
    dragging = Lever(id="1", plus={"2": PLUS}, minus={"1": MINUS})
    assert with_levers(dragging) == [
        "Spaken 1 har ingen egen växel: ingen växel står i både + och -."
    ]
    # 1 straight drags 2 straight, and 2 straight drags 1 diverging: lever 1's + is impossible.
    first = Lever(id="1", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS})
    second = Lever(id="2", plus={"2": PLUS, "1": MINUS}, minus={"2": MINUS})
    assert with_levers(first, second) == ["Spaken 1 i läget + kräver en växel i två lägen."]


def test_a_lever_cannot_lay_a_switch_that_tkl_does_not_lay() -> None:
    model = changed(provby(), "switches", 1, control=SwitchControl.MANUAL)
    lever = Lever(id="1/2", plus={"1": PLUS, "2": PLUS}, minus={"1": MINUS, "2": MINUS})
    assert problems(model.model_copy(update={"levers": [lever]})) == [
        "Spaken 1/2: växel 2 läggs inte av TKL."
    ]


def test_no_number_or_name_is_used_twice() -> None:
    model = provby()
    assert problems(changed(model, "switches", 1, number="1")) == ["Två växlar har numret 1."]
    assert problems(changed(model, "signals", 1, name="In")) == ["Två signaler heter In."]
    pieces = [*model.pieces, model.pieces[0]]
    assert "Två spårbitar heter a." in problems(model.model_copy(update={"pieces": pieces}))
    circuits = [*model.track_circuits, model.track_circuits[0].model_copy()]
    assert "Två spårledningar heter Infart V." in problems(
        model.model_copy(update={"track_circuits": circuits})
    )


def test_a_line_exit_without_a_neighbour_is_a_note_not_a_problem() -> None:
    """An exit is tied to a section per meet (H26), so the station file need not know the
    neighbour: it is shown, but the model may run."""
    model = changed(provby(), "line_exits", 1, neighbour=None)
    assert problems(model) == []
    assert notes(model) == ["Linjeutfarten O saknar grannstation."]
    assert checks(model) == ([], ["Linjeutfarten O saknar grannstation."])


def test_the_graph_holds_together() -> None:
    model = provby()
    assert problems(changed(model, "pieces", 0, start="Ingenstans")) == [
        "Spårbiten a börjar i noden Ingenstans, som inte finns.",
        "Noden V ska ha en spårbit men har 0.",
    ]
    assert problems(changed(model, "signals", 0, approach="e")) == [
        "Signalen In: spårbiten e når inte signalen."
    ]


def level_3(**update: Any) -> StationModel:
    """Provby with every address and feedback in place."""
    model = provby(level=3)
    switches = [
        s.model_copy(update={"address": Address(number=n), "feedback": WITHOUT})
        for n, s in zip((1, 2), model.switches, strict=True)
    ]
    signals = [
        s.model_copy(update={"address": Address(number=100 + n)})
        for n, s in enumerate(model.signals)
    ]
    circuits = [
        c.model_copy(update={"detection": Address(number=500 + n)})
        for n, c in enumerate(model.track_circuits)
    ]
    return model.model_copy(
        update={"switches": switches, "signals": signals, "track_circuits": circuits, **update}
    )


def test_level_3_addresses_are_unique_per_bus() -> None:
    model = level_3()
    assert problems(model) == []
    clash = changed(model, "signals", 1, address=Address(number=100))
    assert problems(clash) == ["Adressen LocoNet 100 används av både signal In och signal Ut."]
    other_bus = changed(model, "signals", 1, address=Address(bus="DCC", number=100))
    assert problems(other_bus) == []
    sensor = changed(model, "switches", 0, feedback=Address(number=500))
    assert problems(sensor) == [
        "Givaren LocoNet 500 används av både växel 1 och spårledningen Infart V."
    ]


def test_level_3_every_switch_has_feedback_or_without() -> None:
    model = level_3()
    assert problems(changed(model, "switches", 0, feedback=None)) == [
        "Växel 1 saknar återrapport: ange en givare eller utan."
    ]
    assert problems(changed(model, "switches", 0, feedback=Address(number=7))) == []
    assert problems(changed(model, "switches", 0, address=None)) == ["Växel 1 saknar adress."]
    manual = changed(model, "switches", 0, address=None, feedback=None)
    manual = changed(manual, "switches", 0, control=SwitchControl.MANUAL)
    assert problems(manual) == [], "a manual switch has no address (TKL26)"
    assert problems(changed(model, "track_circuits", 0, detection=None)) == [
        "Spårledningen Infart V saknar givare: ange en givare eller utan."
    ]


def test_level_2_does_not_ask_for_addresses() -> None:
    assert problems(provby()) == []
    assert all(s.address is None for s in provby().switches)


def test_a_model_with_problems_can_still_be_saved() -> None:
    """Studio keeps a station that is not finished; it only may not run."""
    broken = changed(provby(), "switches", 0, diverging=None)
    again = StationModel.model_validate_json(broken.model_dump_json())
    assert problems(again) == ["Växel 1 saknar avvikande ben."]


def test_the_stop_lamp_is_in_the_signal_catalogue() -> None:
    assert SignalType.STOP_LAMP.value == "stop_lamp"
    assert switch("9", "a", "b", "c").type == SwitchType.ORDINARY
