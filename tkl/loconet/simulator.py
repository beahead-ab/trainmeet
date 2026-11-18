"""The pretend LocoNet: TKL's own simulator at the LocoNet message level (STUDIO-21, TKL95).

"LocoNet ej ansluten" (STUDIO-24) is TKL against this instead of a LocoBuffer: the same
messages and the same code as on the layout, so what Prova tries is what runs (ported from
cda-tkl's src/field.mjs and src/simulator.mjs, which was a process of its own; here it is a
transport in the same process).

It answers as the layout would:

- every message comes back as its echo, as a LocoBuffer sends it;
- a switch moves for a while after a request and reports from its card in the input format,
  as the MGP cards do: on its way first (the output format with both bits clear), then where it
  lies. With two sensors, both are passive while it moves and one is active after; without
  feedback it says nothing. A switch already lying right reports at once, and with sensors not
  at all. The request's off is ignored;
- a signal's card reports its output at once, closed for kör;
- a sensor reports when it changes, and every input answers the interrogation in its group
  ((address - 1) >> 3 & 7, as cda-tkl spread them);
- the MGP cards answer Discover, Identify and reading their SVs over SV2, with the base
  address in SV21;
- OPC_SW_STATE gets a long acknowledge with the switch's state.

Given a station model, it knows the addresses: the model's own, a switch's number as the
default (STUDIO-19), and made-up free ones for what is still grey, so that Koppla in can be
practised before the owner knows them. The wiring is the truth of the pretend layout: it stays
when the model changes. A train occupies and frees the track circuits' sensors as it moves, so
that Prova can drive it (#85 del c). The recorder keeps every message both ways.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal

from contracts.station_model import FeedbackType, Position, StationModel
from contracts.tkl import AddressState, ObjectKind
from tkl.loconet.messages import (
    MGP_BASE_SV,
    MGP_CHANNELS,
    MGP_IDENTITY,
    OPC_SW_STATE,
    FrameError,
    Identity,
    Interrogate,
    Output,
    SensorReport,
    Sv,
    SvCommand,
    SwitchRequest,
    SwitchState,
    decode,
    identity_reply,
    long_ack,
    sensor_report,
    sv_reply,
    switch_report,
    validate,
)
from tkl.loconet.objects import Bus, objects, output_for, position_for, signal_output

MOVEMENT_SECONDS: Final = 0.65
"""How long a switch takes to move, as cda-tkl's simulator had it."""
MOST_RECORDED: Final = 2000
SERVO_CARD: Final = 9
SIGNAL_CARD: Final = 6
FIRST_MADE_UP_SIGNAL: Final = 1001
"""Made-up signal addresses start here, apart from the switches' numbers."""


@dataclass
class PretendSwitch:
    part: str
    address: int
    reversed: bool
    feedback: FeedbackType
    straight: int | None = None
    diverging: int | None = None
    output: Output = Output.CLOSED
    target: Output | None = None
    due: float = 0.0


@dataclass
class PretendSignal:
    name: str
    address: int
    reversed: bool
    output: Output = Output.THROWN


@dataclass
class PretendCircuit:
    name: str
    address: int
    reversed: bool


@dataclass
class PretendCard:
    address: int
    identity: Identity
    base: int
    sv: dict[int, int] = field(default_factory=dict)


