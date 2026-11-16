"""Härledningen (4c1, IMPORT-17, IMPORT-33): a draft from the station lists alone, without the
planning file. Underlagsnivå 1.

The rules (the import's chapter 4, I3), each derived fact marked osäker until the planner
confirms it in Bana (IMPORT-04, PLAN-02):

- A place with its own list clears trains (bemannad), or is a shadow yard when every train in
  its list starts or ends there.
- A code before the track, "Tri 1" in Steinsnes's list, is a place that station runs from afar
  (fjärrstyrd).
- A place named only in Från or Till has no list of its own: trains start or end there, so it
  is an industry or a halt (industri/hållplats), with no time in any list.
- The trains' route is put together over the lists: the same number on the same days between
  the same Från and Till is one train, in the order of its times. Runs that share all of that
  are told apart only on exact times (IMPORT-27).
- A section runs between two places that follow each other on a train's route, single track
  until the track picture or the planner says otherwise.

With the track picture as well (underlagsnivå 2, track_picture.py):

- Each place takes its signature's place on the picture, which becomes the map in Bana.
- A place named only in Från or Till takes the signature on the picture that is an abbreviation
  of its name ("Tve" for Tveiten), or else the only one with the same first letter. That rule is
  said, and the signature is osäker.
- A place on the picture without a list is a place in between: an industry or a halt inside the
  section, where the trains have no time. The lists give no time where the line branches
  either, so such a place lies inside the sections too, and the report says so.
- A section the trains give and the picture shows is säker, with the places in between as its
  parts; two lines side by side all the way make it double track.

Ported from the old Cloud (cloud/domain.py, build_linear_topology), without its silent guesses
(IMPORT-29): no signature is made up, and what a rule decided is said in the report.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

from pydantic import ValidationError

from contracts.common import Weekday
from contracts.meet import (
    Call,
    Clock,
    Display,
    MapPoint,
    Meet,
    MeetPackage,
    Place,
    PlaceKind,
    PlanTrack,
    Section,
    SectionPart,
    TrackKind,
    Train,
)
from contracts.planning import (
    Alternative,
    Certainty,
    Fact,
    ImportReport,
    ImportResult,
    Origin,
    Question,
    Rulebook,
    Source,
    TrainTypeRule,
)
from integrationer import rulebook
from integrationer.planning_json import CONTENT_WORD
from integrationer.station_lists import ListError, Lists, Row, abbreviates, merged
from integrationer.track_picture import Picture

LEVEL: Final = 1  # Stationstidtabeller: underlagsnivå 1 (I1)
DRAWN: Final = 2  # + banbilden: underlagsnivå 2
DAY: Final = 24 * 60
WEEK: Final = list(Weekday)
SHOWN: Final = 3


@dataclass
class _Place:
    id: str
    code: str
    name: str
    at: str
    listed: bool = False
    kind: PlaceKind = PlaceKind.MANNED
    remote_from: str | None = None
    tracks: set[str] = field(default_factory=set)
    kind_note: str = ""
    named_by: str | None = None  # the train that gave a place known by its code its name
    drawn: str | None = None  # the signature on the track picture
    only_drawn: bool = False  # on the picture, in no list
    code_note: str | None = None  # how the signature was found, when a rule decided it


@dataclass
class _Stop:
    place: str
    row: Row

    @property
    def at(self) -> str:
        page = f", sida {self.row.page}" if self.row.page else ""
        return f"{self.row.document}{page}, rad {self.row.row}"

    @property
    def time(self) -> int:
        return _minutes(self.row.arrival or self.row.departure or "00:00")

    @property
    def starts(self) -> bool:
        """The row where the train begins: no Från and no arrival."""
        return not self.row.origin and self.row.arrival is None

    @property
    def ends(self) -> bool:
        """The row where the train ends: no Till and no departure."""
        return not self.row.destination and self.row.departure is None


@dataclass
class _Run:
    number: str
    days: frozenset[int]
    origin: str
    destination: str
    stops: list[_Stop]
    start: int = 0


def draft(
    found: Lists,
    *,
    meet: Meet,
    source: Source,
    picture: Picture | None = None,
    drawn: Source | None = None,
) -> ImportResult:
    """The draft the lists give, with the track picture when there is one (drawn is its
    source). Raises ListError when no train can be read."""
    return _Derivation(found, meet, source, picture if drawn else None, drawn).run()


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _slug(text: str) -> str:
    """An id part from a signature or a name: Gdö is gdo, Munkerød is munkerod."""
    text = text.casefold().replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "x"


def _natural(name: str) -> tuple[int, str]:
    digits = re.match(r"\d+", name)
    return (int(digits[0]) if digits else 1 << 30, name)


def _joined(names: list[str]) -> str:
    """Skuggvik havn, Tveiten och Kjøllstad."""
    unique = list(dict.fromkeys(names))
    return unique[0] if len(unique) == 1 else ", ".join(unique[:-1]) + " och " + unique[-1]


def plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _number_order(number: str) -> tuple[int, str]:
    return (int(number), number) if number.isdigit() else (1 << 30, number)


class _Derivation:
    def __init__(
        self,
        found: Lists,
        meet: Meet,
        source: Source,
        picture: Picture | None,
        drawn: Source | None,
    ) -> None:
        self.found = found
        self.meet = meet
        self.source = source
        self.picture = picture
        self.drawn = drawn
        self.places: dict[str, _Place] = {}
        self.by_code: dict[str, _Place] = {}
        self.by_name: dict[str, _Place] = {}
        self.facts: list[Fact] = []
        self.notes: list[str] = []
        self.left_out: list[str] = list(found.left_out)
        self.unnamed: list[str] = []
        self.midnight: list[str] = []
        # Read with code from text: trolig. Written down by AI: osäker until confirmed (I2).
        self.read = Certainty.UNSURE if found.transcribed else Certainty.LIKELY
        self.confirmed: set[str] = set()

    def origin(self, at: str) -> Origin:
        return Origin(source=self.source.id, at=at)

    def on_picture(self, what: str = "") -> Origin:
        assert self.drawn is not None and self.picture is not None
        at = f"Banbilden, sida {self.picture.page}" + (f", {what}" if what else "")
        return Origin(source=self.drawn.id, at=at)

    def fact(
        self,
        ref: str,
        certainty: Certainty,
        at: list[str],
        note: str | None = None,
        also: list[Origin] | None = None,
    ) -> None:
        origins = [self.origin(a) for a in dict.fromkeys(at)] + (also or [])
        self.facts.append(Fact(ref=ref, certainty=certainty, origins=origins, note=note))

    def run(self) -> ImportResult:
        stops = self._stops()
        runs = self._runs(stops)
        if not runs:
            raise ListError("Listorna har inga tåg att bygga utkastet av.")
        trains = self._trains(runs)
        self._kinds(stops)
        if self.picture is not None:
            self._from_picture(trains)
        sections = self._sections(trains)
        rules, questions = self._rulebook(trains)
        places = [self._place(p) for p in self.places.values()]
        clock = Clock(start_time="06:00")
        self.notes.append("Listorna anger ingen starttid för klockan; 06:00 tills du ändrar.")
        if self.unnamed:
            self.notes.append(
                f"{_joined(self.unnamed)} har ingen signatur i listorna; namnet används."
            )
        if self.midnight:
            self.notes.append(
                f"Tåg {_joined(self.midnight)} går över midnatt; dagarna i listan gäller när "
                "tåget börjar."
            )
        layout = {
            p.id: MapPoint(x=self.picture.places[p.drawn][0], y=self.picture.places[p.drawn][1])
            for p in self.places.values()
            if self.picture is not None and p.drawn is not None
        }
        try:
            package = MeetPackage(
                meet=self.meet,
                clock=clock,
                places=places,
                sections=sections,
                trains=trains,
                display=Display(reference_layout=layout),
            )
        except ValidationError as error:
            raise ListError(
                f"Utkastet ur listorna gick inte att föra in: {error.errors()[0]['msg']}"
            ) from error
        counts = Counter(place.kind for place in places)
        report = ImportReport(
            source=self.source.id,
            level=DRAWN if self.picture is not None else LEVEL,
            places={kind: counts[kind] for kind in PlaceKind if counts[kind]},
            sections=len(sections),
            parts=sum(len(section.parts) for section in sections),
            trains=len(trains),
            calls=sum(len(train.calls) for train in trains),
            train_types=len(rules.train_types),
            notes=[self._summary(sections), *dict.fromkeys(self.notes)],
            left_out=list(dict.fromkeys(self.left_out)),
        )
        return ImportResult(
            package=package,
            facts=self.facts,
            rulebook=rules,
            questions=questions,
            report=report,
        )

    def _summary(self, sections: list[Section]) -> str:
        lists = f"Utkastet är härlett ur {len(self.found.rows)} stationslistor"
        if self.found.transcribed:
            lists += " som AI har skrivit av, så tågen och tiderna är också osäkra"
        if self.picture is None:
            return (
                f"{lists}. Platstyperna och sträckorna är osäkra tills du bekräftar dem i Bana; "
                "banbilden, grafen eller planeringsfilen höjer nivån."
            )
        shown = sum(1 for s in sections if s.id in self.confirmed)
        between = sum(1 for p in self.places.values() if p.only_drawn)
        double = sum(1 for s in sections if s.tracks == TrackKind.DOUBLE)
        return (
            f"{lists} och banbilden. Banbilden visar {shown} av {len(sections)} sträckor, "
            f"{plural(between, 'plats', 'platser')} emellan och dubbelspår på "
            f"{plural(double, 'sträcka', 'sträckor')}. Platstyperna är osäkra tills du "
            "bekräftar dem i Bana."
        )

    # --- Places ------------------------------------------------------------------------------

    def _new(self, code: str, name: str, at: str) -> _Place:
        base = f"l-{_slug(code)}"
        place_id, n = base, 1
        while place_id in self.places:
            n += 1
            place_id = f"{base}-{n}"
        place = _Place(id=place_id, code=code, name=name, at=at)
        self.places[place_id] = place
        self.by_code.setdefault(code.casefold(), place)
        self.by_name.setdefault(name.casefold(), place)
        return place

    def _named(self, name: str, at: str) -> _Place:
        """The place a train starts or ends at, by the name in Från or Till."""
        found = self.by_name.get(name.casefold())
        if found is not None:
            return found
        place = self._new(name, name, at)
        place.kind = PlaceKind.HALT
        place.kind_note = (
            "Står bara i kolumnen Från eller Till: tåg börjar eller slutar här, men platsen har "
            "ingen egen lista. Industri eller hållplats tills du säger annat."
        )
        self.unnamed.append(name)
        return place

    def _stops(self) -> list[_Stop]:
        """Every row as a stop at its place: the list's own station, or the place it runs from
        afar, by the code before the track."""
        homes: list[tuple[_Place, list[Row]]] = []
        for document, rows in sorted(self.found.rows.items()):
            first = rows[0]
            place = self.by_code.get((first.code or first.station).casefold()) or self.by_name.get(
                first.station.casefold()
            )
            if place is None:
                place = self._new(first.code or first.station, first.station, document)
                if not first.code:
                    self.notes.append(
                        f"{document} har ingen signatur; namnet {first.station} används."
                    )
            place.listed = True
            homes.append((place, rows))
        stops: list[_Stop] = []
        for home, rows in homes:
            for row in merged(rows):
                place = home
                if row.remote:
                    place = self.by_code.get(row.remote.casefold()) or self._remote(home, row)
                if row.track:
                    place.tracks.add(row.track)
                stops.append(_Stop(place.id, row))
        return stops

    def _remote(self, home: _Place, row: Row) -> _Place:
        at = f"{row.document}, rad {row.row}"
        place = self._new(row.remote or "", row.remote or "", at)
        place.kind = PlaceKind.REMOTE
        place.remote_from = home.id
        place.kind_note = f"Står med signaturen före spåret i listan för {home.name}."
        return place

    def _kinds(self, stops: list[_Stop]) -> None:
        own: dict[str, list[_Stop]] = defaultdict(list)
        for stop in stops:
            if not stop.row.remote:
                own[stop.place].append(stop)
        for place in self.places.values():
            if not place.listed:
                continue
            rows = own.get(place.id, [])
            if rows and all(s.starts or s.ends for s in rows):
                place.kind = PlaceKind.SHADOW_YARD
                place.kind_note = "Varje tåg i listan börjar eller slutar här: skuggbangård."
            else:
                place.kind = PlaceKind.MANNED
                place.kind_note = "Har en egen stationslista: klarerar tåg."

    def _place(self, place: _Place) -> Place:
        drawn = [self.on_picture(place.drawn)] if place.drawn else []
        at = [] if place.only_drawn else [place.at]
        both = Certainty.SURE if at and drawn else self.read if at else Certainty.LIKELY
        self.fact(f"place:{place.id}", both, at, also=drawn)
        self.fact(f"place:{place.id}.kind", Certainty.UNSURE, at, place.kind_note, also=drawn)
        if place.code_note:
            self.fact(f"place:{place.id}.code", Certainty.UNSURE, at, place.code_note, also=drawn)
        if place.code == place.name and place.kind == PlaceKind.REMOTE and not place.named_by:
            self.notes.append(
                f"{place.code} står bara med signaturen i listorna; namnet saknas tills du "
                "lägger till det."
            )
        return Place(
            id=place.id,
            code=place.code,
            name=place.name,
            kind=place.kind,
            remote_from=place.remote_from,
            tracks=[
                PlanTrack(name=name, sort_order=index)
                for index, name in enumerate(sorted(place.tracks, key=_natural))
            ],
        )

    def _from_picture(self, trains: list[Train]) -> None:
        """The picture's signatures on the places: by signature, by the rule for a place
        without one in the lists, and the rest as places in between."""
        assert self.picture is not None
        picture = self.picture
        codes = {code.casefold(): code for code in picture.places}
        for place in self.places.values():
            code = codes.get(place.code.casefold())
            if code is not None and not (place.code == place.name and place.kind == PlaceKind.HALT):
                place.drawn = code
        free = {c for c in picture.places if c not in {p.drawn for p in self.places.values()}}
        through = {c.place for t in trains for c in t.calls[1:-1]}
        waiting = [p for p in self.places.values() if p.drawn is None and p.code == p.name]

        def candidates(place: _Place) -> tuple[list[str], list[str]]:
            """The free signatures that begin as the name, and those that abbreviate it. A
            place trains run through has at least two lines on the picture."""
            first = sorted(
                c
                for c in free
                if c.casefold()[0] == place.name.casefold()[0]
                and (place.id not in through or picture.branches(c) >= 2)
            )
            return first, [c for c in first if abbreviates(c, place.name)]

        guessed: list[str] = []
        # Settled one at a time until nothing more is settled: a signature taken by one place
        # is no longer one of the others' choices (Ste for Steinsnes leaves Spn for Spiten).
        settled = True
        while settled:
            settled = False
            for loose in (False, True):
                for place in [p for p in waiting if p.drawn is None]:
                    first, short = candidates(place)
                    if len(short) == 1:
                        code, rule = short[0], f"{short[0]} är en förkortning av {place.name}"
                    elif loose and not short and len(first) == 1:
                        code, rule = (
                            first[0],
                            f"{first[0]} är den enda signaturen på banbilden som börjar som "
                            f"{place.name} och inte har en lista",
                        )
                    else:
                        continue
                    free.discard(code)
                    self.by_code[code.casefold()] = place
                    place.code, place.drawn = code, code
                    place.code_note = f"Signaturen ur banbilden: {rule}."
                    guessed.append(f"{code} för {place.name}")
                    settled = True
                if settled:
                    break
        unclear = []
        for place in waiting:
            first, short = candidates(place)
            if place.drawn is None and first:
                shown = _joined(short or first).replace(" och ", " eller ")
                unclear.append(f"{place.name} ({shown})")
        if guessed:
            self.notes.append(
                f"Signaturerna ur banbilden, osäkra tills du bekräftar dem: {_joined(guessed)}."
            )
        if unclear:
            self.notes.append(
                f"Banbilden har flera signaturer som kan vara {_joined(unclear)}; ingen väljs "
                "på en gissning."
            )
        between: list[str] = []
        branching: list[str] = []
        for code in sorted(free):
            place = self._new(code, code, f"Banbilden, sida {self.picture.page}")
            place.kind, place.drawn, place.only_drawn = PlaceKind.HALT, code, True
            place.kind_note = (
                "Står på banbilden men har ingen lista: industri eller hållplats inne i sträckan."
            )
            between.append(code)
            if self.picture.branches(code) >= 3:
                branching.append(code)
                place.kind_note = (
                    "Banan grenar sig här. Platsen har ingen lista och tågen har ingen tid här, "
                    "så den ligger inne i sträckorna tills du ändrar platstypen."
                )
        if between:
            self.notes.append(
                f"{_joined(between)} står på banbilden men har ingen lista; signaturen används "
                "som namn."
            )
        if branching:
            self.notes.append(
                f"Banan grenar sig vid {_joined(branching)}, som saknar lista och tider: platsen "
                "ligger inne i sträckorna tills du ändrar platstypen."
            )

    # --- Trains -------------------------------------------------------------------------------

    def _route(self, stop: _Stop) -> tuple[str, str]:
        here = self.places[stop.place].name
        return (stop.row.origin or here, stop.row.destination or here)

    def _runs(self, stops: list[_Stop]) -> list[_Run]:
        groups: dict[tuple[str, frozenset[int]], list[_Stop]] = defaultdict(list)
        for stop in stops:
            groups[(stop.row.number, frozenset(stop.row.days))].append(stop)
        runs: list[_Run] = []
        for (number, days), group in sorted(
            groups.items(), key=lambda item: (_number_order(item[0][0]), sorted(item[0][1]))
        ):
            by_route: dict[tuple[str, str], list[_Stop]] = defaultdict(list)
            stated_from = {self._route(s) for s in group if s.row.origin}
            stated_to = {self._route(s) for s in group if s.row.destination}
            for stop in group:
                route = self._route(stop)
                if not stop.row.origin and route not in stated_from:
                    known = [k for k in stated_from if k[1] == route[1]]
                    route = self._joined(stop, route, known, 0)
                elif not stop.row.destination and route not in stated_to:
                    known = [k for k in stated_to if k[0] == route[0]]
                    route = self._joined(stop, route, known, 1)
                by_route[route].append(stop)
            for (origin, destination), members in sorted(by_route.items()):
                for part in self._split(members):
                    runs.append(_Run(number, days, origin, destination, part))
        return runs

    def _joined(
        self, stop: _Stop, route: tuple[str, str], known: list[tuple[str, str]], end: int
    ) -> tuple[str, str]:
        """The first or last row of a train whose place the other lists call by another name:
        the one train between the same places it can belong to. A place known only by its
        code takes the name the other lists give it (end 0: Från, end 1: Till)."""
        if len(known) != 1:
            return route
        found = known[0]
        place = self.places[stop.place]
        name = found[end]
        if (
            place.kind == PlaceKind.REMOTE
            and place.name == place.code
            and name.casefold() not in self.by_name
        ):
            place.name = name
            place.named_by = stop.row.number
            self.by_name[name.casefold()] = place
            self.notes.append(f"{place.code} heter {name}, som tåg {stop.row.number} kallar den.")
        return found

    def _split(self, stops: list[_Stop]) -> list[list[_Stop]]:
        """Runs with the same number, days, Från and Till, told apart on their exact times:
        each row goes with the run that began last before it (IMPORT-27)."""
        starts = sorted({s.time for s in stops if s.starts})
        ends = sorted({s.time for s in stops if s.ends})
        if len(starts) <= 1 and len(ends) <= 1:
            return [stops]
        parts: dict[int, list[_Stop]] = defaultdict(list)
        for stop in stops:
            if len(starts) > 1:
                before = [t for t in starts if t <= stop.time]
                parts[before[-1] if before else starts[-1]].append(stop)
            else:
                after = [t for t in ends if t >= stop.time]
                parts[after[0] if after else ends[0]].append(stop)
        return [parts[key] for key in sorted(parts)]

    def _trains(self, runs: list[_Run]) -> list[Train]:
        for run in runs:
            run.start = self._order(run)
        trains: list[Train] = []
        used: Counter[str] = Counter()
        for run in sorted(runs, key=lambda r: (_number_order(r.number), r.start, r.origin)):
            base = f"lt-{_slug(run.number)}"
            used[base] += 1
            train_id = base if used[base] == 1 else f"{base}-{used[base]}"
            trains.append(self._train(train_id, run))
        return trains

    def _order(self, run: _Run) -> int:
        """The stops in the order of their times, from the first row, or after the longest
        pause when no list has the first row. Returns the minute the train starts."""
        starts = [s.time for s in run.stops if s.starts]
        if starts:
            anchor = starts[0]
        else:
            times = sorted({s.time for s in run.stops})
            gaps = [
                ((times[(i + 1) % len(times)] - t) % DAY or DAY, times[(i + 1) % len(times)])
                for i, t in enumerate(times)
            ]
            anchor = max(gaps)[1] if len(times) > 1 else times[0]

        def rank(stop: _Stop) -> tuple[int, int]:
            return ((stop.time - anchor) % DAY, 0 if stop.starts else 2 if stop.ends else 1)

        run.stops.sort(key=rank)
        return anchor

    def _train(self, train_id: str, run: _Run) -> Train:
        labels = Counter(s.row.label for s in run.stops)
        label = labels.most_common(1)[0][0]
        tokens = label[: len(label) - len(run.number)].split()
        calls: list[Call] = []
        at = [s.at for s in run.stops]
        first = self.places[run.stops[0].place]
        if first.name != run.origin:
            calls.append(self._untimed(train_id, len(calls), run.origin, run.stops[0], "börjar"))
        for stop in run.stops:
            call_id = f"{train_id}.{len(calls) + 1}"
            self.fact(f"call:{call_id}", self.read, [stop.at])
            calls.append(
                Call(
                    id=call_id,
                    place=stop.place,
                    track=stop.row.track or None,
                    arrival=stop.row.arrival,
                    departure=stop.row.departure,
                    day_offset=1 if stop.time < run.start else 0,
                    stops=stop.row.stops,
                )
            )
        last = self.places[run.stops[-1].place]
        if last.name != run.destination:
            calls.append(
                self._untimed(train_id, len(calls), run.destination, run.stops[-1], "slutar")
            )
        if any(call.day_offset for call in calls):
            self.midnight.append(run.number)
        self.fact(f"train:{train_id}", self.read, at)
        return Train(
            id=train_id,
            number=run.number,
            train_type=tokens[-1] if tokens else None,
            operator=" ".join(tokens[:-1]) or None,
            days=[WEEK[d] for d in sorted(run.days)],
            calls=calls,
        )

    def _untimed(self, train_id: str, index: int, name: str, near: _Stop, verb: str) -> Call:
        place = self._named(name, near.at)
        call_id = f"{train_id}.{index + 1}"
        note = (
            f"Tåget {verb} här enligt kolumnen {'Från' if verb == 'börjar' else 'Till'}; "
            "tiden står inte i någon lista."
        )
        if place.listed:
            note = f"{note} {place.name}s lista har inte tåget."
        self.fact(f"call:{call_id}", Certainty.UNSURE, [near.at], note)
        return Call(id=call_id, place=place.id)

    # --- Sections -----------------------------------------------------------------------------

    def _sections(self, trains: list[Train]) -> list[Section]:
        """Between places that follow each other on a train's route. Industries and halts lie
        along a section and are passed over, as Drift does."""
        halts = {p.id for p in self.places.values() if p.kind == PlaceKind.HALT}
        pairs: dict[frozenset[str], tuple[str, str]] = {}
        evidence: dict[frozenset[str], list[str]] = defaultdict(list)
        for train in trains:
            route = [c.place for c in train.calls if c.place not in halts]
            for a, b in pairwise(route):
                if a == b:
                    continue
                pair = frozenset((a, b))
                pairs.setdefault(pair, (a, b))
                if train.number not in evidence[pair]:
                    evidence[pair].append(train.number)
        sections: list[Section] = []
        for pair, (a, b) in pairs.items():
            numbers = evidence[pair]
            section_id = f"s-{a.removeprefix('l-')}-{b.removeprefix('l-')}"
            shown = ", ".join(numbers[:SHOWN]) + (" …" if len(numbers) > SHOWN else "")
            names = f"{self.places[a].name} och {self.places[b].name}"
            running = f"{plural(len(numbers), 'tåg', 'tåg')} går direkt mellan {names}"
            way = self._way(a, b, halts)
            if way is None:
                missing = " Banbilden visar ingen väg mellan dem." if self.picture else ""
                self.fact(
                    f"section:{section_id}",
                    Certainty.UNSURE,
                    [f"Tåg {shown}"],
                    f"Härledd: {running}. Enkelspår tills banbilden eller du säger annat.{missing}",
                )
                part = SectionPart(id=f"{section_id}.1", from_place=a, to_place=b)
                self.fact(f"part:{part.id}", Certainty.UNSURE, [f"Tåg {shown}"])
                sections.append(Section(id=section_id, place_a=a, place_b=b, parts=[part]))
                continue
            assert self.picture is not None
            drawn = [self.places[p].drawn or "" for p in way]
            double = all(self.picture.links.get(frozenset(link), False) for link in pairwise(drawn))
            through = [self.places[p].name for p in way[1:-1]]
            self.confirmed.add(section_id)
            self.fact(
                f"section:{section_id}",
                Certainty.SURE,
                [f"Tåg {shown}"],
                f"{running.capitalize()}, och banbilden visar vägen"
                + (f" förbi {_joined(through)}" if through else "")
                + (". Dubbelspår: två linjer hela vägen." if double else ". Enkelspår."),
                also=[self.on_picture("–".join(drawn))],
            )
            parts = [
                SectionPart(id=f"{section_id}.{n}", from_place=x, to_place=y)
                for n, (x, y) in enumerate(pairwise(way), 1)
            ]
            for part in parts:
                link = f"{self.places[part.from_place].drawn}–{self.places[part.to_place].drawn}"
                self.facts.append(
                    Fact(
                        ref=f"part:{part.id}",
                        certainty=Certainty.LIKELY,
                        origins=[self.on_picture(link)],
                    )
                )
            sections.append(
                Section(
                    id=section_id,
                    place_a=a,
                    place_b=b,
                    tracks=TrackKind.DOUBLE if double else TrackKind.SINGLE,
                    parts=parts,
                )
            )
        return sections

    def _way(self, a: str, b: str, halts: set[str]) -> list[str] | None:
        """The places from a to b on the picture, through industries and halts only."""
        if self.picture is None:
            return None
        start, end = self.places[a].drawn, self.places[b].drawn
        if start is None or end is None:
            return None
        through = {self.places[p].drawn for p in halts if self.places[p].drawn}
        way = self.picture.path(start, end, {c for c in through if c})
        if way is None:
            return None
        by_drawn = {p.drawn: p.id for p in self.places.values() if p.drawn}
        return [by_drawn[code] for code in way]

    # --- The rulebook -------------------------------------------------------------------------

    def _rulebook(self, trains: list[Train]) -> tuple[Rulebook, list[Question]]:
        """One rule per abbreviation the trains carry: the rulebook's, or a question where it
        has none. The lists themselves say nothing about what a train type runs."""
        codes: dict[str, list[str]] = defaultdict(list)
        for train in trains:
            if train.train_type:
                codes[train.train_type].append(train.number)
        rules: list[TrainTypeRule] = []
        questions: list[Question] = []
        for code, numbers in sorted(codes.items(), key=lambda item: rulebook.key(item[0])):
            origins = [self.origin(f"Tåg {', '.join(numbers[:SHOWN])}")]
            known = rulebook.known(code)
            if known is not None:
                rules.append(known.model_copy(update={"origins": [*origins, *known.origins]}))
            else:
                rules.append(TrainTypeRule(code=code, certainty=Certainty.UNSURE, origins=origins))
                questions.append(
                    Question(
                        id=f"train-type-{rulebook.key(code) or 'x'}",
                        cause="train_type",
                        message=(f"Vad kör tågslaget {code}? Listorna och regelboken säger inget."),
                        refs=[f"train_type:{code}"],
                        alternatives=[
                            Alternative(value=content, label=CONTENT_WORD[content].capitalize())
                            for content in ("passengers", "goods", "service")
                        ],
                    )
                )
        for rule in rules:
            self.facts.append(
                Fact(ref=f"train_type:{rule.code}", certainty=rule.certainty, origins=rule.origins)
            )
        return Rulebook(train_types=rules), questions
