"""The station model's objects as LocoNet sees them: what Koppla in connects (STUDIO-17).

Every switch part, signal and track circuit has one of four states:

- grey: not connected, no address;
- yellow: an address is given, by the owner, by the switch's number as the default
  (STUDIO-19, STD-17), or from a source such as JMRI, but it is not confirmed on the layout;
- green: confirmed on the layout in Koppla in, by touching (STUDIO-04): the address's own
  origin is confirmed;
- Utan adress: chosen explicitly, for a manual switch and a virtual signal (TKL26). A switch
  the interlocking never lays, manual, planned or not laid, is Utan adress too; a track circuit
  without a sensor is "without" in the model.

The polarity is the address's (STUDIO-24): a reversed switch lies straight when its card's
output is thrown, a reversed signal shows kör when it is thrown, and a reversed sensor is
occupied when it is passive. The switch's feedback is from the card, from two sensors, none,
or manual (STUDIO-24).

The bus is the objects that run now, by address: it reads a report into what it says about the
station, and makes the order for a switch or a signal. Pure Python without I/O.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from contracts.station_model import (
    WITHOUT,
    Address,
    FeedbackType,
    Origin,
    Position,
    Source,
    StationModel,
    SwitchControl,
    SwitchFeedback,
    SwitchType,
)
from contracts.tkl import AddressState, ObjectKind, TklAspect, TklFieldMode
from tkl.loconet.messages import (
    SWITCH_ADDRESSES,
    Message,
    Output,
    SensorReport,
    SwitchReport,
    switch_request,
)

KIND_WORD: Final = {
    ObjectKind.SWITCH: "växel",
    ObjectKind.SIGNAL: "signal",
    ObjectKind.TRACK_CIRCUIT: "spårledningen",
}
RUNNING: Final = {
    TklFieldMode.LOCONET: frozenset({AddressState.GREEN}),
    TklFieldMode.PRETEND: frozenset({AddressState.GREEN, AddressState.YELLOW}),
}
"""The objects that run on the bus besides Utan adress: with LocoNet only the green ones
(STV-17); against the pretend LocoNet the yellow ones too, so that Prova can try a station
before every address is confirmed on the layout (STUDIO-21)."""
STATE_WORD: Final = {
    AddressState.GREY: "grå",
    AddressState.YELLOW: "gul",
    AddressState.GREEN: "grön",
    AddressState.WITHOUT: "Utan adress",
}


@dataclass(frozen=True)
class Wired:
    """One object with its address as the bus uses it."""

    kind: ObjectKind
    name: str
    address: Address | None
    """The address that counts: the model's, else the switch's number as the default."""
    default: bool
    state: AddressState
    feedback: SwitchFeedback | None = None
    control: SwitchControl | None = None
    note: str | None = None
    derailer: bool = False
    """A derailer (spårspärr, TKL129): driven and reported as a switch, + av and - på."""
    drop_delay: float = 0.0
    """A track circuit's släpptid in seconds (STUDIO-35)."""

    @property
    def reversed(self) -> bool:
        return self.address.reversed if self.address is not None else False

    @property
    def said(self) -> str:
        """As a sentence names it: växel 1, signal 21, Spår 3."""
        if self.kind == ObjectKind.TRACK_CIRCUIT:
            return self.name
        if self.derailer:
            return f"spårspärr {self.name}"
        return f"{KIND_WORD[self.kind]} {self.name}"

    @property
    def word(self) -> str:
        """The object's kind as a sentence begins: Växel, Spårspärr, Signal."""
        return self.said.removesuffix(f" {self.name}").capitalize()


def default_address(number: str) -> Address | None:
    """STUDIO-19: a switch's number is its LocoNet address as the default, when it is a number
    LocoNet can address. Vx4 or 22a has none."""
    if number.isascii() and number.isdigit() and 1 <= int(number) <= SWITCH_ADDRESSES:
        return Address(number=int(number))
    return None


def state_of(address: Address | None, without: bool) -> AddressState:
    if without:
        return AddressState.WITHOUT
    if address is None:
        return AddressState.GREY
    if address.origin is not None and address.origin.confirmed:
        return AddressState.GREEN
    return AddressState.YELLOW


def confirmed(address: Address) -> Address:
    """The address as it is once the owner has seen it on the layout: green."""
    return address.model_copy(update={"origin": Origin(source=Source.LAYOUT, confirmed=True)})


_NOT_RUN: Final = {
    SwitchControl.MANUAL: "Manuell: läggs för hand.",
    SwitchControl.PLANNED: "Planerad: finns inte än.",
    SwitchControl.NOT_LAID: "Läggs inte från ställverket.",
}


