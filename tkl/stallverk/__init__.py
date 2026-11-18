"""Ställverket at level 1–2 (#84): the interlocking, one state machine for every station.

Pure Python without I/O, using only the contracts and the engine (tkl/standard). From a station
model, plant.Plant derives what the interlocking needs and never stores: the sections it locks
and releases, the ways with where a train stands to take them, the levers and the exits. The
Interlocking holds the state of the moment over it and checks every operation (STV-43).

No code here names a station (RS13).
"""

from tkl.stallverk.interlocking import Interlocking, Outcome, UnknownStart, load
from tkl.stallverk.plant import Plant, Section, Way, fingerprint, plant_of

__all__ = [
    "Interlocking",
    "Outcome",
    "Plant",
    "Section",
    "UnknownStart",
    "Way",
    "fingerprint",
    "load",
    "plant_of",
]
