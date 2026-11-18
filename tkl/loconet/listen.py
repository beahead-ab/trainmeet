"""Lyssna, behind Felsök (STUDIO-24): the last LocoNet messages, decoded and in Swedish.

Ported from cda-tkl's telegram recorder and communication diagnostics: each message with its
time, its direction, its bytes as JMRI's monitor writes them, what it says, and the station's
objects on its address with what it means for them, the polarity counted. A message TKL does
not read is shown as it is, with a note. Nothing here changes an object's state, and LocoNet
carries no secrets; the port itself is not in the list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal

from contracts.station_model import Position, StationModel
from contracts.tkl import AddressState, ObjectKind, TklHeard, TklListen
from tkl.loconet.messages import (
    OPC_SW_REQ,
    OPC_SW_STATE,
    Busy,
    FrameError,
    Interrogate,
    LongAck,
    Message,
    Output,
    Power,
    SensorReport,
    SignalReport,
    Sv,
    SwitchReport,
    SwitchRequest,
    SwitchState,
    Unknown,
    decode,
    hex_of,
)
from tkl.loconet.objects import Wired, objects, position_for, signal_output

MOST: Final = 200
OUTPUT_WORD: Final = {Output.CLOSED: "closed (C)", Output.THROWN: "thrown (T)"}
POSITION_WORD: Final = {Position.PLUS: "rakt (+)", Position.MINUS: "avvikande (\N{MINUS SIGN})"}


def describe(message: Message) -> str:
    """What a message says, without knowing the station."""
    if isinstance(message, SwitchRequest):
        state = "på" if message.on else "av"
        return f"Order till adress {message.address}: {OUTPUT_WORD[message.output]}, {state}."
    if isinstance(message, SwitchReport):
        if message.output is None:
            return f"Växelrapport från adress {message.address}: i rörelse."
        return f"Växelrapport från adress {message.address}: {OUTPUT_WORD[message.output]}."
    if isinstance(message, SensorReport):
        said = "slog till (aktiv)" if message.active else "släppte (passiv)"
        return f"Givare {message.address}: {said}."
    if isinstance(message, SwitchState):
        return f"Fråga om läget för adress {message.address}."
    if isinstance(message, LongAck):
        if message.opcode == OPC_SW_REQ & 0x7F and message.ack1 == 0:
            return "Långt kvitto: kommandostationen avvisade en växelorder."
        if message.opcode == OPC_SW_STATE & 0x7F:
            lies = "closed (C)" if message.closed else "thrown (T)"
            return f"Långt kvitto på frågan om läget: {lies}."
        return f"Långt kvitto på {message.opcode | 0x80:02X}: {message.ack1}."
    if isinstance(message, Interrogate):
        g = message.group
        return (
            f"Avfrågning, grupp {g >> 2}/{(g >> 1) & 1}/{g & 1}: ingångskorten i gruppen svarar "
            "med sina ingångar."
        )
    if isinstance(message, SignalReport):
        return (
            f"Signalbesked från adress {message.address}: kod {message.code}. Preliminär "
            "Signal10-form, inte en svensk beskedstabell."
        )
    if isinstance(message, Sv):
        identity = message.identity
        if identity is not None:
            return (
                f"{message.name} från kort {message.card}: {identity.name}, serienummer "
                f"{identity.serial}."
            )
        if message.cmd == 0x07:
            return "Discover: alla kort svarar med sin identitet."
        data = " ".join(str(d) for d in message.data)
        towards = "från" if message.reply else "till"
        return f"{message.name} {towards} kort {message.dst}, SV {message.sv}, data {data}."
    if isinstance(message, Power):
        return "Spänningen på (OPC_GPON)." if message.on else "Spänningen av (OPC_GPOFF)."
    if isinstance(message, Busy):
        return "Upptagen (OPC_BUSY): kommandostationens utfyllnad."
    assert isinstance(message, Unknown)
    return message.note


def meaning(message: Message, found: list[Wired]) -> list[str]:
    """The objects on the message's address, and what it means for each."""
    said: list[str] = []
    for o in found:
        if o.address is None or o.state == AddressState.WITHOUT:
            continue
        number = o.address.number
        if isinstance(message, SwitchRequest | SwitchReport) and number == message.address:
            output = message.output
            if output is None:
                if o.kind == ObjectKind.SWITCH:
                    said.append(f"{o.said} i rörelse")
            elif o.kind == ObjectKind.SWITCH:
                said.append(f"{o.said}: {POSITION_WORD[position_for(output, o.reversed)]}")
            elif o.kind == ObjectKind.SIGNAL:
                proceed = output == signal_output(True, o.reversed)
                said.append(f"{o.said}: {'kör' if proceed else 'stopp'}")
        if isinstance(message, SensorReport):
            if o.kind == ObjectKind.TRACK_CIRCUIT and number == message.address:
                occupied = message.active != o.reversed
                said.append(f"{o.said}: {'belagd' if occupied else 'fri'}")
            if o.kind == ObjectKind.SWITCH and o.feedback is not None:
                for sensor, lies in (
                    (o.feedback.straight, "rakt"),
                    (o.feedback.diverging, "avvikande"),
                ):
                    if sensor is not None and sensor.number == message.address:
                        level = "aktiv" if message.active else "passiv"
                        said.append(f"{o.said}: givaren för {lies} {level}")
    return said


@dataclass(frozen=True)
class Heard:
    at: datetime
    direction: Literal["in", "out"]
    data: bytes
    problem: str | None = None


@dataclass
class Listening:
    """The last messages, both ways, newest first."""

    most: int = MOST
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    heard: list[Heard] = field(default_factory=list)

    def hear(
        self, direction: Literal["in", "out"], data: bytes, problem: str | None = None
    ) -> None:
        self.heard.insert(0, Heard(self.now(), direction, data, problem))
        del self.heard[self.most :]

    def problem(self, error: FrameError) -> None:
        self.hear("in", b"", f"Ogiltig ram: {error}")

    def clear(self) -> None:
        self.heard.clear()

    def view(self, model: StationModel | None, connected: bool) -> TklListen:
        found = objects(model) if model is not None else []
        shown: list[TklHeard] = []
        for h in self.heard:
            if h.problem is not None:
                shown.append(TklHeard(at=h.at, direction=h.direction, hex="–", text=h.problem))
                continue
            try:
                message = decode(h.data)
            except FrameError as error:
                shown.append(
                    TklHeard(at=h.at, direction=h.direction, hex=hex_of(h.data), text=str(error))
                )
                continue
            shown.append(
                TklHeard(
                    at=h.at,
                    direction=h.direction,
                    hex=hex_of(h.data),
                    text=describe(message),
                    objects=meaning(message, found),
                )
            )
        return TklListen(connected=connected, messages=shown)