def objects(model: StationModel) -> list[Wired]:
    """Every switch part, signal and track circuit, in the model's order."""
    found: list[Wired] = []
    for switch in model.switches:
        if switch.type == SwitchType.CROSSING:
            continue
        units = (
            [(switch.number, switch.address, switch.feedback)]
            if switch.type in (SwitchType.ORDINARY, SwitchType.Y)
            else [(p.number, p.address, p.feedback) for p in switch.parts]
        )
        for number, address, feedback in units:
            if switch.control != SwitchControl.TKL:
                found.append(
                    Wired(
                        ObjectKind.SWITCH,
                        number,
                        None,
                        False,
                        AddressState.WITHOUT,
                        feedback,
                        switch.control,
                        _NOT_RUN[switch.control],
                    )
                )
                continue
            effective = address or default_address(number)
            found.append(
                Wired(
                    ObjectKind.SWITCH,
                    number,
                    effective,
                    address is None and effective is not None,
                    state_of(effective, False),
                    feedback,
                    switch.control,
                )
            )
    for derailer in model.derailers:
        if derailer.control != SwitchControl.TKL:
            found.append(
                Wired(
                    ObjectKind.SWITCH,
                    derailer.number,
                    None,
                    False,
                    AddressState.WITHOUT,
                    derailer.feedback,
                    derailer.control,
                    _NOT_RUN[derailer.control],
                    derailer=True,
                )
            )
            continue
        effective = derailer.address or default_address(derailer.number)
        found.append(
            Wired(
                ObjectKind.SWITCH,
                derailer.number,
                effective,
                derailer.address is None and effective is not None,
                state_of(effective, False),
                derailer.feedback,
                derailer.control,
                derailer=True,
            )
        )
    for signal in model.signals:
        given = signal.address
        without = given == WITHOUT
        address = given if isinstance(given, Address) else None
        note = "Virtuell: visas bara i panelen." if without else None
        if signal.planned:
            note = "Planerad: finns inte än."
        found.append(
            Wired(
                ObjectKind.SIGNAL,
                signal.name,
                address,
                False,
                state_of(address, without),
                note=note,
            )
        )
    for circuit in model.track_circuits:
        detection = circuit.detection
        without = detection == WITHOUT
        address = detection if isinstance(detection, Address) else None
        found.append(
            Wired(
                ObjectKind.TRACK_CIRCUIT,
                circuit.name,
                address,
                False,
                state_of(address, without),
                note="Utan givare." if without else None,
                drop_delay=circuit.drop_delay,
            )
        )
    return found


def find(model: StationModel, kind: ObjectKind, name: str) -> Wired | None:
    return next((o for o in objects(model) if o.kind == kind and o.name == name), None)


def states(model: StationModel) -> dict[tuple[ObjectKind, str], AddressState]:
    return {(o.kind, o.name): o.state for o in objects(model)}


class Keep:
    """A field left as it is in `changed`."""


KEEP: Final = Keep()


def changed(
    model: StationModel,
    kind: ObjectKind,
    name: str,
    *,
    address: Address | str | Keep | None = KEEP,
    feedback: SwitchFeedback | Keep | None = KEEP,
    control: SwitchControl | Keep = KEEP,
    drop_delay: float | Keep = KEEP,
) -> StationModel:
    """The model with one object's address, feedback or control changed, or a track circuit's
    släpptid (STUDIO-35). An address of "without" is Utan adress, for a signal or a track
    circuit. KeyError for an unknown name."""
    if kind == ObjectKind.SWITCH:
        switches = list(model.switches)
        for i, switch in enumerate(switches):
            update: dict[str, object] = {}
            if switch.type in (SwitchType.ORDINARY, SwitchType.Y) and switch.number == name:
                if not isinstance(address, Keep):
                    update["address"] = address
                if not isinstance(feedback, Keep):
                    update["feedback"] = feedback
            elif any(p.number == name for p in switch.parts):
                own: dict[str, object] = {}
                if not isinstance(address, Keep):
                    own["address"] = address
                if not isinstance(feedback, Keep):
                    own["feedback"] = feedback
                update["parts"] = [
                    p.model_copy(update=own) if p.number == name else p for p in switch.parts
                ]
            else:
                continue
            if not isinstance(control, Keep):
                update["control"] = control
            switches[i] = switch.model_copy(update=update)
            return model.model_copy(update={"switches": switches})
        derailers = list(model.derailers)
        for i, derailer in enumerate(derailers):
            if derailer.number != name:
                continue
            update = {}
            if not isinstance(address, Keep):
                update["address"] = address
            if not isinstance(feedback, Keep):
                update["feedback"] = feedback
            if not isinstance(control, Keep):
                update["control"] = control
            derailers[i] = derailer.model_copy(update=update)
            return model.model_copy(update={"derailers": derailers})
        raise KeyError(name)
    if kind == ObjectKind.SIGNAL:
        signals = list(model.signals)
        for i, signal in enumerate(signals):
            if signal.name == name:
                if not isinstance(address, Keep):
                    signals[i] = signal.model_copy(update={"address": address})
                return model.model_copy(update={"signals": signals})
        raise KeyError(name)
    circuits = list(model.track_circuits)
    for i, circuit in enumerate(circuits):
        if circuit.name == name:
            update = {}
            if not isinstance(address, Keep):
                update["detection"] = address
            if not isinstance(drop_delay, Keep):
                update["drop_delay"] = drop_delay
            circuits[i] = circuit.model_copy(update=update)
            return model.model_copy(update={"track_circuits": circuits})
    raise KeyError(name)


