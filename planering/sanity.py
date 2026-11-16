"""Rimlighetskontrollen (PLAN-36): the whole timetable compared with itself.

The plan has no distances, speeds or shortest running times. So each train is compared with
the other trains between the same places and at the same place: if nearly all take 15 minutes
between two places and one takes two hours, it is worth a look. What is found is advice to the
planner, never an error that stops publishing, and it does not go with the version.

Ported from the old Cloud (cloud/timetable_core/sanity.py and docs/traffic-review.md there).
The planner corrects a deviation in the grid, or lets it stand; Låt stå comes back by itself
when the calls it is about change, and can be taken back.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import Final, Literal

from contracts.meet import Call, MeetPackage, Train
from contracts.planning import Deviation

#: The fewest OTHER trains between the same places, or at the same place, before anything is
#: compared. With fewer there is no usual time to deviate from.
MIN_OTHER_TRAINS: Final = 3
#: Unusually long running time: at least 2.5 times the others' median ...
SLOW_FACTOR: Final = 2.5
#: ... and at least 20 minutes more, so that 5 minutes against 2 does not count.
SLOW_MARGIN: Final = 20
#: Unusually short running time: at most a third of the median ...
FAST_DIVISOR: Final = 3
#: ... and at least 5 minutes shorter, so that 1 minute against 3 does not count.
FAST_MARGIN: Final = 5
#: Unusually long stop: at least five times the median ...
DWELL_FACTOR: Final = 5
#: ... and at least 45 minutes longer than it ...
DWELL_MARGIN: Final = 45
#: ... and never under half an hour.
DWELL_MINIMUM: Final = 30
#: Without three other trains to compare with, only stops of three hours or more are marked. A
#: train that stands that long in the middle of its way is seldom meant to.
DWELL_FALLBACK: Final = 180
#: A time that goes back more than half a day is midnight, not an error: 23:50 to 00:05 is 15
#: minutes. Less than that back is an error.
MIDNIGHT_WRAP: Final = 720

Kind = Literal["slow_leg", "fast_leg", "backwards_leg", "backwards_dwell", "long_dwell"]
TITLES: Final[dict[Kind, str]] = {
    "slow_leg": "Ovanligt lång gångtid",
    "fast_leg": "Ovanligt kort gångtid",
    "backwards_leg": "Tåget är framme innan det har gått",
    "backwards_dwell": "Avgång före ankomst",
    "long_dwell": "Ovanligt långt uppehåll",
}
KINDS: Final = tuple(TITLES)


@dataclass(frozen=True)
class _Stop:
    index: int
    call: Call
    arrival: int | None
    departure: int | None

    @property
    def start(self) -> int | None:
        """Where a leg starts: the departure, or the only time the stop has."""
        return self.departure if self.departure is not None else self.arrival

    @property
    def end(self) -> int | None:
        return self.arrival if self.arrival is not None else self.departure


@dataclass
class _Found:
    kind: Kind
    stops: tuple[int, ...]
    minutes: int
    usual: float | None
    samples: int


Typical = Callable[[str, tuple[str, ...]], tuple[float | None, int]]


def duration(minutes: float) -> str:
    """15 min, 2 h, 2 h 5 min: without a sign, half minutes up."""
    hours, rest = divmod(_whole(abs(minutes)), 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def _whole(value: float) -> int:
    """Whole minutes, halves up: the median of 14 and 15 is 15."""
    return int(value + 0.5)


def _clock_minutes(text: str | None) -> int | None:
    return None if text is None else int(text[:2]) * 60 + int(text[3:])


def _clock(minutes: int) -> str:
    minute = minutes % 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _wrap(minutes: int) -> int:
    return minutes + 1440 if minutes < -MIDNIGHT_WRAP else minutes


def _stops(train: Train) -> list[_Stop]:
    return [
        _Stop(i, c, _clock_minutes(c.arrival), _clock_minutes(c.departure))
        for i, c in enumerate(train.calls)
    ]


def _legs(stops: list[_Stop]) -> tuple[list[tuple[int, int]], set[int]]:
    """Legs between calls that follow each other at different places, and the calls in the
    middle of the way (neither the first nor the last with a time)."""
    legs = [
        (a.index, b.index)
        for a, b in pairwise(stops)
        if a.call.place != b.call.place and a.start is not None and b.end is not None
    ]
    timed = [s for s in stops if s.start is not None]
    return legs, {s.index for s in timed[1:-1]}


def _leg_minutes(stops: list[_Stop], i: int, j: int) -> int:
    end, start = stops[j].end, stops[i].start
    assert end is not None and start is not None
    return _wrap(end - start)


def _pair(stops: list[_Stop], i: int, j: int) -> tuple[str, ...]:
    return tuple(sorted((stops[i].call.place, stops[j].call.place)))


def _dwell(stop: _Stop) -> int | None:
    """The stop in minutes, or None for passages and calls without both times."""
    if stop.arrival is None or stop.departure is None or not stop.call.stops:
        return None
    return _wrap(stop.departure - stop.arrival)


def _samples(package: MeetPackage) -> dict[str, dict[tuple[str, ...], dict[str, list[int]]]]:
    """Each train's running times per pair of places, and stops per place."""
    tables: dict[str, dict[tuple[str, ...], dict[str, list[int]]]] = {
        "leg": defaultdict(lambda: defaultdict(list)),
        "dwell": defaultdict(lambda: defaultdict(list)),
    }
    for train in package.trains:
        stops = _stops(train)
        legs, inner = _legs(stops)
        for i, j in legs:
            minutes = _leg_minutes(stops, i, j)
            if minutes >= 0:
                tables["leg"][_pair(stops, i, j)][train.id].append(minutes)
        for stop in stops:
            dwell = _dwell(stop)
            if dwell is not None and dwell >= 0 and stop.index in inner:
                tables["dwell"][(stop.call.place,)][train.id].append(dwell)
    return tables


