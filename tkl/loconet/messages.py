"""LocoNet's messages: framing, the checksum, and the messages TKL sends and reads.

Ported from cda-tkl (src/protocol.mjs and src/sv2.mjs), whose sources are LocoNet Personal
Edition 1.0, JMRI's monitor and Benny's monitoring of the MGP cards on his layout (9 and 10
October 2026). The byte fixtures in the tests are those frames, word for word.

- A frame is an opcode with bit 7 set, data bytes below 0x80, and a checksum: the XOR of every
  byte is 0xFF. Its length follows from the opcode: 2, 4 or 6 bytes, or the count in its
  second byte.
- OPC_SW_REQ (B0): a switch request, closed (C) or thrown (T), with the output on or off. A
  signal on an MGP card is ordered the same way: kör is closed and stopp thrown, as cda-tkl
  ordered them after the station's JMRI file (a card set the other way is reversed).
- OPC_SW_REP (B1): the switch report. The MGP cards send it in the input format (bit 6 set,
  bit 5 the switch input, bit 4 set for closed); the output format is read too, with both
  bits clear while the switch moves. A signal's card reports its aspect the same way.
- OPC_SW_STATE (BC): a question for a switch's state, answered with a long acknowledge.
- OPC_INPUT_REP (B2): a sensor report, active or passive.
- OPC_LONG_ACK (B4): the long acknowledge, for example a refused switch request.
- E4 09: the Signal10 report with an aspect code, a provisional Czech profile that cda-tkl
  could read but never verified for Swedish aspects. Only read here.
- E5 10: SV2 programming over OPC_PEER_XFER, for Discover, Identify and reading a card's SVs
  (SV Programming Message Formats v13). Nothing here writes to a card.
- The interrogation: switch requests off to the addresses 1017–1020, which JMRI sends at start;
  the MGP input cards answer with a B2 for every input.
- OPC_GPON and OPC_GPOFF (83, 82): power on and off. cda-tkl never sent them, so TKL does not
  either; Lyssna only names them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

OPC_BUSY: Final = 0x81
OPC_GPOFF: Final = 0x82
OPC_GPON: Final = 0x83
OPC_SW_REQ: Final = 0xB0
OPC_SW_REP: Final = 0xB1
OPC_INPUT_REP: Final = 0xB2
OPC_LONG_ACK: Final = 0xB4
OPC_SW_STATE: Final = 0xBC
OPC_SE: Final = 0xE4
OPC_PEER_XFER: Final = 0xE5

SWITCH_ADDRESSES: Final = 2048
SENSOR_ADDRESSES: Final = 4096
SIGNAL_ADDRESSES: Final = 16384
LONGEST: Final = 127


class FrameError(ValueError):
    """A frame that is not LocoNet: the reason in Swedish."""


class Output(StrEnum):
    """A switch output, as LocoNet names it."""

    CLOSED = "C"  # rakt, eller kör för en signal
    THROWN = "T"  # avvikande, eller stopp för en signal


def checksum(data: Iterable[int]) -> int:
    """The byte that makes the XOR of the whole frame 0xFF."""
    value = 0xFF
    for byte in data:
        value ^= byte
    return value


def frame(data: Iterable[int]) -> bytes:
    """The bytes with their checksum."""
    body = bytes(data)
    return body + bytes([checksum(body)])


def length(opcode: int, second: int) -> int:
    """A frame's length from its opcode, and from its second byte for the long ones."""
    return (2, 4, 6, second)[(opcode >> 5) & 3]


def validate(data: bytes) -> bytes:
    """The frame as it is, or FrameError: the opcode, the length, the data and the checksum."""
    if len(data) < 2 or not data[0] & 0x80:
        raise FrameError("Saknad opcode.")
    size = length(data[0], data[1])
    if size < 2 or size > LONGEST or len(data) != size:
        raise FrameError("Fel ramlängd.")
    if any(byte & 0x80 for byte in data[1:]):
        raise FrameError("Fel databyte.")
    every = 0
    for byte in data:
        every ^= byte
    if every != 0xFF:
        raise FrameError("Fel kontrollsumma.")
    return data


