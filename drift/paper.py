"""Efter pappret (LOK-13, LOK-29, LF16, LF22): a duty the driver has on paper but the plan does
not have. The driver photographs its pages, the hub reads them with AI (Integrationer), and
Drift keeps what was read as a service run after the paper, which the driver runs at once.

AI only suggests. The paper's number, start and end are taken as they are written, and a time
that could not be read stays empty (LOK-29). The places on the paper are matched to the meet's
by name or signature; a row at a place the meet does not have keeps its name as read.

Before the reading becomes a service it is compared with the plan: the planned services that
start nearest the paper's start, at the same place first, are offered, and the driver may take
one of them instead (LF16). Trafikledningen then approves or rejects it. Until it is approved no
station sees it: it has no train in Drift, so it is in no snapshot and no clearance. Approved,
it is an extra train with the paper's calls (DRIFT-41, H12), marked Efter pappret wherever it
shows; rejected, the driver is told why.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Final

from contracts import drift as events
from contracts import driver as contract
from contracts.meet import MeetPackage
from contracts.reasons import Reason
from drift import drivers
from drift.driver_book import Paper, key_of, paper_ref
from drift.engine import SECONDS_PER_DAY, Drift, Refused, parse_time

# The planned services offered beside the paper: at most three, starting within an hour at the
# same place, or within half an hour anywhere else (LF16).
NEAREST: Final = 3
SAME_PLACE_WINDOW: Final = 3600
ELSEWHERE_WINDOW: Final = 1800
_WORD: Final = re.compile(r"[^0-9a-z]+")


def _plain(name: str) -> str:
    """A place's name to compare: no accents, no case, no punctuation."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WORD.sub(" ", bare).strip()


def match_place(package: MeetPackage, name: str | None) -> str | None:
    """The meet's place the paper names: by its name or signature, and else the one place whose
    name begins with what was read. None when the meet has no such place, or more than one."""
    if not name:
        return None
    asked = _plain(name)
    if not asked:
        return None
    for place in package.places:
        if asked in (_plain(place.name), _plain(place.code)):
            return place.id
    if len(asked) < 3:
        return None
    begins = [p for p in package.places if _plain(p.name).startswith(asked)]
    return begins[0].id if len(begins) == 1 else None


def matched(package: MeetPackage, reading: events.PaperReading) -> events.PaperReading:
    """The reading with the paper's places matched to the meet's (LOK-29)."""

    def end(given: events.PaperEnd) -> events.PaperEnd:
        return given.model_copy(update={"place": match_place(package, given.place_name)})

    return reading.model_copy(
        update={
            "start": end(reading.start),
            "end": end(reading.end),
            "rows": [
                row.model_copy(update={"place": match_place(package, row.place_name)})
                for row in reading.rows
            ],
        }
    )


# --- The driver reads the paper -------------------------------------------------------------


def may_read(drift: Drift, driver: str) -> None:
    """Before anything is read or paid for: a driver has one service at a time (LOK-40)."""
    if drift.drivers.service_of(driver) is not None:
        raise Refused(Reason.ONE_SERVICE)


def create(
    drift: Drift,
    driver: str,
    paper: str,
    reading: events.PaperReading,
    *,
    pages: int,
    paid_by: events.PaperPayer,
    cost: int,
    now: datetime,
) -> Paper:
    """Kör efter pappret (LOK-29): what was read becomes the driver's service, waiting for
    Trafikledningen. A paper that names none of the meet's places cannot be run."""
    may_read(drift, driver)
    found = matched(drift.package, reading)
    if not any(row.place for row in found.rows):
        raise Refused(Reason.PAPER_NO_PLACES)
    drift.record_driver(
        events.EventKind.PAPER_CREATED,
        events.PaperCreated(
            paper=paper, driver=driver, reading=found, pages=pages, paid_by=paid_by, cost=cost
        ).model_dump(mode="json"),
        now,
        actor=drivers.actor_of("driver", driver),
    )
    return drift.drivers.papers[paper]


# --- The plan beside the paper (LF16) -------------------------------------------------------


def _start(drift: Drift, paper: Paper) -> tuple[str | None, str | None, str | None]:
    """The paper's start: the front's time and place, else its first row's."""
    reading = paper.reading
    first = next((row for row in reading.rows if row.departure or row.arrival), None)
    time = reading.start.time or (first.departure or first.arrival if first else None)
    place = reading.start.place or (reading.rows[0].place if reading.rows else None)
    named = reading.start.place_name or (reading.rows[0].place_name if reading.rows else None)
    known = next((p for p in drift.package.places if p.id == place), None)
    return time, place, known.name if known else named


def _apart(one: int, other: int) -> int:
    """Seconds between two times of day, across midnight too."""
    gap = abs(one - other) % SECONDS_PER_DAY
    return min(gap, SECONDS_PER_DAY - gap)


def nearest(drift: Drift, paper: Paper) -> list[drivers.Service]:
    """The planned services that start nearest the paper's start: at the same place within an
    hour first, then elsewhere within half an hour; free before taken, none that is done."""
    time, place, _ = _start(drift, paper)
    if time is None:
        return []
    wanted = parse_time(time)
    _, listed = drivers.services(drift)
    scored: list[tuple[bool, bool, int, drivers.Service]] = []
    for service in listed:
        key = key_of(service.ref)
        if key in drift.drivers.done:
            continue
        first = service.calls[0]
        begins = first.departure or first.arrival
        if begins is None:
            continue
        gap = _apart(parse_time(begins), wanted)
        same = place is not None and first.place == place
        if gap <= (SAME_PLACE_WINDOW if same else ELSEWHERE_WINDOW):
            taken = key in drift.drivers.holders
            scored.append((not same, taken, gap, service))
    scored.sort(key=lambda item: (item[0], item[1], item[2], drivers.start_seconds(item[3])))
    return [service for *_, service in scored[:NEAREST]]


