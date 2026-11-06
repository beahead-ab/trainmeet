"""Trafikkontrollen: what the draft would carry as findings if it were published (spec 4.1).

A finding never stops publishing; structural errors already cannot get into a package. The
check looks for:
- a train between two places that clear (not halts) with no section between them: Drift
  cannot clear that part of its way (observation, grouped per pair of places);
- two trains on the same track of a place at the same time on the same day (conflict);
- questions without an answer, and facts that are unsure (observation).
"""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from typing import Final

from contracts.common import Weekday
from contracts.meet import Call, Finding, MeetPackage, PlaceKind, Severity, Train
from contracts.planning import Certainty, Draft

DAY: Final = 24 * 60
WEEKDAYS: Final = list(Weekday)
SHOWN: Final = 6


def check(draft: Draft) -> list[Finding]:
    package = draft.package
    if package is None:
        return []
    findings = [*_without_section(package), *_track_conflicts(package)]
    unanswered = [q for q in draft.questions if q.answer is None]
    unsure = [f for f in draft.facts if f.certainty == Certainty.UNSURE]
    if unanswered:
        findings.append(
            Finding(
                id="questions",
                severity=Severity.OBSERVATION,
                code="unanswered_questions",
                message=_count(len(unanswered), "fråga", "frågor")
                + " från importen är obesvarade.",
                refs=[],
            )
        )
    if unsure:
        findings.append(
            Finding(
                id="unsure",
                severity=Severity.OBSERVATION,
                code="unsure_facts",
                message=_count(len(unsure), "uppgift", "uppgifter")
                + " är osäkra, inte bekräftade.",
                refs=[],
            )
        )
    return findings


def _count(number: int, one: str, many: str) -> str:
    return f"1 {one}" if number == 1 else f"{number} {many}"


def _numbers(trains: list[Train]) -> str:
    numbers = list(dict.fromkeys(train.number for train in trains))
    shown = ", ".join(numbers[:SHOWN])
    return shown + (f" och {len(numbers) - SHOWN} till" if len(numbers) > SHOWN else "")


def _without_section(package: MeetPackage) -> list[Finding]:
    names = {place.id: place.name for place in package.places}
    stops = {place.id for place in package.places if place.kind != PlaceKind.HALT}
    sections = {frozenset((s.place_a, s.place_b)) for s in package.sections}
    missing: dict[tuple[str, str], list[Train]] = defaultdict(list)
    for train in package.trains:
        route = [call.place for call in train.calls if call.place in stops]
        for a, b in pairwise(route):
            if a != b and frozenset((a, b)) not in sections:
                key = (a, b) if a < b else (b, a)
                if train not in missing[key]:
                    missing[key].append(train)
    return [
        Finding(
            id=f"no-section-{a}-{b}",
            severity=Severity.OBSERVATION,
            code="no_section",
            message=(
                f"{_count(len(trains), 'tåg går', 'tåg går')} {names[a]}–{names[b]} utan "
                f"klareringssträcka, så Drift klarerar inte den biten: {_numbers(trains)}."
            ),
            refs=[a, b, *(train.id for train in trains)],
        )
        for (a, b), trains in sorted(
            missing.items(), key=lambda item: (names[item[0][0]], names[item[0][1]])
        )
    ]


def _span(call: Call) -> tuple[int, int] | None:
    """The minutes from the train's first day that the call holds its track."""
    times = [t for t in (call.arrival, call.departure) if t is not None]
    if not times:
        return None
    minutes = [int(t[:2]) * 60 + int(t[3:]) + call.day_offset * DAY for t in times]
    if len(minutes) == 2 and minutes[1] < minutes[0]:
        minutes[1] += DAY  # the departure is after midnight
    return minutes[0], minutes[-1]


def _track_conflicts(package: MeetPackage) -> list[Finding]:
    """Two trains on one track at once. Each call is placed in the week, per traffic day."""
    held: dict[tuple[str, str], list[tuple[int, int, Train, Call]]] = defaultdict(list)
    for train in package.trains:
        for call in train.calls:
            span = _span(call)
            if call.track is None or span is None:
                continue
            for day in train.days:
                start = WEEKDAYS.index(day) * DAY
                held[(call.place, call.track)].append(
                    (start + span[0], start + span[1], train, call)
                )
    names = {place.id: place.name for place in package.places}
    found: dict[tuple[str, str, str, str], list[str]] = {}
    for (place, track), spans in held.items():
        spans.sort(key=lambda item: (item[0], item[1]))
        for index, (_start, end, train, call) in enumerate(spans):
            for other_start, _other_end, other, other_call in spans[index + 1 :]:
                if other_start > end:
                    break
                # Two passages in the same minute are not counted: the plan gives a passage
                # the main track whichever way it runs.
                if other.id == train.id or not other_start < end:
                    continue
                low, high = sorted((call.id, other_call.id))
                key = (place, track, low, high)
                found.setdefault(key, [train.number, other.number, _clock(other_start)])
    return [
        Finding(
            id=f"track-{a}-{b}",
            severity=Severity.CONFLICT,
            code="track_conflict",
            message=(
                f"Tåg {first} och {second} står på spår {track} i {names[place]} samtidigt ({at})."
            ),
            refs=[place, a, b],
        )
        for (place, track, a, b), (first, second, at) in sorted(found.items())
    ]


def _clock(minutes: int) -> str:
    minute = minutes % DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"
