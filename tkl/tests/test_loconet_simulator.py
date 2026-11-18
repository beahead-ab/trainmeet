"""The pretend LocoNet (#85, STUDIO-21): TKL's simulator at the LocoNet message level, wired
from a station model, with MGP cards, switches, signals, sensors, trains and a recorder.

The tests marked "Ported" carry an old cda-tkl test's behaviour, with the old test named.
Nothing here names a station (RS13).
"""

from __future__ import annotations

from contracts.station_model import Address, FeedbackType, Position, SwitchFeedback
from contracts.tkl import ObjectKind
from tkl.loconet.messages import (
    MGP_BASE_SV,
    MGP_IDENTITY,
    OPC_SW_STATE,
    FrameReader,
    LongAck,
    Output,
    SensorReport,
    SvCommand,
    SwitchReport,
    decode,
    decode_sv,
    discover,
    hex_of,
    identify,
    interrogation,
    read_sv4,
    switch_request,
    switch_state,
)
from tkl.loconet.objects import changed
from tkl.loconet.simulator import PretendLoconet, Wiring
from tkl.tests.niva3 import level_3
from tkl.tests.provstation import provby

C, T = Output.CLOSED, Output.THROWN


class Clock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


def answers(layout: PretendLoconet, data: bytes) -> list[object]:
    """What the layout sends back for one message, the echo left out."""
    layout.write(data)
    out = layout.read(0)
    assert out.startswith(data), "every message comes back as its echo"
    return [decode(frame) for frame in _frames(out[len(data) :])]


def test_a_switch_moves_and_its_card_reports_in_the_input_format() -> None:
    """Ported: benny-monitoring.test.mjs, "simulatorn tar en order i båda formaten och svarar i
    ingångsformatet": on its way first, then where it lies; the off changes nothing."""
    clock = Clock()
    layout = PretendLoconet.from_model(level_3(provby()), clock=clock, movement=0.5)
    assert answers(layout, switch_request(1, T)) == [SwitchReport(1, None)]
    assert layout.position("1") is None
    clock.seconds = 0.6
    assert [decode(f) for f in _frames(layout.read(0))] == [SwitchReport(1, T, True)]
    assert layout.position("1") == Position.MINUS
    assert answers(layout, switch_request(1, T, on=False)) == []
    assert layout.position("1") == Position.MINUS, "the off changes nothing"
    assert answers(layout, switch_request(1, T)) == [SwitchReport(1, T, True)], (
        "a switch already lying right reports at once"
    )
    assert answers(layout, switch_state(1)) == [LongAck(OPC_SW_STATE & 0x7F, 0)]


def _frames(data: bytes) -> list[bytes]:
    return FrameReader().push(data)


def test_two_sensors_go_passive_while_the_switch_moves_and_none_says_nothing() -> None:
    model = level_3(provby())
    sensors = SwitchFeedback(
        type=FeedbackType.SENSORS, straight=Address(number=41), diverging=Address(number=42)
    )
    model = changed(model, ObjectKind.SWITCH, "1", feedback=sensors)
    model = changed(model, ObjectKind.SWITCH, "2", feedback=SwitchFeedback(type=FeedbackType.NONE))
    clock = Clock()
    layout = PretendLoconet.from_model(model, clock=clock, movement=0.5)
    assert answers(layout, switch_request(1, T)) == [SensorReport(41, False)]
    clock.seconds = 1.0
    assert [decode(f) for f in _frames(layout.read(0))] == [SensorReport(42, True)]
    assert answers(layout, switch_request(2, T)) == []
    clock.seconds = 2.0
    assert layout.read(0) == b"" and layout.position("2") == Position.MINUS


def test_a_signal_card_reports_its_output_at_once_with_the_polarity() -> None:
    model = level_3(provby())
    layout = PretendLoconet.from_model(model, reversed_=["Ut"])
    In = layout.wiring.signals["In"].address
    assert answers(layout, switch_request(In, C)) == [SwitchReport(In, C, True)]
    assert layout.proceed("In")
    ut = layout.wiring.signals["Ut"].address
    answers(layout, switch_request(ut, C))
    assert not layout.proceed("Ut"), "wired the other way: closed is stopp"