def said(drift: Drift, paper: Paper, found: list[drivers.Service]) -> str:
    """The paper beside the plan, in words (LF16): no service starts there and then, the nearest
    ones, or the one that does and may be the same."""
    time, place, name = _start(drift, paper)
    kind, _ = drivers.services(drift)
    duty = kind == events.ServiceKind.DUTY
    if time is None:
        return "Starten gick inte att läsa på pappret, så den kan inte jämföras med planen."
    where = f" vid {name}" if name else ""
    same = [
        s
        for s in found
        if s.calls[0].place == place and (s.calls[0].departure or s.calls[0].arrival) == time
    ]
    if same:
        noun = "Tjänst" if duty else "Tåg"
        return f"{noun} {same[0].number} i planen startar {time}{where}. Är det samma som pappret?"
    nobody = "Ingen tjänst" if duty else "Inget tåg"
    if not found:
        return f"{nobody} i planen startar {time}{where}, och ingen nära den tiden."
    close = ", ".join(f"{s.number} kl. {s.calls[0].departure or s.calls[0].arrival}" for s in found)
    return f"{nobody} startar {time}{where}. Närmast: {close}."


def view(
    drift: Drift,
    paper: Paper,
    *,
    names: Mapping[str, str | None] | None = None,
    photos: list[str] | None = None,
) -> contract.PaperService:
    """The paper as the driver and Förare see it: what was read, where it stands and the plan
    beside it."""
    found = nearest(drift, paper)
    reading = paper.reading
    return contract.PaperService(
        paper=paper.id,
        service=paper_ref(paper.id),
        status=paper.status,
        driver=paper.driver,
        driver_name=(names or {}).get(paper.driver),
        number=reading.number,
        train_number=paper.train_number or reading.train_number,
        operator=reading.operator,
        start=reading.start,
        end=reading.end,
        rows=reading.rows,
        pages=paper.pages,
        photos=photos or [],
        paid_by=paper.paid_by,
        cost=paper.cost,
        said=said(drift, paper, found),
        candidates=[drivers.offer(drift, service, names=names) for service in found],
        reason=paper.reason,
        train=paper.train,
        model_time=paper.at.model_time,
        wall_time=paper.at.wall_time,
    )


def listed(drift: Drift) -> list[Paper]:
    """The papers for Förare: those waiting for an answer first, then the newest."""
    return sorted(
        drift.drivers.papers.values(),
        key=lambda p: (p.status != events.PaperStatus.WAITING, -p.seq),
    )


# --- Trafikledningen decides (LOK-13, LF22) --------------------------------------------------


def _waiting(drift: Drift, paper: str) -> Paper:
    found = drift.drivers.papers.get(paper)
    if found is None:
        raise Refused(Reason.UNKNOWN_PAPER)
    if found.status != events.PaperStatus.WAITING:
        raise Refused(Reason.PAPER_DECIDED)
    return found


def extra_train(drift: Drift, paper: Paper, number: str | None) -> events.ExtraTrain:
    """The extra train the paper becomes (H12): its rows at the meet's places, as they stand,
    on today's traffic day. Raises Refused for what the stations could not clear."""
    rows = [row for row in paper.reading.rows if row.place is not None]
    if len({row.place for row in rows}) < 2:
        raise Refused(Reason.PAPER_FEW_PLACES)
    times = [row.departure or row.arrival for row in rows]
    first = next((time for time in times if time is not None), None)
    if first is None:
        raise Refused(Reason.PAPER_NO_TIMES)
    train_number = (number or "").strip() or paper.reading.train_number
    if not train_number:
        raise Refused(Reason.PAPER_NO_NUMBER)
    return events.ExtraTrain(
        number=train_number,
        departure=first,
        days=[drift.traffic_day],
        calls=[
            events.ExtraCall(
                place=row.place,
                arrival=row.arrival,
                departure=row.departure,
                track=row.track,
                stops=row.stops,
                note=row.note,
            )
            for row in rows
            if row.place is not None
        ],
        paper=paper.id,
    )


def change_id_of(paper: str) -> str:
    """The driftändring an approved paper is: one per paper, so it is never made twice."""
    return f"c-{paper}"


def approve(drift: Drift, paper: str, number: str | None, now: datetime) -> events.ExtraTrain:
    """Godkänn (LOK-13): the paper becomes an extra train in Drift, which the stations see and
    clear, marked Efter pappret. The driver keeps running it. Returns the change it is, which
    goes to Planering as a proposal like every driftändring (4.4)."""
    found = _waiting(drift, paper)
    extra = extra_train(drift, found, number)
    change_id = change_id_of(paper)
    drift.make_change(events.MakeChange(change=extra), now, change_id)
    drift.record_driver(
        events.EventKind.PAPER_APPROVED,
        events.PaperApproved(
            paper=paper, change_id=change_id, train=f"x-{change_id}", train_number=extra.number
        ).model_dump(mode="json"),
        now,
        actor=events.Actor(kind=events.ActorKind.DISPATCHER),
        train=f"x-{change_id}",
    )
    return extra


def reject(drift: Drift, paper: str, reason: str, now: datetime) -> None:
    """Avslå: the driver no longer runs it, and is told why."""
    _waiting(drift, paper)
    drift.record_driver(
        events.EventKind.PAPER_REJECTED,
        events.PaperRejected(paper=paper, reason=reason).model_dump(mode="json"),
        now,
        actor=events.Actor(kind=events.ActorKind.DISPATCHER),
    )