def hex_of(data: bytes) -> str:
    """A frame as JMRI's monitor writes it: B0 7A 30 05."""
    return " ".join(f"{byte:02X}" for byte in data)


def from_hex(text: str) -> bytes:
    """A frame from its hex text, validated."""
    parts = text.split()
    if not parts or any(
        len(p) != 2 or any(c not in "0123456789abcdefABCDEF" for c in p) for p in parts
    ):
        raise FrameError("Ogiltig hexram.")
    return validate(bytes(int(p, 16) for p in parts))


def _address(number: int, most: int) -> int:
    if not 1 <= number <= most:
        raise FrameError(f"Adressen {number} ligger utanför 1–{most}.")
    return number - 1


# --- what TKL sends --------------------------------------------------------------------------


def switch_request(address: int, output: Output, on: bool = True) -> bytes:
    """OPC_SW_REQ: a switch or a signal output, closed or thrown, on or off."""
    n = _address(address, SWITCH_ADDRESSES)
    direction = 0x20 if output == Output.CLOSED else 0
    return frame([OPC_SW_REQ, n & 0x7F, (n >> 7) | direction | (0x10 if on else 0)])


def switch_report(address: int, output: Output | None) -> bytes:
    """OPC_SW_REP as the MGP cards send it, in the input format; None, a switch on its way, only
    the pretend LocoNet sends, in the output format with both bits clear."""
    n = _address(address, SWITCH_ADDRESSES)
    bits = 0 if output is None else 0x60 | (0x10 if output == Output.CLOSED else 0)
    return frame([OPC_SW_REP, n & 0x7F, (n >> 7) | bits])


def switch_state(address: int) -> bytes:
    """OPC_SW_STATE: what state is the switch in? The answer is a long acknowledge."""
    n = _address(address, SWITCH_ADDRESSES)
    return frame([OPC_SW_STATE, n & 0x7F, n >> 7])


def sensor_report(address: int, active: bool) -> bytes:
    """OPC_INPUT_REP: a sensor, active or passive."""
    n = _address(address, SENSOR_ADDRESSES)
    high = ((n >> 8) & 0x0F) | (0x20 if n & 1 else 0) | 0x40 | (0x10 if active else 0)
    return frame([OPC_INPUT_REP, (n >> 1) & 0x7F, high])


def signal_report(address: int, code: int) -> bytes:
    """E4 09: the provisional Signal10 report with an aspect code (not a Swedish mapping)."""
    n = _address(address, SIGNAL_ADDRESSES)
    if not 0 <= code <= LONGEST:
        raise FrameError("Ogiltig beskedskod.")
    return frame([OPC_SE, 9, n >> 7, n & 0x7F, 0, 1, code, 0])


def long_ack(opcode: int, ack1: int) -> bytes:
    """OPC_LONG_ACK for a message with this opcode."""
    return frame([OPC_LONG_ACK, opcode & 0x7F, ack1 & 0x7F])


def power(on: bool) -> bytes:
    """OPC_GPON or OPC_GPOFF. TKL never sends it; the tests and the pretend LocoNet do."""
    return frame([OPC_GPON if on else OPC_GPOFF])


def interrogation() -> list[bytes]:
    """The eight frames JMRI sends at start, in its order 1/0/0, 1/0/1, … 0/1/1: switch
    requests off to 1017–1020, where the group's a/c/b bits choose which cards answer."""
    return [
        frame([OPC_SW_REQ, 0x78 | (group & 3), (0x20 if group & 4 else 0) | 0x07])
        for group in (4, 5, 6, 7, 0, 1, 2, 3)
    ]