def explicit(model: StationModel) -> bool:
    """The model has an address of its own somewhere: level 3 can be turned on."""
    for switch in model.switches:
        if switch.address is not None or any(p.address is not None for p in switch.parts):
            return True
    if any(d.address is not None for d in model.derailers):
        return True
    return any(isinstance(s.address, Address) for s in model.signals) or any(
        isinstance(c.detection, Address) for c in model.track_circuits
    )


# --- the bus ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SwitchReported:
    part: str
    position: Position | None
    """None: on its way, or the two sensors disagree."""


@dataclass(frozen=True)
class SectionReported:
    section: str
    occupied: bool


@dataclass(frozen=True)
class SignalReported:
    name: str
    aspect: TklAspect


FieldReport = SwitchReported | SectionReported | SignalReported


def output_for(position: Position, reversed_: bool) -> Output:
    """The card's output for a switch position: straight is closed unless reversed."""
    straight = position == Position.PLUS
    return Output.CLOSED if straight != reversed_ else Output.THROWN


def position_for(output: Output, reversed_: bool) -> Position:
    straight = (output == Output.CLOSED) != reversed_
    return Position.PLUS if straight else Position.MINUS


def signal_output(proceed: bool, reversed_: bool) -> Output:
    """A signal's output: kör is closed and stopp thrown, as cda-tkl ordered them, unless
    reversed."""
    return Output.CLOSED if proceed != reversed_ else Output.THROWN


class Bus:
    """The objects in the given states, by address, for the interlocking at level 3."""

    def __init__(self, model: StationModel, running: Collection[AddressState]) -> None:
        self.objects = [o for o in objects(model) if o.state in running and o.address]
        self.by_name = {(o.kind, o.name): o for o in self.objects}
        self.outputs: dict[int, list[Wired]] = {}
        self.inputs: dict[int, list[Wired]] = {}
        self.feedback_inputs: dict[int, list[tuple[Wired, Position]]] = {}
        self._input: dict[int, bool] = {}
        for o in self.objects:
            assert o.address is not None
            if o.kind == ObjectKind.TRACK_CIRCUIT:
                self.inputs.setdefault(o.address.number, []).append(o)
                continue
            self.outputs.setdefault(o.address.number, []).append(o)
            if o.kind == ObjectKind.SWITCH and self.feedback(o) == FeedbackType.SENSORS:
                assert o.feedback is not None
                for sensor, shows in (
                    (o.feedback.straight, Position.PLUS),
                    (o.feedback.diverging, Position.MINUS),
                ):
                    if sensor is not None:
                        self.feedback_inputs.setdefault(sensor.number, []).append((o, shows))

    @staticmethod
    def feedback(wired: Wired) -> FeedbackType:
        """The switch's feedback; from the card when the model does not say."""
        return wired.feedback.type if wired.feedback is not None else FeedbackType.CARD

    def reports(self, message: Message) -> list[FieldReport]:
        """What a message says about the station: nothing for one the bus does not know."""
        found: list[FieldReport] = []
        if isinstance(message, SwitchReport):
            for o in self.outputs.get(message.address, []):
                reversed_ = o.reversed
                if o.kind == ObjectKind.SIGNAL:
                    if message.output is not None:
                        proceed = (message.output == Output.CLOSED) != reversed_
                        found.append(
                            SignalReported(o.name, TklAspect.PROCEED if proceed else TklAspect.STOP)
                        )
                    continue
                if self.feedback(o) != FeedbackType.CARD:
                    continue
                position = (
                    None if message.output is None else position_for(message.output, reversed_)
                )
                found.append(SwitchReported(o.name, position))
        if isinstance(message, SensorReport):
            self._input[message.address] = message.active
            for o in self.inputs.get(message.address, []):
                found.append(SectionReported(o.name, message.active != o.reversed))
            for o, _ in self.feedback_inputs.get(message.address, []):
                found.append(SwitchReported(o.name, self._sensed(o)))
        return found

    def _sensed(self, wired: Wired) -> Position | None:
        """Two sensors: the position whose sensor is active while the other is passive."""
        feedback = wired.feedback
        if feedback is None or feedback.straight is None or feedback.diverging is None:
            return None
        straight = self._input.get(feedback.straight.number)
        diverging = self._input.get(feedback.diverging.number)
        if straight is True and diverging is False:
            return Position.PLUS
        if diverging is True and straight is False:
            return Position.MINUS
        return None

    def switch_order(self, part: str, position: Position) -> bytes | None:
        o = self.by_name.get((ObjectKind.SWITCH, part))
        if o is None or o.address is None:
            return None
        return switch_request(o.address.number, output_for(position, o.reversed))

    def signal_order(self, name: str, aspect: TklAspect) -> bytes | None:
        o = self.by_name.get((ObjectKind.SIGNAL, name))
        if o is None or o.address is None:
            return None
        proceed = aspect != TklAspect.STOP
        return switch_request(o.address.number, signal_output(proceed, o.reversed))

    def silent(self, part: str) -> bool:
        """A switch without feedback: TKL takes the order as the position."""
        o = self.by_name.get((ObjectKind.SWITCH, part))
        return o is not None and self.feedback(o) == FeedbackType.NONE
