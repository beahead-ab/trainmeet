"""Trafikkontrollen: what the draft would carry as findings if it were published (spec 4.1,
PLAN-35). It follows the conflict check of the old Cloud (docs/traffic-review.md and
timetable_core/findings.py there). Times are half open: a train that leaves a section at 10:12
and one that enters it at 10:12 do not meet. The check follows the traffic days, so a train
that runs only on Saturdays never meets one that runs Monday to Friday, and Sunday evening
runs on into Monday morning.

- Struktur: the meet's dates, its places, its trains and a line that hangs together. These
  stop publishing; everything else is shown and goes with the version.
- A, conflict: two trains in opposite directions on the same single-track section at once.
- B, conflict: two trains on the same track of a place at once; a passage takes a minute.
- C, observation: trains that follow closely on the same section.
- D, observation: what cannot be checked: a call without a time, or trains between two places
  that clear with no section between them (Drift cannot clear that part of the way). A part of
  a station and the station itself are the exception: the way between them is the station's own
  interlocking, never a clearance (TKL97, PLAN-34).
- A part of a station that is its own driftplats, with no train leaving it in the plan
  (observation): its trains may stand on the station in the source. Hubben says so and moves
  nothing; there is no rule for which of the station's trains are the part's.
- Questions without an answer, and facts that are unsure (observation).

A single-track section with at least two A conflicts gives the double-track question; a No
is kept with a fingerprint of the trains on it, and the question comes back only when they
change.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

from contracts.common import Weekday
from contracts.meet import (
    Call,
    Finding,
    MeetPackage,
    PlaceKind,
    Section,
    Severity,
    TrackKind,
    Train,
)
from contracts.planning import Certainty, DoubleTrackQuestion, Draft
from core.changes import times

DAY: Final = 24 * 60
WEEK: Final = 7 * DAY
WEEKDAYS: Final = list(Weekday)
DAY_NAMES: Final = ("Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön")
SHOWN: Final = 6
PASSAGE: Final = 1  # A passage holds its track a minute (B).
QUESTION_AT: Final = 2  # A conflicts on one single-track section that ask if it is double.


@dataclass
class Review:
    """The whole check: findings that go with the version, structural errors that stop it, and
    the double-track questions."""

    findings: list[Finding] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    double_track: list[DoubleTrackQuestion] = field(default_factory=list)


def check(draft: Draft) -> list[Finding]:
    """The findings a published version carries."""
    return review(draft).findings


def review(draft: Draft) -> Review:
    package = draft.package
    if package is None:
        return Review(blocking=["Lägg till underlag först."])
    lines = _line_conflicts(package)
    findings = [
        *_missing_times(package),
        *lines.findings,
        *_track_conflicts(package),
        *_without_section(package),
        *_unused(package),
        *_parts_without_trains(package),
    ]
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
    return Review(
        findings=findings,
        blocking=structure(draft),
        double_track=_questions(package, lines, draft.double_track_declined),
    )


# --- Struktur: stops publishing -----------------------------------------------------------------


def structure(draft: Draft) -> list[str]:
    """The structural errors (Struktur in PLAN-35). References are already kept right by the
    package's own validation; what is left is the meet's dates, enough of a line, and one
    that hangs together."""
    package = draft.package
    if package is None:
        return ["Lägg till underlag först."]
    errors = []
    if draft.meet.first_date is None or draft.meet.last_date is None:
        errors.append("Träffen saknar första eller sista dag. Ange dem under Träffar.")
    if len(package.places) < 2:
        errors.append("Minst två driftplatser krävs.")
    if not package.trains:
        errors.append("Tidtabellen saknar tåg.")
    if not _connected(package):
        errors.append(
            "Banan hänger inte ihop: några driftplatser nås varken via sträckorna eller av tågen "
            "från de andra."
        )
    return errors


def _links(package: MeetPackage) -> dict[str, set[str]]:
    """Which places lie next to each other: through the sections and their parts, or the way
    a train runs (an industry or a halt may lie off every clearance section)."""
    linked: dict[str, set[str]] = defaultdict(set)
    hops = [
        hop
        for section in package.sections
        for hop in (
            [(p.from_place, p.to_place) for p in section.parts]
            or [(section.place_a, section.place_b)]
        )
    ]
    hops += [(a.place, b.place) for train in package.trains for a, b in pairwise(train.calls)]
    # A part of a station lies at the station, whether or not a train runs between them.
    hops += [(p.id, p.part_of) for p in package.places if p.part_of is not None]
    for a, b in hops:
        linked[a].add(b)
        linked[b].add(a)
    return linked


def _connected(package: MeetPackage) -> bool:
    """Every place in use is reached from every other."""
    linked = _links(package)
    used = [p.id for p in package.places if linked[p.id]]
    if len(used) < 2:
        return True
    reached = {used[0]}
    queue = [used[0]]
    while queue:
        for other in linked[queue.pop()] - reached:
            reached.add(other)
            queue.append(other)
    return reached >= set(used)


def _unused(package: MeetPackage) -> list[Finding]:
    """D: places that no section and no train uses are not checked."""
    linked = _links(package)
    loose = [p for p in package.places if not linked[p.id]]
    if not loose or len(loose) == len(package.places):
        return []
    names = ", ".join(p.name for p in loose[:SHOWN])
    more = f" och {len(loose) - SHOWN} till" if len(loose) > SHOWN else ""
    return [
        Finding(
            id="unused-places",
            severity=Severity.OBSERVATION,
            code="unused_places",
            message=(
                f"{_count(len(loose), 'driftplats', 'driftplatser')} används varken av en "
                f"sträcka eller av något tåg: {names}{more}."
            ),
            refs=[p.id for p in loose],
        )
    ]


def _parts_without_trains(package: MeetPackage) -> list[Finding]:
    """A part of a station that is its own driftplats, and no train leaves it in the plan
    (PLAN-34, TKL108). The source may have its trains on the station: said, never guessed."""
    names = {place.id: place.name for place in package.places}
    leaving = {
        call.place
        for train in package.trains
        for index, call in enumerate(train.calls)
        if index < len(train.calls) - 1
    }
    return [
        Finding(
            id=_id("part-without-trains", place.id),
            severity=Severity.OBSERVATION,
            code="part_without_trains",
            message=(
                f"Inget tåg avgår från {place.name} i planen. {place.name} är en del av "
                f"{names.get(place.part_of, place.part_of)} och egen driftplats. Står delens tåg "
                f"på {names.get(place.part_of, place.part_of)} i underlaget, flytta dem dit i "
                "planeringsprogrammet; Hubben flyttar inga tåg själv."
            ),
            refs=[place.id, place.part_of],
        )
        for place in package.places
        if place.part_of is not None and place.id not in leaving
    ]


def _missing_times(package: MeetPackage) -> list[Finding]:
    """D: a call with no time at all cannot be checked."""
    names = {place.id: place.name for place in package.places}
    return [
        Finding(
            id=_id("time", call.id),
            severity=Severity.OBSERVATION,
            code="missing_time",
            message=f"Tåg {train.number}: tid saknas vid {names.get(call.place, call.place)}.",
            refs=[call.place, train.id, call.id],
        )
        for train in package.trains
        for call in train.calls
        if call.arrival is None and call.departure is None
    ]


# --- A and C: on the line -----------------------------------------------------------------------


@dataclass
class _Run:
    """A train on a section on one day, in minutes from Monday 00:00."""

    start: float
    end: float
    train: Train
    source: str
    target: str
    calls: tuple[str, str]


@dataclass
class _Found:
    """One finding per rule, place and pair of trains; the days it happens on are gathered."""

    rule: str
    subject: str
    trains: tuple[Train, Train]
    day: int
    start: float
    end: float
    text: str
    refs: list[str]
    days: set[int] = field(default_factory=set)


@dataclass
class _Lines:
    findings: list[Finding]
    a_conflicts: dict[str, int]
    calls: dict[str, set[tuple[str, str]]]


def _timeline(train: Train) -> list[tuple[Call, float, float]]:
    """The train's calls with times, in minutes from its first day. A time that goes back is
    the next day, as in the old Cloud."""
    out: list[tuple[Call, float, float]] = []
    previous: float | None = None
    for call in train.calls:
        arrival, departure = times(call)
        first = arrival if arrival is not None else departure
        if first is None:
            continue
        last = departure if departure is not None else first
        start, end = first / 60, last / 60
        while previous is not None and start < previous:
            start, end = start + DAY, end + DAY
        previous = end
        out.append((call, start, end))
    return out


def _unique_path(
    graph: dict[str, list[tuple[str, Section]]], source: str, target: str
) -> list[tuple[str, str, Section]] | None:
    """One shortest way through the sections, or None if there is none or more than one."""
    queue: deque[tuple[str, list[tuple[str, str, Section]]]] = deque([(source, [])])
    distance = {source: 0}
    found: list[list[tuple[str, str, Section]]] = []
    while queue:
        node, path = queue.popleft()
        if found and len(path) >= len(found[0]):
            continue
        for neighbour, section in graph[node]:
            longer = [*path, (node, neighbour, section)]
            if neighbour == target:
                found.append(longer)
                if len(found) > 1:
                    return None
            elif len(longer) <= distance.get(neighbour, len(longer)):
                distance[neighbour] = len(longer)
                queue.append((neighbour, longer))
    return found[0] if found else None


def _overlaps(runs: list[_Run]) -> Iterator[tuple[_Run, _Run, float, float]]:
    """Each pair of runs of different trains that share at least a minute. A copy of the week
    after lets Sunday evening meet Monday morning."""
    expanded = sorted(
        (
            _Run(r.start + shift, r.end + shift, r.train, r.source, r.target, r.calls)
            for r in runs
            for shift in (0, WEEK)
        ),
        key=lambda r: (r.start, r.end),
    )
    active: list[_Run] = []
    for current in expanded:
        active = [r for r in active if r.end - current.start >= 1]
        for prior in active:
            if prior.train.id == current.train.id:
                continue
            start, end = max(prior.start, current.start), min(prior.end, current.end)
            if end - start >= 1 and start < WEEK + DAY:
                yield prior, current, start, end
        active.append(current)


def _line_conflicts(package: MeetPackage) -> _Lines:
    names = {place.id: place.name for place in package.places}
    stops = {place.id for place in package.places if place.kind != PlaceKind.HALT}
    graph: dict[str, list[tuple[str, Section]]] = defaultdict(list)
    direct: dict[frozenset[str], Section] = {}
    for section in package.sections:
        graph[section.place_a].append((section.place_b, section))
        graph[section.place_b].append((section.place_a, section))
        direct[frozenset((section.place_a, section.place_b))] = section
    runs: dict[str, list[_Run]] = defaultdict(list)
    used: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for train in package.trains:
        timed = [t for t in _timeline(train) if t[0].place in stops]
        for (a, _a_in, a_out), (b, b_in, _b_out) in pairwise(timed):
            if a.place == b.place:
                continue
            straight = direct.get(frozenset((a.place, b.place)))
            path = (
                [(a.place, b.place, straight)]
                if straight is not None
                else _unique_path(graph, a.place, b.place)
            )
            if not path:
                continue  # no_section says so
            for index, (source, target, on) in enumerate(path):
                start = a_out + (b_in - a_out) * index / len(path)
                end = a_out + (b_in - a_out) * (index + 1) / len(path)
                used[on.id].add((train.id, a.id))
                used[on.id].add((train.id, b.id))
                for weekday in train.days:
                    shift = WEEKDAYS.index(weekday) * DAY
                    runs[on.id].append(
                        _Run(start + shift, end + shift, train, source, target, (a.id, b.id))
                    )
    sections = {s.id: s for s in package.sections}
    found: dict[str, _Found] = {}
    for section_id, section_runs in runs.items():
        section = sections[section_id]
        title = f"{names[section.place_a]}–{names[section.place_b]}"
        for first, second, start, end in _overlaps(section_runs):
            if first.source == second.source:
                ahead, behind = sorted((first, second), key=lambda r: r.start)
                gap = round(abs(second.start - first.start))
                text = (
                    f"{title}: tåg {behind.train.number} följer tåg {ahead.train.number} "
                    f"med {gap} min lucka"
                )
                rule = "C"
            elif section.tracks == TrackKind.SINGLE:
                text = (
                    f"{title} (enkelspår): tåg {first.train.number} "
                    f"({names[first.source]} → {names[first.target]}) och tåg "
                    f"{second.train.number} ({names[second.source]} → {names[second.target]}) "
                    "är på linjen samtidigt"
                )
                rule = "A"
            else:
                continue
            pair = sorted((first.train, second.train), key=lambda t: t.id)
            key = _id(rule.lower(), section_id, pair[0].id, pair[1].id)
            on_day = int(start // DAY) % 7
            item = found.get(key)
            if item is None or on_day < item.day:
                refs = [section.place_a, section.place_b, pair[0].id, pair[1].id, section_id]
                gathered: set[int] = item.days if item else set()
                item = found[key] = _Found(
                    rule, section_id, (pair[0], pair[1]), on_day, start, end, text, refs, gathered
                )
            item.days.add(on_day)
    a_conflicts: dict[str, int] = defaultdict(int)
    findings = []
    for key, item in sorted(found.items(), key=lambda kv: (kv[1].rule, kv[1].start % DAY, kv[0])):
        if item.rule == "A":
            a_conflicts[item.subject] += 1
        when = (
            f"{_clock(item.start)}–{_clock(item.end)}" if item.rule == "A" else _clock(item.start)
        )
        label = _days(item.days)
        findings.append(
            Finding(
                id=key,
                severity=Severity.CONFLICT if item.rule == "A" else Severity.OBSERVATION,
                code="single_track_conflict" if item.rule == "A" else "close_following",
                message=f"{item.text}, {when}" + (f" ({label})" if label else "") + ".",
                refs=item.refs,
            )
        )
    return _Lines(findings, dict(a_conflicts), dict(used))


def _questions(
    package: MeetPackage, lines: _Lines, declined: dict[str, str]
) -> list[DoubleTrackQuestion]:
    """Is it double track? Asked for a single-track section with at least two A conflicts,
    unless a No was given for the same trains."""
    names = {place.id: place.name for place in package.places}
    calls = {c.id: (t, c) for t in package.trains for c in t.calls}
    questions = []
    for section in package.sections:
        count = lines.a_conflicts.get(section.id, 0)
        if count < QUESTION_AT or section.tracks != TrackKind.SINGLE:
            continue
        fingerprint = _fingerprint(calls, lines.calls.get(section.id, set()))
        if declined.get(section.id) == fingerprint:
            continue
        title = f"{names[section.place_a]}–{names[section.place_b]}"
        questions.append(
            DoubleTrackQuestion(
                section=section.id,
                conflicts=count,
                fingerprint=fingerprint,
                message=f"Är det dubbelspår på {title}? I så fall försvinner {count} konflikter.",
            )
        )
    return questions


def _fingerprint(calls: dict[str, tuple[Train, Call]], used: set[tuple[str, str]]) -> str:
    """The trains on a section as they are: their numbers, days and the times at its ends."""
    rows = []
    for _train_id, call_id in sorted(used):
        train, call = calls[call_id]
        rows.append(
            [
                train.id,
                train.number,
                sorted(train.days),
                call.id,
                call.place,
                call.arrival,
                call.departure,
                call.day_offset,
            ]
        )
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def _days(days: set[int]) -> str | None:
    """Mån–Tor or Mån, Fre, or None when every day of the week."""
    if not days or len(days) == 7:
        return None
    runs: list[list[int]] = []
    for day in sorted(days):
        if runs and day == runs[-1][1] + 1:
            runs[-1][1] = day
        else:
            runs.append([day, day])
    return ", ".join(DAY_NAMES[a] if a == b else f"{DAY_NAMES[a]}–{DAY_NAMES[b]}" for a, b in runs)


def _id(*parts: str) -> str:
    """A finding's id, kept short enough for an Id."""
    text = "-".join(parts)
    if len(text) <= 80:
        return text
    return f"{parts[0]}-{hashlib.sha256(text.encode()).hexdigest()[:24]}"


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
    # Between a part and its station the station's own interlocking moves the train (TKL97).
    sections |= {frozenset((p.id, p.part_of)) for p in package.places if p.part_of is not None}
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
    """The minutes from the train's first day that the call holds its track. A passage holds
    it a minute (B)."""
    clock = [t for t in (call.arrival, call.departure) if t is not None]
    if not clock:
        return None
    minutes = [int(t[:2]) * 60 + int(t[3:]) + call.day_offset * DAY for t in clock]
    if len(minutes) == 2 and minutes[1] < minutes[0]:
        minutes[1] += DAY  # the departure is after midnight
    if not call.stops:
        return minutes[0], minutes[0] + PASSAGE
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


def _clock(minutes: float) -> str:
    minute = round(minutes) % DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"