# --- SV2 over OPC_PEER_XFER -----------------------------------------------------------------


class SvCommand:
    WRITE: Final = 0x01
    READ: Final = 0x02
    MASKED_WRITE: Final = 0x03
    WRITE4: Final = 0x05
    READ4: Final = 0x06
    DISCOVER: Final = 0x07
    IDENTIFY: Final = 0x08
    CHANGE_ADDRESS: Final = 0x09
    RECONFIGURE: Final = 0x0F


SV_NAMES: Final = {
    0x01: "SV skriv",
    0x02: "SV läs",
    0x03: "SV maskad skrivning",
    0x05: "SV skriv 4",
    0x06: "SV läs 4",
    0x07: "Discover",
    0x08: "Identify",
    0x09: "Adressbyte",
    0x0F: "Omstart",
}
MGP_IDENTITY: Final = (126, 1)
"""The MGP cards' manufacturer and developer in the Discover answer (Benny's trace)."""
MGP_PRODUCTS: Final = {6: "Signal10 SE", 9: "servokort med ingångar"}
"""The products known so far. Product 5 (Benny's card 18) is not identified."""
MGP_CHANNELS: Final = {6: 10, 9: 5}
"""Outputs per card, from the base address in SV21 up: Signal10 SE drives ten (LT110–119 on
Benny's bench), the servo card five (the JMRI comments M03-110-1 … M03-110-5)."""
MGP_BASE_SV: Final = 21
"""SV21: the card's base address; output 2 has the address plus one, and so on."""


@dataclass(frozen=True)
class Identity:
    manufacturer: int
    developer: int
    product: int
    serial: int

    @property
    def name(self) -> str:
        if (self.manufacturer, self.developer) == MGP_IDENTITY and self.product in MGP_PRODUCTS:
            return f"MGP {MGP_PRODUCTS[self.product]}"
        return f"produkt {self.product}"


def _check(value: int, most: int, what: str) -> int:
    if not 0 <= value <= most:
        raise FrameError(f"{what} utanför intervallet 0–{most}.")
    return value


def sv_message(
    *, cmd: int, src: int = 1, dst: int = 0, sv: int = 0, data: Iterable[int] = ()
) -> bytes:
    """<E5><10><SRC><SV_CMD><02><SVX1><DST_L><DST_H><SV_L><SV_H><SVX2><D1><D2><D3><D4><CHK>.
    SVX1 and SVX2 carry bit 7 of the four bytes after each, so every data byte stays below 0x80."""
    _check(src, 127, "Avsändare")
    _check(cmd, 127, "SV-kommando")
    _check(dst, 65535, "Kortadress")
    _check(sv, 65535, "SV-nummer")
    given = list(data)
    four = [_check(given[i] if i < len(given) else 0, 255, "Databyte") for i in range(4)]
    dst_l, dst_h, sv_l, sv_h = dst & 0xFF, dst >> 8, sv & 0xFF, sv >> 8

    def high(value: int) -> int:
        return (value >> 7) & 1

    svx1 = 0x10 | high(dst_l) | high(dst_h) << 1 | high(sv_l) << 2 | high(sv_h) << 3
    svx2 = 0x10 | high(four[0]) | high(four[1]) << 1 | high(four[2]) << 2 | high(four[3]) << 3
    low = [b & 0x7F for b in (dst_l, dst_h, sv_l, sv_h)]
    return frame([OPC_PEER_XFER, 0x10, src, cmd, 0x02, svx1, *low, svx2, *(b & 0x7F for b in four)])


def discover(src: int = 1) -> bytes:
    return sv_message(cmd=SvCommand.DISCOVER, src=src)


def identify(dst: int, src: int = 1) -> bytes:
    return sv_message(cmd=SvCommand.IDENTIFY, src=src, dst=dst)


def read_sv(dst: int, sv: int, src: int = 1) -> bytes:
    return sv_message(cmd=SvCommand.READ, src=src, dst=dst, sv=sv)