def _typical(tables: dict[str, dict[tuple[str, ...], dict[str, list[int]]]], train: str) -> Typical:
    """The OTHER trains' median, one value per train: a train is never compared with itself.
    The median is None with fewer than MIN_OTHER_TRAINS trains."""
    cache: dict[tuple[str, tuple[str, ...]], tuple[float | None, int]] = {}

    def typical(kind: str, key: tuple[str, ...]) -> tuple[float | None, int]:
        if (kind, key) not in cache:
            values = [median(v) for other, v in tables[kind].get(key, {}).items() if other != train]
            usual = median(values) if len(values) >= MIN_OTHER_TRAINS else None
            cache[(kind, key)] = (usual, len(values))
        return cache[(kind, key)]

    return typical


def _check(stops: list[_Stop], typical: Typical) -> list[_Found]:
    """One train's deviations, in the order it runs."""
    legs, inner = _legs(stops)
    found: list[_Found] = []
    for i, j in legs:
        minutes = _leg_minutes(stops, i, j)
        usual, samples = typical("leg", _pair(stops, i, j))
        kind: Kind
        if minutes < 0:
            kind = "backwards_leg"
        elif (
            usual is not None and minutes >= SLOW_FACTOR * usual and minutes - usual >= SLOW_MARGIN
        ):
            kind = "slow_leg"
        elif (
            usual is not None and minutes <= usual / FAST_DIVISOR and usual - minutes >= FAST_MARGIN
        ):
            kind = "fast_leg"
        else:
            continue
        found.append(_Found(kind, (i, j), minutes, usual, samples))
    for stop in stops:
        dwell = _dwell(stop)
        if dwell is None:
            continue
        usual, samples = typical("dwell", (stop.call.place,))
        # Departure before arrival is wrong wherever it stands. A long stop only counts in the
        # middle of the way: a train may stand for hours where it starts or ends.
        if dwell < 0:
            kind = "backwards_dwell"
        elif stop.index not in inner:
            continue
        elif (
            usual is not None
            and dwell >= max(DWELL_FACTOR * usual, usual + DWELL_MARGIN)
            and dwell >= DWELL_MINIMUM
        ) or (usual is None and dwell >= DWELL_FALLBACK):
            kind = "long_dwell"
        else:
            continue
        found.append(_Found(kind, (stop.index,), dwell, usual, samples))
    found.sort(key=lambda f: (f.stops[-1], len(f.stops) == 1, KINDS.index(f.kind)))
    return found