def test_the_inputs_answer_the_interrogation_in_their_group() -> None:
    """Ported: field.mjs's interrogate: every input answers once a round, in the group
    ((address - 1) >> 3 & 7)."""
    layout = PretendLoconet.from_model(level_3(provby()))
    layout.occupy("Spår 1")
    layout.read(0)
    heard: list[SensorReport] = []
    for frame in interrogation():
        heard += [m for m in answers(layout, frame) if isinstance(m, SensorReport)]
    sensors = {c.address for c in layout.wiring.circuits.values()}
    assert {h.address for h in heard} == sensors
    spår_1 = layout.wiring.circuits["Spår 1"].address
    assert SensorReport(spår_1, True) in heard


def test_the_mgp_cards_answer_discover_identify_and_their_svs() -> None:
    """Ported: benny-monitoring.test.mjs, "MGP-appen: Discover-svaren bär kortens identitet":
    the pretend cards answer as MGP's, with the asker's number in SRC; SV21 is the base."""
    layout = PretendLoconet.from_model(level_3(provby()))
    layout.write(discover(0))
    replies = [decode_sv(f) for f in _frames(layout.read(0))[1:]]
    assert replies and all(r is not None and r.src == 0 for r in replies)
    identities = [r.identity for r in replies if r is not None]
    assert all(i is not None and (i.manufacturer, i.developer) == MGP_IDENTITY for i in identities)
    servo = next(c for c in layout.wiring.cards if c.identity.product == 9)
    assert servo.base == 1 and servo.address == 1, "switches 1 and 2 on one servo card"
    signal = next(c for c in layout.wiring.cards if c.identity.product == 6)
    assert signal.base == 101, "the signals from 101 on a Signal10 SE"
    layout.write(identify(signal.address))
    again = [decode_sv(f) for f in _frames(layout.read(0))[1:]]
    assert again[0] is not None and again[0].card == signal.address
    layout.write(read_sv4(signal.address, MGP_BASE_SV))
    read = decode_sv(_frames(layout.read(0))[1])
    assert read is not None and read.cmd == SvCommand.READ4 | 0x40
    assert read.data[0] | read.data[1] << 8 == 101


def test_made_up_addresses_for_what_is_grey_and_the_switch_number_by_default() -> None:
    """Given a model, the pretend LocoNet knows the addresses: the model's, a switch's number
    as the default (STUDIO-19), and free made-up ones for the grey objects."""
    model = provby()
    wiring = Wiring.of(model)
    assert {p: s.address for p, s in wiring.switches.items()} == {"1": 1, "2": 2}
    assert sorted(s.address for s in wiring.signals.values()) == list(range(1001, 1010))
    sensors = sorted(c.address for c in wiring.circuits.values())
    assert sensors == list(range(1, 7))
    model = changed(model, ObjectKind.TRACK_CIRCUIT, "Spår 1", address=Address(number=3))
    model = changed(model, ObjectKind.SIGNAL, "In", address="without")
    wiring = Wiring.of(model)
    assert wiring.circuits["Spår 1"].address == 3 and "In" not in wiring.signals
    assert 3 not in [c.address for n, c in wiring.circuits.items() if n != "Spår 1"]


def test_a_train_occupies_and_frees_the_sensors_as_it_moves_and_everything_is_recorded() -> None:
    layout = PretendLoconet.from_model(level_3(provby()))
    layout.put_train("102", ["Infart V"])
    layout.move_train("102", "Vx1")
    layout.move_train("102", "Spår 1")
    assert [layout.occupied(c) for c in ("Infart V", "Vx1", "Spår 1")] == [False, True, True]
    layout.remove_train("102")
    assert not any(layout.occupied(c) for c in layout.wiring.circuits)
    heard = [r for r in layout.recorded if r.direction == "in"]
    assert [hex_of(r.data)[:2] for r in heard] == ["B2"] * 6
    layout.write(switch_request(1, C))
    assert layout.received() == [switch_request(1, C)]


def test_a_reversed_sensor_is_active_when_the_track_is_free() -> None:
    layout = PretendLoconet.from_model(level_3(provby()), reversed_=["Spår 1"])
    address = layout.wiring.circuits["Spår 1"].address
    assert dict(layout.sensors())[address] is True
    layout.occupy("Spår 1")
    assert dict(layout.sensors())[address] is False and layout.occupied("Spår 1")