def read_sv4(dst: int, sv: int, src: int = 1) -> bytes:
    return sv_message(cmd=SvCommand.READ4, src=src, dst=dst, sv=sv)


@dataclass(frozen=True)
class Sv:
    """An SV2 message: a request, or a card's reply (the command with bit 6 set). In a reply
    the card's address is in DST and SRC is the asker's agent number (Benny's trace)."""

    cmd: int
    src: int
    dst: int
    sv: int
    data: tuple[int, int, int, int]

    @property
    def reply(self) -> bool:
        return bool(self.cmd & 0x40)

    @property
    def name(self) -> str:
        said = SV_NAMES.get(self.cmd & ~0x40, f"SV okänt kommando {self.cmd}")
        return f"Svar {said}" if self.reply else said

    @property
    def identity(self) -> Identity | None:
        if self.cmd & ~0x40 not in (SvCommand.DISCOVER, SvCommand.IDENTIFY) or not self.reply:
            return None
        d = self.data
        return Identity(self.sv & 0xFF, self.sv >> 8, d[0] | d[1] << 8, d[2] | d[3] << 8)

    @property
    def card(self) -> int:
        """The card the reply comes from: DST, and SRC only when DST is missing."""
        return self.dst if self.dst > 1 else self.src


def decode_sv(data: bytes) -> Sv | None:
    """The SV2 message, or None when the frame is not one: type 02 and the upper nibble 1 in
    both SVX1 and SVX2."""
    if (
        len(data) != 16
        or data[0] != OPC_PEER_XFER
        or data[1] != 0x10
        or data[4] != 0x02
        or data[5] & 0xF0 != 0x10
        or data[10] & 0xF0 != 0x10
    ):
        return None

    def with7(value: int, bit: int, carrier: int) -> int:
        return value | ((carrier >> bit) & 1) << 7

    dst = with7(data[6], 0, data[5]) | with7(data[7], 1, data[5]) << 8
    sv = with7(data[8], 2, data[5]) | with7(data[9], 3, data[5]) << 8
    d = tuple(with7(data[11 + k], k, data[10]) for k in range(4))
    return Sv(cmd=data[3], src=data[2], dst=dst, sv=sv, data=(d[0], d[1], d[2], d[3]))


def sv_reply(request: Sv, *, dst: int, sv: int | None = None, data: Iterable[int] = ()) -> bytes:
    """The answer to a request: the same command with bit 6 set, the card in DST."""
    return sv_message(
        cmd=request.cmd | 0x40,
        src=request.src,
        dst=dst,
        sv=request.sv if sv is None else sv,
        data=data,
    )


def identity_reply(request: Sv, address: int, identity: Identity) -> bytes:
    """A card's answer to Discover or Identify: its identity in SV and data."""
    return sv_message(
        cmd=request.cmd | 0x40,
        src=request.src,
        dst=address,
        sv=(identity.manufacturer & 0xFF) | (identity.developer & 0xFF) << 8,
        data=[
            identity.product & 0xFF,
            identity.product >> 8,
            identity.serial & 0xFF,
            identity.serial >> 8,
        ],
    )


# --- reading a frame -------------------------------------------------------------------------


@dataclass(frozen=True)
class SwitchRequest:
    address: int
    output: Output
    on: bool


@dataclass(frozen=True)
class SwitchReport:
    address: int
    output: Output | None
    """None: the switch is on its way (the output format with both bits clear)."""
    input: bool = False
    """The input format, as the MGP cards report."""


@dataclass(frozen=True)
class SwitchState:
    address: int


@dataclass(frozen=True)
class SensorReport:
    address: int
    active: bool


@dataclass(frozen=True)
class SignalReport:
    address: int
    code: int