def _text(train: Train, item: _Found, stops: list[_Stop], names: dict[str, str]) -> str:
    number = train.number
    others = (
        f" Andra tåg tar {duration(item.usual)} (median av {item.samples} tåg)."
        if item.usual is not None
        else ""
    )
    if len(item.stops) == 2:
        a, b = (stops[i] for i in item.stops)
        assert a.start is not None and b.end is not None
        if item.kind == "backwards_leg":
            return (
                f"Tåg {number} är framme i {names[b.call.place]} {_clock(b.end)} men lämnar "
                f"{names[a.call.place]} först {_clock(a.start)}.{others}"
            )
        return (
            f"Tåg {number} tar {duration(item.minutes)} mellan {names[a.call.place]} och "
            f"{names[b.call.place]}.{others}"
        )
    stop = stops[item.stops[0]]
    assert stop.arrival is not None and stop.departure is not None
    name = names[stop.call.place]
    if item.kind == "backwards_dwell":
        return (
            f"Tåg {number} avgår från {name} {_clock(stop.departure)}, "
            f"{duration(item.minutes)} före ankomsten {_clock(stop.arrival)}."
        )
    text = (
        f"Tåg {number} står {duration(item.minutes)} i {name} (ankomst {_clock(stop.arrival)}, "
        f"avgång {_clock(stop.departure)})."
    )
    if item.usual is not None:
        return f"{text} Andra tåg står {duration(item.usual)} (median av {item.samples} tåg)."
    return (
        f"{text} För få andra tåg stannar här för en jämförelse; uppehåll på "
        f"{duration(DWELL_FALLBACK)} eller mer markeras ändå."
    )


def fingerprint(train: Train, calls: list[Call]) -> str:
    """What the deviation is about: a decision on it holds until these change."""
    rows = [
        [train.number, sorted(train.days), c.id, c.place, c.arrival, c.departure, c.stops]
        for c in sorted(calls, key=lambda c: c.id)
    ]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def _id(text: str) -> str:
    if len(text) <= 80:
        return text
    return f"{text.split(':')[0]}:{hashlib.sha256(text.encode()).hexdigest()[:24]}"


def deviations(package: MeetPackage, let_stand: dict[str, str] | None = None) -> list[Deviation]:
    """Every deviation in the draft, train by train. One the planner let stand is marked, as
    long as the calls it is about are the same."""
    let_stand = let_stand or {}
    names = {p.id: p.name for p in package.places}
    tables = _samples(package)
    out: list[Deviation] = []
    for train in package.trains:
        stops = _stops(train)
        seen: dict[str, int] = defaultdict(int)
        for item in _check(stops, _typical(tables, train.id)):
            # The id says what and where, never when: a decision on it is not lost because a
            # time is corrected elsewhere in the train.
            where = ".".join(stops[i].call.place for i in item.stops)
            identity = _id(f"{item.kind}:{train.id}:{where}")
            seen[identity] += 1
            if seen[identity] > 1:
                identity = _id(f"{identity}-{seen[identity]}")
            # The call where it is first, so that Visa i rutnätet lands there.
            calls = [stops[i].call for i in reversed(item.stops)]
            print_ = fingerprint(train, calls)
            out.append(
                Deviation(
                    id=identity,
                    kind=item.kind,
                    title=TITLES[item.kind],
                    message=_text(train, item, stops, names),
                    train=train.id,
                    train_number=train.number,
                    calls=[c.id for c in calls],
                    days=train.days,
                    minutes=item.minutes,
                    usual=None if item.usual is None else _whole(item.usual),
                    samples=item.samples,
                    fingerprint=print_,
                    let_stand=let_stand.get(identity) == print_,
                )
            )
    return out