@dataclass
class Wiring:
    """How the pretend layout is wired: the truth the owner learns in Koppla in."""

    switches: dict[str, PretendSwitch]
    signals: dict[str, PretendSignal]
    circuits: dict[str, PretendCircuit]
    cards: list[PretendCard]

    @classmethod
    def of(cls, model: StationModel, *, reversed_: Collection[str] = ()) -> Wiring:
        """The model's addresses, a switch's number as the default, and free made-up addresses
        for the rest; `reversed_` names objects wired the other way round than the model says,
        so that the polarity question has something to find."""
        found = [o for o in objects(model) if o.state != AddressState.WITHOUT]
        outputs = {
            o.address.number for o in found if o.address and o.kind != ObjectKind.TRACK_CIRCUIT
        }
        inputs = {
            o.address.number for o in found if o.address and o.kind == ObjectKind.TRACK_CIRCUIT
        }
        for o in found:
            if o.feedback is not None:
                inputs |= {s.number for s in (o.feedback.straight, o.feedback.diverging) if s}

        def free(taken: set[int], start: int = 1) -> int:
            number = start
            while number in taken:
                number += 1
            taken.add(number)
            return number

        switches: dict[str, PretendSwitch] = {}
        signals: dict[str, PretendSignal] = {}
        circuits: dict[str, PretendCircuit] = {}
        for o in found:
            flipped = o.name in reversed_
            if o.kind == ObjectKind.SWITCH:
                kind = Bus.feedback(o)
                straight = diverging = None
                if kind == FeedbackType.SENSORS:
                    given = o.feedback
                    straight = given.straight.number if given and given.straight else free(inputs)
                    diverging = (
                        given.diverging.number if given and given.diverging else free(inputs)
                    )
                address = o.address.number if o.address else free(outputs)
                switches[o.name] = PretendSwitch(
                    o.name, address, o.reversed != flipped, kind, straight, diverging
                )
            elif o.kind == ObjectKind.SIGNAL:
                address = o.address.number if o.address else free(outputs, FIRST_MADE_UP_SIGNAL)
                wired_reversed = o.reversed != flipped
                signals[o.name] = PretendSignal(
                    o.name, address, wired_reversed, signal_output(False, wired_reversed)
                )
            else:
                address = o.address.number if o.address else free(inputs)
                circuits[o.name] = PretendCircuit(o.name, address, o.reversed != flipped)
        cards = _cards(
            sorted(s.address for s in switches.values()),
            sorted(s.address for s in signals.values()),
        )
        return cls(switches, signals, circuits, cards)


def _cards(switches: list[int], signals: list[int]) -> list[PretendCard]:
    """The MGP cards: servo cards with five outputs for the switches, Signal10 SE with ten for
    the signals, each from the first address it drives. The card's own SV2 address is its base
    address, as on Benny's bench (card 6 at LT6, card 110 at LT110). The base is in SV21, and
    above 255 its high byte in SV22, as the service reads it."""
    cards: list[PretendCard] = []
    used: set[int] = set()
    for addresses, product in ((switches, SERVO_CARD), (signals, SIGNAL_CARD)):
        span = MGP_CHANNELS[product]
        base: int | None = None
        for address in addresses:
            if base is not None and address < base + span:
                continue
            base = address
            card = base
            while card in used:
                card += 1
            used.add(card)
            identity = Identity(MGP_IDENTITY[0], MGP_IDENTITY[1], product, 100 + len(cards))
            sv = {
                1: 2,
                2: 1,
                3: identity.serial & 0xFF,
                4: identity.serial >> 8,
                MGP_BASE_SV: base & 0xFF,
                MGP_BASE_SV + 1: base >> 8,
            }
            cards.append(PretendCard(card, identity, base, sv))
    return cards


@dataclass(frozen=True)
class Recorded:
    at: datetime
    direction: Literal["in", "out"]
    """Out from TKL to the bus, in from the bus to TKL."""
    data: bytes


@dataclass
class PretendTrain:
    name: str
    circuits: list[str]
    """The track circuits it stands in, from the tail to the front."""


