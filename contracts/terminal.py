"""The terminal protocol: the 16×2 profile, for TMBoxes that do not draw their own screen.

Drift draws the screen (16×2 or 20×4) and the box sends key presses. This is exactly the old
Server's terminal16 profile (docs/protocol/terminal16, Server 4.24), so boxes with firmware 0.7
or later work without reflashing. The TMBox logic is not redesigned (decided 1 November): the
menus, screens, keys and flows are ported as they are, with their tests.

Physical boxes, over MQTT (QoS 1, no retain, clean session, keepalive 10 s, no login; found
with DNS-SD `_tmbox._tcp`, TXT `protocol=…` and `server_id=…`):

    box → hub   tmbox/terminal/device/<id>/hello      Hello
    box → hub   tmbox/terminal/device/<id>/presence   Presence
    box → hub   tmbox/terminal/device/<id>/command    KeyPress
    hub → box   tmbox/terminal/device/<id>/alive      Alive
    hub → box   tmbox/terminal/device/<id>/frame      FrameMessage
    hub → box   tmbox/terminal/device/<id>/ack        Ack

TMBox web, in the browser: the same frames and key presses over HTTP and an event stream,
drawn by the same code in Drift, so the two cannot behave differently:

    POST /api/terminal/session    WebLogin -> WebSession
    GET  /api/terminal/frame      Frame
    POST /api/terminal/keys       KeyPress -> Ack
    GET  /api/terminal/events     the frame again whenever it changes (text/event-stream)

Each login creates a separate box under Väntar. The dispatcher assigns its client_id
to a place and side through Drift's API. The tab keeps its session key separately
and uses Authorization: Bearer for frames, keys and SSE (using fetch). The server
checks the assignment on each request. Keys never travel in URLs or logs.

New in the next generation, without changing how the box works: each box gets its own queue
in Drift, so one hiccup never stalls all boxes. Physical boxes over MQTT are accepted as today,
without a key.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, ValidationError, field_validator

from contracts.common import Contract, Id, Text

TOPIC_PREFIX: Final = "tmbox/terminal/device/"
PROFILE: Final = "server-16x2-pilot"  # the value the old Server sends and the firmware knows

# The values the old Server and the firmware agree on (terminal16 README, "Värden").
MAX_SESSIONS: Final = 256
SESSION_IDLE_SECONDS: Final = 45
MAX_PAYLOAD_BYTES: Final = 4096
INPUT_GUARD_MS: Final = 500
NOTICE_SECONDS: Final = 3
ENTRY_MAX_LENGTH: Final = 5
ATTENTION_WINDOW_SECONDS: Final = 2
DEVICE_ONLINE_SECONDS: Final = 20
DEVICE_OFFLINE_SECONDS: Final = 900

Key = Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B", "C", "D", "#", "*"]


class DisplaySize(Contract):
    """16×2 or 20×4. Anything else, or nothing, counts as 16×2; a box is never shut out."""

    rows: Literal[2, 4] = 2
    cols: Literal[16, 20] = 16


def known_size(value: object) -> DisplaySize | None:
    """A size the box announced, or None (16×2) for anything else (old Server: 4×16, 1×8,
    "4x20" and [4, 20] all give a 16×2, and the box is not turned away)."""
    if value is None or isinstance(value, DisplaySize):
        return value
    try:
        size = DisplaySize.model_validate(value, strict=True)
    except ValidationError:
        return None
    return size if (size.rows, size.cols) in {(2, 16), (4, 20)} else None


class Hello(Contract):
    device_code: Text
    model: Text
    firmware_version: Text
    hardware_version: Text
    display: DisplaySize | None = None
    boot: Text = Field(description="Ny för varje anslutning; alla meddelanden bär den.")

    @field_validator("display", mode="before")
    @classmethod
    def _any_size(cls, value: object) -> DisplaySize | None:
        return known_size(value)


class Presence(Contract):
    nonce: Text
    boot: Text


class Alive(Contract):
    boot: Text
    nonce: Text | None = None


class KeyPress(Contract):
    command_id: Text = Field(description="<boot>-<n>, unik per boot.")
    view_token: Text = Field(description="Binder trycket till bilden det gjordes på.")
    key: Key
    train_number: Text | None = Field(default=None, pattern=r"^[0-9]{1,5}$")
    entry_context: Text | None = None
    boot: Text | None = Field(default=None, description="Bara över MQTT.")


class WebLogin(Contract):
    name: Text
    code: Text = Field(description="Lokal kod för träffen. Skrivs aldrig ut i loggen.")
    display: DisplaySize | None = Field(
        default=None, description="Boxens storlek, som i hello. Utelämnad är 16×2."
    )

    @field_validator("display", mode="before")
    @classmethod
    def _any_size(cls, value: object) -> DisplaySize | None:
        return known_size(value)


class WebSession(Contract):
    client_id: Id
    session_key: Text = Field(description="Boxens sessionsnyckel. Skrivs aldrig ut i loggen.")


class Glyph(Contract):
    slot: int = Field(ge=0, le=7)
    character: str = Field(min_length=1, max_length=1)
    rows: list[int] = Field(min_length=8, max_length=8)


class Lcd(Contract):
    encoding: Literal["hd44780-5x8-cgram-v1"] = "hd44780-5x8-cgram-v1"
    cells: list[list[int]]
    glyphs: list[Glyph] = Field(default_factory=list, max_length=8)


class KeyInfo(Contract):
    label: Text
    short: str = Field(max_length=12, description="Ordet en telefon skriver under tangenten.")
    acts: bool = Field(description="Sant när tangenten ändrar trafiken.")


class AttentionKind(StrEnum):
    """What the box should beep for, most important first. The box picks the tones."""

    INCOMING_REQUEST = "incoming_request"
    REQUEST_DENIED = "request_denied"
    REQUEST_APPROVED = "request_approved"
    INCOMING_TRAIN = "incoming_train"


class Attention(Contract):
    epoch: Text
    seq: int = Field(ge=0)
    kind: AttentionKind | None = None


class Entry(Contract):
    context: Text
    max_length: int = ENTRY_MAX_LENGTH
    lines: list[str]
    lcd: Lcd
    row: int = 0
    column: int = 5
    commit: Key = "#"
    cancel: Key = "*"
    erase: Key = "B"
    shortcut: Key = "A"
    labels: dict[str, Text] = Field(default_factory=dict)
    short: dict[str, str] = Field(default_factory=dict)


class Frame(Contract):
    """One screen. The old Server sends more fields (requests, active, status, upcoming ...);
    they are kept as they are, since unknown fields are kept."""

    profile: Text = PROFILE
    device_id: Text
    station: Text
    station_code: Text
    rows: Literal[2, 4]
    cols: Literal[16, 20]
    lines: list[str] = Field(description="Exakt rows rader, var och en exakt cols tecken.")
    lcd: Lcd
    attention: Attention
    view_token: Text
    revision: int = Field(ge=0)
    view_revision: int = Field(ge=0)
    input_guard_ms: int = INPUT_GUARD_MS
    language: Text
    keys: dict[str, KeyInfo]
    entry: Entry


class FrameMessage(Contract):
    boot: Text
    frame: Frame


class AckStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class Ack(Contract):
    status: AckStatus
    message: str = Field(default="", description="En text att visa, på boxens språk.")
    command_id: Text
    boot: Text | None = None
    frame: Frame
