"""What the keys look like: the prototype's colours, symbols and words (SD3, SD6).

The colours are locked and the same on every station (SD3): a train route is green, a shunting
route yellow, a chosen start blue (train) or yellow (shunting), a goal dark green with a green
frame, a refusal red for three seconds with the reason, and a hindered route dimmed with a red
dot and the reason (SD17, SD18). Words and simple shapes, no emoji (SD6). They are the ones of
the prototype in the specification (src/streamdeck.js), and of its pictures for what the
prototype does not draw: the modes, Platser and Spårplan.
"""

from __future__ import annotations

import re
from typing import Final

from contracts.tkl import TklDeckFace

EMPTY: Final = TklDeckFace()
GREEN: Final = "#15803d"
GREEN_BAND: Final = "#bbf7d0"
YELLOW: Final = "#a16207"
YELLOW_BAND: Final = "#fde68a"
RED: Final = "#b91c1c"
DOT: Final = "#ff5a4d"
BLUE: Final = "#2563eb"
LIGHT_BLUE: Final = "#60a5fa"
GOAL_BG: Final = "#14532d"
GOAL_FG: Final = "#bbf7d0"
GOAL_FRAME: Final = "#22c55e"
CLOCK_BG: Final = "#0b1220"
CLOCK_FG: Final = "#93c5fd"
TAB_BG: Final = "#111827"
TAB_FG: Final = "#9ca3af"
TAB_ON: Final = "#334155"
PLACE_BG: Final = "#000000"
PLACE_FG: Final = "#f3f4f6"
BAR_FREE: Final = "#8a939c"
BAR_TRAIN: Final = "#22c55e"
BAR_SHUNT: Final = "#eab308"
BAR_OCCUPIED: Final = "#ef4444"
CHOSEN_BG: Final = "#172a46"
DIM_FG: Final = "#4b5563"
TRACK_FG: Final = "#e6e9ec"


def clock(time: str, station: str) -> TklDeckFace:
    """Larm och klocka at rest: the game clock from Hubben, else the computer's (SD15)."""
    return TklDeckFace(
        type="clock", text=time, under=station, bg=CLOCK_BG, fg=CLOCK_FG, label=f"Klockan {time}"
    )


def no_contact() -> TklDeckFace:
    """Ingen kontakt: never an old state, and silence never means free (SD21)."""
    return TklDeckFace(
        type="contact",
        text="Ingen",
        under="kontakt",
        bg="#16191c",
        fg="#8b95a1",
        dim=True,
        label="Ingen kontakt",
    )


def refused(text: str, reason: str) -> TklDeckFace:
    """The interlocking's no, on the key for three seconds (SD18)."""
    return TklDeckFace(
        type="answer",
        text=text or "Nej",
        under=reason,
        bg=RED,
        fg="#ffffff",
        label=f"Nej: {reason}",
    )


SHORT: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"belagd av (tåg \w+)", re.IGNORECASE), r"belagt · \1"),
    (re.compile(r"är belagd", re.IGNORECASE), "belagt"),
    (re.compile(r"Växel (\S+) är låst", re.IGNORECASE), r"vx \1 låst"),
    (re.compile(r"Växel (\S+) kan inte läggas om", re.IGNORECASE), r"vx \1 under tåg"),
    (re.compile(r"är låst i vägen", re.IGNORECASE), "väg ligger över"),
    (re.compile(r"visar redan kör|ska visa stopp|visar kör", re.IGNORECASE), "väg ligger över"),
    (re.compile(r"signalstopp", re.IGNORECASE), "signalstopp"),
    (re.compile(r"ur drift", re.IGNORECASE), "ur drift"),
    (re.compile(r"lokalt frigivet", re.IGNORECASE), "lokal frigivning"),
    (re.compile(r"Vändskivan", re.IGNORECASE), "skivan står fel"),
    (re.compile(r"Ingen (tåg|växlings)?väg", re.IGNORECASE), "ingen väg"),
    (re.compile(r"okänd beläggning", re.IGNORECASE), "okänt läge"),
    (re.compile(r"står i stopp", re.IGNORECASE), "i stopp"),
    (re.compile(r"ligger redan", re.IGNORECASE), "ligger redan"),
    (re.compile(r"Väntar på återrapport", re.IGNORECASE), "väntar på vx"),
)


def short(reason: str | None) -> str:
    """The interlocking's own reason, short enough for a key (SD18). The whole reason stands in
    the deck's message and on the info line or the strip."""
    if not reason:
        return "nej"
    for pattern, said in SHORT:
        found = pattern.search(reason)
        if found is not None:
            return found.expand(said)[:30]
    words = reason.rstrip(".").split()
    return " ".join(words[:3])[:30]


def tab(text: str, under: str, active: bool) -> TklDeckFace:
    return TklDeckFace(
        type="page",
        text=text,
        under=under,
        bg=TAB_ON if active else TAB_BG,
        fg="#ffffff" if active else TAB_FG,
        line="#f8fafc" if active else None,
        label=f"Sida {text}",
    )