class PretendLoconet:
    """The pretend layout as a transport: what TKL writes is answered in what it reads."""

    label = "Låtsas-LocoNet"

    def __init__(
        self,
        wiring: Wiring,
        *,
        clock: Callable[[], float] = time.monotonic,
        movement: float = MOVEMENT_SECONDS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.wiring = wiring
        self.clock = clock
        self.now = now
        self.movement = movement
        self.inputs: dict[int, bool] = {}
        for circuit in wiring.circuits.values():
            self.inputs[circuit.address] = circuit.reversed
        for switch in wiring.switches.values():
            if switch.feedback == FeedbackType.SENSORS:
                for sensor, lies in (
                    (switch.straight, Position.PLUS),
                    (switch.diverging, Position.MINUS),
                ):
                    if sensor is not None:
                        self.inputs[sensor] = self.position(switch.part) == lies
        self.trains: dict[str, PretendTrain] = {}
        self.recorded: list[Recorded] = []
        self._out = bytearray()
        self.closed = False

    @classmethod
    def from_model(
        cls,
        model: StationModel,
        *,
        reversed_: Collection[str] = (),
        clock: Callable[[], float] = time.monotonic,
        movement: float = MOVEMENT_SECONDS,
    ) -> PretendLoconet:
        """The pretend layout wired as the model says, and the rest made up (Wiring.of)."""
        return cls(Wiring.of(model, reversed_=reversed_), clock=clock, movement=movement)

    # --- the transport ------------------------------------------------------------------------

    def write(self, data: bytes) -> None:
        try:
            validate(data)
        except FrameError:
            return  # a garbled message on the bus gets no answer
        self._record("out", data)
        self._out += data  # the echo
        message = decode(data)
        if isinstance(message, SwitchRequest):
            if message.on:
                self._request(message)
        elif isinstance(message, Interrogate):
            self._interrogate(message.group)
        elif isinstance(message, SwitchState):
            self._state(message.address)
        elif isinstance(message, Sv) and not message.reply:
            self._sv(message)

    def read(self, timeout: float) -> bytes:
        self.tick()
        data, self._out = bytes(self._out), bytearray()
        return data

    def close(self) -> None:
        self.closed = True

    # --- answering ----------------------------------------------------------------------------

    def _send(self, data: bytes) -> None:
        self._record("in", data)
        self._out += data

    def _record(self, direction: Literal["in", "out"], data: bytes) -> None:
        self.recorded.append(Recorded(self.now(), direction, data))
        del self.recorded[:-MOST_RECORDED]

    def _request(self, message: SwitchRequest) -> None:
        for switch in self.wiring.switches.values():
            if switch.address != message.address:
                continue
            if switch.target is None and switch.output == message.output:
                if switch.feedback == FeedbackType.CARD:
                    self._send(switch_report(switch.address, switch.output))
                continue
            switch.target, switch.due = message.output, self.clock() + self.movement
            if switch.feedback == FeedbackType.CARD:
                self._send(switch_report(switch.address, None))
            elif switch.feedback == FeedbackType.SENSORS:
                for sensor in (switch.straight, switch.diverging):
                    if sensor is not None:
                        self._input(sensor, False)
        for signal in self.wiring.signals.values():
            if signal.address == message.address:
                signal.output = message.output
                self._send(switch_report(signal.address, signal.output))

    def _interrogate(self, group: int) -> None:
        for address in sorted(self.inputs):
            if (address - 1) >> 3 & 7 == group:
                self._send(sensor_report(address, self.inputs[address]))

    def _state(self, address: int) -> None:
        for switch in self.wiring.switches.values():
            if switch.address == address:
                closed = switch.target is None and switch.output == Output.CLOSED
                self._send(long_ack(OPC_SW_STATE, 0x20 if closed else 0))
                return

    def _sv(self, request: Sv) -> None:
        if request.cmd == SvCommand.DISCOVER:
            for card in self.wiring.cards:
                self._send(identity_reply(request, card.address, card.identity))
            return
        for card in self.wiring.cards:
            if card.address != request.dst:
                continue
            if request.cmd == SvCommand.IDENTIFY:
                self._send(identity_reply(request, card.address, card.identity))
            elif request.cmd == SvCommand.READ:
                self._send(sv_reply(request, dst=card.address, data=[card.sv.get(request.sv, 0)]))
            elif request.cmd == SvCommand.READ4:
                values = [card.sv.get(request.sv + i, 0) for i in range(4)]
                self._send(sv_reply(request, dst=card.address, data=values))

    def tick(self) -> None:
        """The switches that have come to rest report where they lie."""
        now = self.clock()
        for switch in self.wiring.switches.values():
            if switch.target is None or switch.due > now:
                continue
            switch.output, switch.target = switch.target, None
            if switch.feedback == FeedbackType.CARD:
                self._send(switch_report(switch.address, switch.output))
            elif switch.feedback == FeedbackType.SENSORS:
                lies = self.position(switch.part)
                if switch.straight is not None:
                    self._input(switch.straight, lies == Position.PLUS)
                if switch.diverging is not None:
                    self._input(switch.diverging, lies == Position.MINUS)

    def _input(self, address: int, active: bool) -> None:
        if self.inputs.get(address) == active:
            return
        self.inputs[address] = active
        self._send(sensor_report(address, active))

    # --- what the pretend layout says ---------------------------------------------------------

    def position(self, part: str) -> Position | None:
        """Where a switch lies, as the model says it: None while it moves."""
        switch = self.wiring.switches[part]
        if switch.target is not None:
            return None
        return position_for(switch.output, switch.reversed)

    def proceed(self, name: str) -> bool:
        """The signal shows kör."""
        signal = self.wiring.signals[name]
        return signal.output == signal_output(True, signal.reversed)

    def occupied(self, circuit: str) -> bool:
        wired = self.wiring.circuits[circuit]
        return self.inputs.get(wired.address, wired.reversed) != wired.reversed

    # --- what happens on the pretend layout ----------------------------------------------------

    def occupy(self, circuit: str, occupied: bool = True) -> None:
        """A wagon put on a track circuit, or lifted off it: its sensor reports."""
        wired = self.wiring.circuits.get(circuit)
        if wired is None:
            raise KeyError(circuit)
        self._input(wired.address, occupied != wired.reversed)

    def touch_sensor(self, address: int, active: bool) -> None:
        """A sensor by its address, as a finger on the layout."""
        self._input(address, active)

    def lay_by_hand(self, part: str, position: Position) -> None:
        """Someone lays a switch by hand on the layout; its card reports it."""
        switch = self.wiring.switches[part]
        switch.output, switch.target = output_for(position, switch.reversed), None
        if switch.feedback == FeedbackType.CARD:
            self._send(switch_report(switch.address, switch.output))

    def put_train(self, name: str, circuits: list[str]) -> None:
        """A train standing in these track circuits, from its tail to its front."""
        if name in self.trains:
            raise ValueError(f"Tåg {name} står redan på banan.")
        for circuit in circuits:
            self.occupy(circuit)
        self.trains[name] = PretendTrain(name, list(circuits))

    def move_train(self, name: str, circuit: str, length: int = 2) -> None:
        """The train's front into the next track circuit; its tail leaves the one furthest
        behind when it is longer than `length` circuits."""
        train = self.trains[name]
        self.occupy(circuit)
        train.circuits.append(circuit)
        while len(train.circuits) > max(1, length):
            gone = train.circuits.pop(0)
            if gone not in train.circuits:
                self.occupy(gone, False)

    def remove_train(self, name: str) -> None:
        train = self.trains.pop(name)
        for circuit in set(train.circuits):
            self.occupy(circuit, False)

    def received(self) -> list[bytes]:
        """What TKL has written, in order: for the tests."""
        return [r.data for r in self.recorded if r.direction == "out"]

    def sensors(self) -> list[tuple[int, bool]]:
        return sorted(self.inputs.items())


def sensor_reports(data: Iterable[bytes]) -> list[SensorReport]:
    found = []
    for frame_ in data:
        message = decode(frame_)
        if isinstance(message, SensorReport):
            found.append(message)
    return found
