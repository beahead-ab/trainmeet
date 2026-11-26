"""Träffens skärmar (TV, 1920 × 1080): a screen joins with the meet's code, waits under Väntar
and shows the view the dispatcher gives it in Klienter (S3, S4). The clock comes in two
built-in styles, analog and digital (H74), and a meet may show its own face, custom:<id>
(F13, H75). The track overview, the train graph and the overview draw on the meet as it
runs (ärende 70).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from contracts.common import Contract, Id, Text, Weekday
from contracts.drift import Now
from contracts.station import Clock


class ScreenView(StrEnum):
    CLOCK = "clock"  # Klocka, analog (H74)
    CLOCK_DIGITAL = "clock_digital"  # Klocka, digital (H74)
    TRACKS = "tracks"  # Banöversikt (SKARM-21, H47)
    GRAPH = "graph"  # Tågdiagram (SKARM-18)
    OVERVIEW = "overview"  # Översikt (SKARM-18)


class ScreenLogin(Contract):
    name: str = Field(min_length=1, max_length=40)
    code: Text = Field(description="Träffens kod. Skrivs aldrig ut i loggen.")


class ScreenSession(Contract):
    client_id: Id
    session_key: Text = Field(description="Skärmens nyckel. Skrivs aldrig ut i loggen.")


class ShowView(Contract):
    """The dispatcher gives a screen its view; none sends it back to Väntar."""

    client_id: Id
    view: ScreenView | None = None


class ScreenShare(Contract):
    """QR-koderna i klockans hörn (SKARM-18): 1 · Wi-Fi och 2 · Träffen, som i Dela träffen."""

    wifi: bool = Field(
        description=(
            "Träffens Wi-Fi är inlagt och skärmen står på träffens nät: QR-koden ritas på "
            "/api/deltagare/wifi.svg (S8)."
        )
    )
    link: Text = Field(description="Länken till träffen, för QR-koden 2 · Träffen.")


class ClockMotion(Contract):
    """Hur visarna går, ur klockpaketets clock.json."""

    hour: Literal["smooth", "minute"] = "smooth"
    minute: Literal["smooth", "jump"] = "smooth"
    minute_bounce: bool = False
    second: Literal["smooth", "tick", "sweep"] = "smooth"
    sweep_seconds: float = Field(default=60, ge=30, le=60)


class ClockFaceShow(Contract):
    """Vad den analoga klockskärmen ritar (H74, H75). analog är den inbyggda tavlan.
    custom:<id> är träffens klockpaket. Lagren hämtas på /api/screen/clock/{id}/{lager}."""

    style: str = Field(description="analog eller custom:<urtavlans id>.")
    id: Id | None = None
    name: Text | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    motion: ClockMotion | None = None
    layers: list[str] = Field(default_factory=list)
    dark: list[str] = Field(default_factory=list)


class ScreenPicture(Contract):
    """What the screen shows now. Without a view it waits, and says its name."""

    name: Text
    view: ScreenView | None = None
    meet: Text
    traffic_day: Weekday
    clock: Clock
    now: Now | None = Field(
        default=None,
        description="Träffen som den går, för vyerna som ritar banan (SKARM-09). Inte för klockan.",
    )
    package: Text | None = Field(
        default=None,
        description=(
            "Vilket paket vyn ritar på: byts när versionen eller driftändringarna ändras. "
            "Paketet hämtas på /api/screen/package."
        ),
    )
    share: ScreenShare | None = Field(
        default=None, description="QR-koderna, för klockans två vyer (SKARM-18)."
    )
