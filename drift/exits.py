"""Stationens utfarter mot träffens sträckor (H26, PLAN-31, TRAFIK-05).

A station's exits have a fixed id and a side in its outside. Which section each exit leads to is
kept per meet. When a TKL connects, Hubben guesses: an exit named after the neighbour, the one
exit on the section's side, or the exit the station gave last meet for the same neighbour. When
it is not sure it asks, and the station in TKL or the dispatcher in Klienter answers; the first
answer stands. A station coupled in advance in Planering brings its own table, which is used as
it is.

The answers are remembered across meets in a small file of the hub's (ExitMemory), keyed by the
station and the neighbour's name, so that the next meet with the same neighbour need not ask.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from threading import Lock

from contracts import station
from contracts.station_outside import Exit, StationOutside


def neighbour_key(name: str) -> str:
    return " ".join(name.casefold().split())


def _mentions(exit_: Exit, names: Sequence[str]) -> bool:
    """The exit's name or id names the neighbour: Mot Västby, Västby or Vby."""
    said = " ".join(filter(None, (exit_.name, exit_.id))).casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", said) for name in names if name
    )


def couple(
    outside: StationOutside,
    place: str,
    sections: Sequence[station.SectionHere],
    neighbours: Mapping[str, station.Neighbour],
    *,
    pinned: Mapping[str, str] | None = None,
    answered: Mapping[str, str] | None = None,
    remembered: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], list[station.ExitQuestion]]:
    """The exit of each section at the place, and the questions for those Hubben is not sure
    of. pinned: the table from Planering; answered: this meet's answers, by section;
    remembered: earlier meets' answers, by the neighbour's key."""
    exits = {e.id: e for e in outside.exits}
    found: dict[str, str] = {}
    guessed: dict[str, str] = {}
    unsure: list[tuple[station.SectionHere, list[Exit]]] = []
    for here in sections:
        given = (pinned or {}).get(here.section) or (answered or {}).get(here.section)
        if given in exits:
            found[here.section] = given
            continue
        other = neighbours.get(here.other_place)
        names = [other.name, other.code] if other else [here.other_code]
        candidates = list(outside.exits)
        if here.side is not None:
            candidates = [e for e in candidates if e.side == here.side] or candidates
        named = [e for e in candidates if _mentions(e, names)]
        if len(named) == 1:
            guessed[here.section] = named[0].id
            continue
        candidates = named or candidates
        memory = (remembered or {}).get(neighbour_key(other.name if other else here.other_code))
        if memory in {e.id for e in candidates}:
            guessed[here.section] = str(memory)
            continue
        if len(candidates) == 1 and (here.side is not None or len(exits) == 1):
            guessed[here.section] = candidates[0].id
            continue
        unsure.append((here, candidates))
    # Two sections guessed onto the same exit: neither guess is sure.
    taken = list(found.values()) + list(guessed.values())
    for section, exit_id in guessed.items():
        if taken.count(exit_id) == 1:
            found[section] = exit_id
        else:
            here = next(s for s in sections if s.section == section)
            same_side = [e for e in outside.exits if here.side is None or e.side == here.side]
            unsure.append((here, same_side or list(outside.exits)))
    questions = []
    for here, candidates in unsure:
        other = neighbours.get(here.other_place)
        questions.append(
            station.ExitQuestion(
                station_id=outside.station_id,
                place=place,
                section=here.section,
                other_place=here.other_place,
                other_name=other.name if other else here.other_code,
                side=here.side,
                alternatives=[
                    station.ExitChoice(exit=e.id, side=e.side, name=e.name) for e in candidates
                ],
            )
        )
    return found, questions


class ExitMemory:
    """Earlier meets' answers, so that Hubben can guess from them (H26). One small file per
    hub, shared by its meets."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._ready = False

    def _db(self) -> sqlite3.Connection:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS exit_answer (station_id TEXT NOT NULL, "
                    "neighbour TEXT NOT NULL, exit TEXT NOT NULL, "
                    "PRIMARY KEY (station_id, neighbour))"
                )
            self._ready = True
        return sqlite3.connect(self.path)

    def remembered(self, station_id: str) -> dict[str, str]:
        with self._lock, closing(self._db()) as db:
            rows = db.execute(
                "SELECT neighbour, exit FROM exit_answer WHERE station_id=?", (station_id,)
            ).fetchall()
        return {str(neighbour): str(exit_) for neighbour, exit_ in rows}

    def remember(self, station_id: str, neighbour: str, exit_id: str) -> None:
        with self._lock, closing(self._db()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO exit_answer VALUES (?, ?, ?)",
                (station_id, neighbour_key(neighbour), exit_id),
            )
