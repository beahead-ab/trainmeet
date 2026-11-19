"""The driftplatser TKL runs in Hubben: the station's, and its parts' (#87 del b, TRAFIK-35).

A station whose owner made parts their own driftplatser (TKL101) asks Hubben for one place per
part besides the station's, and Trafikledningen approves or refuses each on its own. Hubben
says, for every place TKL asked for, its answer and which part of the station it is: the part's
id in the station's outside, the link the plan keeps as `part_of` and `station.part` (PLAN-34).
So the station's place is the one that is no part, and a part's place is found by the part's id.

A hub from before the parts says nothing per place: then the first approved place is the
station's, as it always was, and a part's place is the one the model names, if TKL is approved
for it.

Following after the approval: a part approved later comes with the same key, so TKL keeps
asking how the approval stands after it has its key, more seldom when nothing waits.

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from typing import Final

from contracts import station
from contracts.tkl import TklPartPlace
from tkl.store import Connection

FOLLOW_WAITING: Final = 3.0
"""Seconds between two questions to the hub while a place waits for its answer: as often as the
web app asked while TKL waited before (#84)."""
FOLLOW_SETTLED: Final = 30.0
"""Seconds between two questions once every place has its answer: a part may be approved or
refused later, and the key may be revoked."""


def _is_part(place: station.ClientPlace) -> bool:
    return place.part is not None or place.part_of is not None


def home_place(made: Connection) -> str | None:
    """The station's own place, when TKL is approved for it."""
    if not made.wanted:
        return made.places[0] if made.places else None
    parts = {w.place for w in made.wanted if _is_part(w)}
    return next((p for p in made.places if p not in parts), None)


def part_places(made: Connection) -> list[TklPartPlace]:
    """Each part's place with the dispatcher's answer for it, as Hubben said it."""
    return [
        TklPartPlace(part=w.part, place=w.place, status=w.status)
        for w in made.wanted
        if w.part is not None
    ]


def part_place(made: Connection, part: str, named: str | None = None) -> str | None:
    """The approved place of a part: found by its link, else the one the model names."""
    found = next((w.place for w in made.wanted if w.part == part), None)
    if found is None and not made.wanted:
        found = named
    return found if found is not None and found in made.places else None


def places_of(made: Connection) -> list[str]:
    """Every approved place, the station's first."""
    home = home_place(made)
    return ([home] if home else []) + [p for p in made.places if p != home]


def next_question(made: Connection) -> float:
    """How long TKL waits between two questions to the hub about the approval."""
    waiting = made.status == station.ApprovalStatus.WAITING or any(
        w.status == station.ApprovalStatus.WAITING for w in made.wanted
    )
    return FOLLOW_WAITING if waiting else FOLLOW_SETTLED


__all__ = [
    "FOLLOW_SETTLED",
    "FOLLOW_WAITING",
    "home_place",
    "next_question",
    "part_place",
    "part_places",
    "places_of",
]