@dataclass(frozen=True)
class LongAck:
    opcode: int
    ack1: int

    @property
    def closed(self) -> bool | None:
        """For OPC_SW_STATE: bit 5 is closed, as JMRI reads it."""
        return bool(self.ack1 & 0x20) if self.opcode == OPC_SW_STATE & 0x7F else None


@dataclass(frozen=True)
class Interrogate:
    group: int


@dataclass(frozen=True)
class Power:
    on: bool


@dataclass(frozen=True)
class Busy:
    pass


@dataclass(frozen=True)
class Unknown:
    opcode: int
    note: str


Message = (
    SwitchRequest
    | SwitchReport
    | SwitchState
    | SensorReport
    | SignalReport
    | LongAck
    | Interrogate
    | Power
    | Busy
    | Sv
    | Unknown
)


def decode(data: bytes) -> Message:
    """What a frame says, or FrameError. A frame TKL does not read is Unknown, with a note."""
    validate(data)
    op = data[0]
    a = data[1] if len(data) > 1 else 0
    b = data[2] if len(data) > 2 else 0
    switch_address = 1 + a + ((b & 0x0F) << 7)
    if op == OPC_SW_REQ:
        if a & 0xFC == 0x78 and b & 0xDF == 0x07:
            return Interrogate(((b & 0x20) >> 3) | (a & 3))
        output = Output.CLOSED if b & 0x20 else Output.THROWN
        return SwitchRequest(switch_address, output, bool(b & 0x10))
    if op == OPC_SW_REP:
        if b & 0x40:
            if not b & 0x20:
                return Unknown(op, "Hjälpingången på växelkortet, inget läge.")
            closed = bool(b & 0x10)
            return SwitchReport(switch_address, Output.CLOSED if closed else Output.THROWN, True)
        bits = b & 0x30
        found = Output.CLOSED if bits == 0x20 else Output.THROWN if bits == 0x10 else None
        return SwitchReport(switch_address, found)
    if op == OPC_SW_STATE:
        return SwitchState(switch_address)
    if op == OPC_INPUT_REP:
        address = 1 + 2 * (a + 128 * (b & 0x0F)) + ((b & 0x20) >> 5)
        return SensorReport(address, bool(b & 0x10))
    if op == OPC_LONG_ACK:
        return LongAck(a, b)
    if op == OPC_SE and len(data) == 9 and data[4] == 0 and data[5] == 1 and data[7] == 0:
        return SignalReport(1 + data[2] * 128 + data[3], data[6])
    if op == OPC_PEER_XFER:
        sv = decode_sv(data)
        if sv is not None:
            return sv
        return Unknown(op, "Peer-to-peer utan SV2-signatur. Visas utan tolkning.")
    if op in (OPC_GPON, OPC_GPOFF):
        return Power(op == OPC_GPON)
    if op == OPC_BUSY:
        return Busy()
    return Unknown(op, "Okänd opcode. Kontrollsumman stämmer, ramen visas som den är.")


@dataclass
class FrameReader:
    """Frames out of a byte stream, as a serial port gives it in pieces. Garbage before an
    opcode is skipped, a frame cut short by a new opcode is an error, and nothing is made up."""

    on_error: Callable[[FrameError], None] = lambda _error: None
    _pending: list[int] = field(default_factory=list)

    def push(self, chunk: bytes) -> list[bytes]:
        found: list[bytes] = []
        for byte in chunk:
            if byte & 0x80:
                if self._pending:
                    self.on_error(FrameError("Avbruten ram."))
                self._pending = [byte]
                continue
            if not self._pending:
                continue
            self._pending.append(byte)
            size = length(self._pending[0], self._pending[1])
            if size < 2 or size > LONGEST:
                self.on_error(FrameError("Fel ramlängd."))
                self._pending = []
                continue
            if len(self._pending) == size:
                message = bytes(self._pending)
                self._pending = []
                try:
                    found.append(validate(message))
                except FrameError as error:
                    self.on_error(error)
        return found
