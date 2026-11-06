"""Stefan's planning file (JSON), read with code and without AI: level 4, the key.

The planning program saves the whole plan as .NET's reference-preserving JSON: an object may
carry "$id", a repeat of it is {"$ref": id}, and lists sit in {"$values": [...]}. Nothing in
the file is run.

What is read, and how (ported from the old Cloud's planning_json, made plain):
- Operation locations become places. The kind comes from the file: manned, shadow yard, remote
  (ControlledBy) or industry. A place that lies inside a clearance section and ends none has no
  clearance of its own, so it is a halt along that section (spec F1, F2). The rest are unmanned.
- Dispatch stretches become sections, the plan's clearance sections; their track stretches are
  the parts, in order from one end to the other. A track stretch outside every dispatch stretch
  has no clearance in the plan and is named in the report.
- Trains become trains with their calls in the plan's order (Sequence). The traffic days come
  from the program's two-week session mask, Monday first. "1.00:05:00" is the next game day.
  The same time in and out is a passage (no stop); a stop with neither arrival nor departure
  exchange is a stop without exchange. Shunting categories are shunting tasks, not trains.
- Two trains that share a number on the same days are kept apart by operator and abbreviation,
  and by their route when that is not enough (service_key, F9).
- Driver duties become duties and the program's schedules become turns.
- The settings give the clock and the game week; the meet's own name, dates and country stay.
- Train types go through the rulebook. A type whose content neither the file nor the rulebook
  knows becomes a question. The train number never decides it.
- Participants, vehicle contributions and owners are personal data and are never read.
"""

from __future__ import annotations

import json
import re
import zlib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from pydantic import ValidationError

from contracts.common import Language, Weekday
from contracts.meet import (
    About,
    Call,
    Clock,
    Duty,
    DutyLeg,
    Meet,
    MeetPackage,
    Place,
    PlaceKind,
    PlanTrack,
    Section,
    SectionPart,
    Shunting,
    TrackKind,
    TrafficWeek,
    Train,
    Turn,
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
    TrainContent,
    TrainTypeRule,
)
from integrationer import rulebook

MAX_BYTES: Final = 40 * 1024 * 1024
MAX_CALLS: Final = 20_000
LEVEL: Final = 4
#: The program's Content on a train category.
CONTENT: Final[dict[int, TrainContent]] = {1: "passengers", 2: "goods"}
#: The session mask has two weeks; bit 0 and bit 7 are both Monday.
WEEK: Final = 0b1111111
WEEKDAYS: Final = list(Weekday)
_CLOCK = re.compile(r"(?:(\d+)\.)?(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
#: [se] starts a language and [/se] ends it, as the planning program writes them.
_MARKER = re.compile(r"^\s*\[(/?)([A-Za-z]{2})\]\s*$")
_MARKERS: Final = {
    "se": "sv",
    "sv": "sv",
    "da": "da",
    "dk": "da",
    "no": "nb",
    "nb": "nb",
    "nn": "nb",
    "de": "de",
    "en": "en",
    "gb": "en",
    "uk": "en",
}
_EMPTY_ELEMENT = re.compile(r"^\s*<[A-Za-z][\w.-]*\s*/>\s*$")
COUNTRY_LANGUAGE: Final = {
    "se": Language.SV,
    "dk": Language.DA,
    "no": Language.NB,
    "de": Language.DE,
}
CONTENT_WORD: Final[dict[TrainContent, str]] = {
    "passengers": "resande",
    "goods": "gods",
    "service": "tjänst",
}


class PlanError(ValueError):
    """The file cannot be read as a plan. The message is for the person who added it."""


# --- Reading the file --------------------------------------------------------------------------


def load(data: bytes) -> dict[str, Any]:
    """The file as a JSON object. Gzip is unpacked; anything but an object is not a plan."""
    if data[:2] == b"\x1f\x8b":
        data = _unpack(data)
    if len(data) > MAX_BYTES:
        raise PlanError(f"Filen är större än {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise PlanError("Filen går inte att läsa som JSON.") from error
    if not isinstance(value, dict):
        raise PlanError("JSON-filen är inte ett objekt.")
    return value


def _unpack(data: bytes) -> bytes:
    """Gzip unpacked, never past the size limit."""
    unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        unpacked = unpacker.decompress(data, MAX_BYTES + 1)
    except zlib.error as error:
        raise PlanError("Filen är packad men går inte att packa upp.") from error
    if unpacker.unconsumed_tail:
        raise PlanError(f"Filen är större än {MAX_BYTES // (1024 * 1024)} MB.")
    return unpacked


class _Plan:
    """The plan's objects with the references resolved."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.ids: dict[str, dict[str, Any]] = {}
        self.problems: list[str] = []
        references: set[str] = set()
        stack: list[Any] = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if isinstance(item.get("$id"), str):
                    if item["$id"] in self.ids:
                        self.problems.append(f"objekt-id {item['$id']} finns flera gånger")
                    self.ids[item["$id"]] = item
                if "$ref" in item:
                    references.add(str(item["$ref"]))
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
        missing = sorted(references - self.ids.keys())
        self.problems.extend(f"objektreferensen {ref} saknas" for ref in missing)

    def resolve(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                return self.ids.get(str(value["$ref"]), {})
            if "$values" in value:
                values = value["$values"]
                return values if isinstance(values, list) else []
        return value

    def get(self, item: Any, key: str) -> Any:
        return self.resolve(item.get(key)) if isinstance(item, dict) else None

    def items(self, item: Any, key: str) -> list[dict[str, Any]]:
        value = self.get(item, key)
        if not isinstance(value, list):
            return []
        return [found for entry in value if isinstance(found := self.resolve(entry), dict)]


def problem(data: dict[str, Any]) -> str:
    """What keeps the file from being the planning program's plan, or empty when it is one."""
    plan = _Plan(data)
    timetable = plan.get(data, "Timetable")
    layout = plan.get(timetable, "Layout") if isinstance(timetable, dict) else None
    if not isinstance(layout, dict):
        return "Timetable.Layout saknas"
    if not isinstance(plan.get(layout, "OperationLocations"), list):
        return "banans driftplatser (OperationLocations) saknas"
    if not isinstance(plan.get(timetable, "Trains"), list):
        return "tågen (Timetable.Trains) saknas"
    if plan.problems:
        return "; ".join(plan.problems[:5])
    return ""


# --- Small readers -----------------------------------------------------------------------------


def _text(value: Any) -> str:
    return "" if value is None or isinstance(value, (dict, list)) else " ".join(str(value).split())


def _int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def clock(value: Any) -> str | None:
    """HH:MM from "06:20:00" or "1.00:05:00", where the number before the dot is days."""
    match = _CLOCK.fullmatch(_text(value))
    if not match or int(match.group(2)) > 23 or int(match.group(3)) > 59:
        return None
    return f"{int(match.group(2)):02d}:{match.group(3)}"


def day(value: Any) -> int:
    """The days before the time: 1 for "1.00:05:00", otherwise 0."""
    match = _CLOCK.fullmatch(_text(value))
    return int(match.group(1)) if match and match.group(1) else 0


def weekdays(sessions: Any) -> list[Weekday]:
    """The weekdays of the program's two-week session mask, Monday first; empty without days."""
    mask = _int(sessions)
    if mask <= 0:
        return []
    week = (mask | (mask >> 7)) & WEEK
    return [weekday for bit, weekday in enumerate(WEEKDAYS) if week >> bit & 1]


def split_languages(text: str, default: str) -> dict[str, str]:
    """A text with language lines like [se] and [da], split per language. Text before the
    first marker, after a closing [/se] or without markers goes under the default."""
    parts: dict[str, list[str]] = {}
    current = default
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        marker = _MARKER.match(line)
        if marker and marker.group(2).lower() in _MARKERS:
            current = default if marker.group(1) else _MARKERS[marker.group(2).lower()]
            continue
        if _EMPTY_ELEMENT.match(line):
            continue
        parts.setdefault(current, []).append(line)
    return {
        language: joined
        for language, lines in parts.items()
        if (joined := "\n".join(lines).strip())
    }


def _languages(text: Any, default: str) -> dict[Language, str]:
    found = split_languages(str(text or ""), default)
    return {Language(language): value for language, value in found.items()}


def _plain(value: Any, limit: int = 500) -> str:
    """Text for a Text field: one line, within its limit."""
    return _text(value)[:limit].strip()


# --- The import --------------------------------------------------------------------------------


@dataclass
class _Reading:
    """Everything gathered while reading, before the package is put together."""

    source: Source
    facts: list[Fact] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)

    def origin(self, at: str) -> Origin:
        return Origin(source=self.source.id, at=at)

    def fact(self, ref: str, at: str, note: str | None = None) -> None:
        self.facts.append(
            Fact(ref=ref, certainty=Certainty.SURE, origins=[self.origin(at)], note=note)
        )


def read(data: bytes, *, meet: Meet, source: Source) -> ImportResult:
    """Stefan's planning file as a draft for the meet. Raises PlanError when it is not a plan."""
    plan_data = load(data)
    found = problem(plan_data)
    if found:
        raise PlanError("Filen är inte planeringsprogrammets plan: " + found + ".")
    return _Importer(plan_data, meet, source).run()


class _Importer:
    def __init__(self, data: dict[str, Any], meet: Meet, source: Source) -> None:
        self.data = data
        self.meet = meet
        self.plan = _Plan(data)
        self.timetable: dict[str, Any] = self.plan.get(data, "Timetable") or {}
        self.layout: dict[str, Any] = self.plan.get(self.timetable, "Layout") or {}
        self.reading = _Reading(source)
        self.language = str(COUNTRY_LANGUAGE.get(meet.country, Language.SV))
        self.locations: dict[Any, dict[str, Any]] = {}
        self.tracks: dict[Any, tuple[dict[str, Any], str]] = {}
        self.place_ids: dict[Any, str] = {}
        self.places: list[Place] = []
        self.categories: dict[Any, dict[str, Any]] = {}
        self.companies: dict[Any, dict[str, Any]] = {}
        self.call_ids: dict[Any, tuple[str, str]] = {}

    # The order matters: places, then sections, then trains, then what points at trains.
    def run(self) -> ImportResult:
        self._read_places()
        sections = self._sections()
        self.categories = {
            category["Id"]: category
            for category in self.plan.items(self.timetable, "TrainCategories")
            if category.get("Id") is not None
        }
        self.companies = {
            company["Id"]: company
            for company in self.plan.items(self.layout, "Companies")
            if company.get("Id") is not None
        }
        trains, shunting = self._trains()
        duties = self._duties()
        turns = self._turns({train.id for train in trains})
        rules, questions = self._rulebook(trains)
        traffic_week, clock_settings, first, last = self._settings()
        meet = self.meet.model_copy(
            update={
                "traffic_week": traffic_week,
                "first_date": self.meet.first_date or first,
                "last_date": self.meet.last_date or last,
            }
        )
        if (first, last) != (None, None) and (self.meet.first_date, self.meet.last_date) not in (
            (None, None),
            (first, last),
        ):
            self.reading.notes.append(
                f"Filen gäller {_dates(first, last)}; träffens datum "
                f"{_dates(self.meet.first_date, self.meet.last_date)} står kvar."
            )
        try:
            package = MeetPackage(
                meet=meet,
                clock=clock_settings,
                places=self.places,
                sections=sections,
                trains=trains,
                duties=duties,
                turns=turns,
                shunting=shunting,
                about=self._about(),
            )
        except ValidationError as error:
            raise PlanError(f"Planen gick inte att föra in: {error.errors()[0]['msg']}") from error
        counts: dict[PlaceKind, int] = defaultdict(int)
        for place in self.places:
            counts[place.kind] += 1
        report = ImportReport(
            source=self.reading.source.id,
            level=LEVEL,
            places={kind: counts[kind] for kind in PlaceKind if counts[kind]},
            sections=len(sections),
            parts=sum(len(section.parts) for section in sections),
            trains=len(trains),
            calls=sum(len(train.calls) for train in trains),
            duties=len(duties),
            turns=len(turns),
            shunting=len(shunting),
            train_types=len(rules.train_types),
            notes=list(dict.fromkeys(self.reading.notes)),
            left_out=list(dict.fromkeys(self.reading.left_out)),
        )
        return ImportResult(
            package=package,
            facts=self.reading.facts,
            rulebook=rules,
            questions=questions,
            report=report,
        )

    # --- Places ------------------------------------------------------------------------------

    def _read_places(self) -> None:
        for location in self.plan.items(self.layout, "OperationLocations"):
            if location.get("Id") is None or not _text(location.get("Name")):
                continue
            self.locations[location["Id"]] = location
            self.place_ids[location["Id"]] = f"p{_id(location['Id'])}"
            for track in self.plan.items(location, "Tracks"):
                if track.get("Id") is not None:
                    self.tracks[track["Id"]] = (location, _text(track.get("Number")))
        if not self.locations:
            raise PlanError("Planen har inga driftplatser.")
        ends, inside = self._dispatch_ends()
        for location in self.locations.values():
            self.places.append(self._place(location, ends, inside))

    def _dispatch_ends(self) -> tuple[set[Any], dict[Any, str]]:
        """The places that end a clearance section, and those only inside one (with its name)."""
        ends: set[Any] = set()
        inside: dict[Any, str] = {}
        for stretch in self.plan.items(self.layout, "DispatchStretches"):
            start, end = self.plan.get(stretch, "From"), self.plan.get(stretch, "To")
            if not isinstance(start, dict) or not isinstance(end, dict):
                continue
            ends.update((start.get("Id"), end.get("Id")))
            name = f"{_text(start.get('Name'))}–{_text(end.get('Name'))}"
            for part in self.plan.items(stretch, "Stretches"):
                for key in ("StartId", "EndId"):
                    inside.setdefault(part.get(key), name)
        return ends, {place: name for place, name in inside.items() if place not in ends}

    def _place(self, location: dict[str, Any], ends: set[Any], inside: dict[Any, str]) -> Place:
        plan_id = location["Id"]
        place_id = self.place_ids[plan_id]
        name = _plain(location.get("Name"))
        code = _plain(location.get("Signature"), 40)
        at = f"OperationLocations Id {plan_id}"
        self.reading.fact(f"place:{place_id}", at)
        if not code:
            code = name
            self.reading.notes.append(f"{name} har ingen signatur i filen; namnet används.")
        controller = self.plan.get(location, "ControlledBy")
        controller_id = controller.get("Id") if isinstance(controller, dict) else None
        remote_from = self.place_ids.get(controller_id) if controller_id is not None else None
        kind_note: str | None = None
        if location.get("IsShadow"):
            kind = PlaceKind.SHADOW_YARD
        elif location.get("IsManned"):
            kind = PlaceKind.MANNED
        elif remote_from is not None and remote_from != place_id:
            kind = PlaceKind.REMOTE
        elif plan_id in inside:
            kind = PlaceKind.HALT
            kind_note = (
                f"Ligger inne i klareringssträckan {inside[plan_id]} och klarerar inte själv."
            )
            self.reading.notes.append(f"{name}: {kind_note[0].lower()}{kind_note[1:]}")
        elif _text(location.get("$type")) == "IndustrialArea":
            kind = PlaceKind.HALT
        else:
            kind = PlaceKind.UNMANNED
        self.reading.fact(f"place:{place_id}.kind", at, kind_note)
        tracks: list[PlanTrack] = []
        seen: set[str] = set()
        located = sorted(
            self.plan.items(location, "Tracks"), key=lambda t: _int(t.get("DisplayOrder"))
        )
        for track in located:
            label = _plain(track.get("Number"), 40)
            # Storage, terminal and yard tracks (IsScheduled false) are not the place's tracks.
            if not label or track.get("IsScheduled") is False:
                continue
            if label.casefold() in seen:
                self.reading.notes.append(
                    f"{name} har två spår som heter {label}; det första gäller."
                )
                continue
            seen.add(label.casefold())
            tracks.append(PlanTrack(name=label, sort_order=len(tracks)))
        phone = _plain(location.get("PhoneNumber"), 40) or None
        if phone:
            self.reading.fact(f"place:{place_id}.phone", at)
        return Place(
            id=place_id,
            code=code,
            name=name,
            kind=kind,
            remote_from=remote_from if kind == PlaceKind.REMOTE else None,
            phone=phone,
            tracks=tracks,
            instructions=_languages(location.get("Instructions"), self.language),
            source_ids={"planning_json": str(plan_id)},
        )

    # --- Sections ----------------------------------------------------------------------------

    def _sections(self) -> list[Section]:
        stretches = {
            stretch.get("Id"): stretch
            for stretch in self.plan.items(self.layout, "TrackStretches")
            if stretch.get("Id") is not None
        }
        used: set[Any] = set()
        sections: list[Section] = []
        pairs: set[frozenset[str]] = set()
        for dispatch in self.plan.items(self.layout, "DispatchStretches"):
            start, end = self.plan.get(dispatch, "From"), self.plan.get(dispatch, "To")
            a = self.place_ids.get(start.get("Id")) if isinstance(start, dict) else None
            b = self.place_ids.get(end.get("Id")) if isinstance(end, dict) else None
            plan_id = dispatch.get("Id")
            if a is None or b is None or a == b:
                self.reading.left_out.append(
                    f"Klareringssträckan med Id {plan_id} har ingen giltig början och ände."
                )
                continue
            if frozenset((a, b)) in pairs:
                self.reading.left_out.append(
                    f"Klareringssträckan {_pair(start, end)} finns två gånger; den första gäller."
                )
                continue
            pairs.add(frozenset((a, b)))
            section_id = f"d{_id(plan_id)}"
            at = f"DispatchStretches Id {plan_id}"
            parts_in = self.plan.items(dispatch, "Stretches")
            used.update(part.get("Id") for part in parts_in)
            parts = self._chain(a, b, parts_in)
            if parts is None:
                parts = []
                self.reading.notes.append(
                    f"Delsträckorna i {_pair(start, end)} går inte i följd och lästes inte."
                )
            counts = [_int(part.get("TracksCount")) for part in parts_in]
            double = bool(counts) and all(count >= 2 for count in counts)
            self.reading.fact(f"section:{section_id}", at)
            for part in parts:
                self.reading.fact(f"part:{part.id}", f"TrackStretches Id {part.id[1:]}")
            sections.append(
                Section(
                    id=section_id,
                    place_a=a,
                    place_b=b,
                    tracks=TrackKind.DOUBLE if double else TrackKind.SINGLE,
                    parts=parts,
                    source_ids={"planning_json": str(plan_id)},
                )
            )
        if not self.plan.items(self.layout, "DispatchStretches"):
            self.reading.notes.append(
                "Filen har inga klareringssträckor; Drift kan inte klarera några tåg."
            )
        outside = [
            _pair(self.locations.get(s.get("StartId")), self.locations.get(s.get("EndId")))
            for plan_id, s in stretches.items()
            if plan_id not in used
            and s.get("StartId") in self.locations
            and s.get("EndId") in self.locations
        ]
        if outside:
            self.reading.notes.append(
                f"{len(outside)} spårsträckor ligger utanför planens klareringssträckor och "
                f"klareras inte: {', '.join(outside)}."
            )
        return sections

    def _chain(self, a: str, b: str, stretches: list[dict[str, Any]]) -> list[SectionPart] | None:
        """The parts in order from a to b, or None when they do not follow on from each other."""
        left = list(stretches)
        current, parts = a, []
        while left:
            step = next(
                (
                    s
                    for s in left
                    if current
                    in {self.place_ids.get(s.get("StartId")), self.place_ids.get(s.get("EndId"))}
                ),
                None,
            )
            if step is None:
                return None
            left.remove(step)
            ends = (self.place_ids.get(step.get("StartId")), self.place_ids.get(step.get("EndId")))
            other = ends[1] if ends[0] == current else ends[0]
            if other is None:
                return None
            parts.append(
                SectionPart(id=f"s{_id(step.get('Id'))}", from_place=current, to_place=other)
            )
            current = other
        return parts if parts and current == b else None

    # --- Trains ------------------------------------------------------------------------------

    def _company(self, train: dict[str, Any], category: dict[str, Any] | None) -> str:
        company = self.companies.get(train.get("CompanyId")) or self.companies.get(
            (category or {}).get("CompanyId")
        )
        return _plain((company or {}).get("Signature"), 40)

    def _trains(self) -> tuple[list[Train], list[Shunting]]:
        sources = self.plan.items(self.timetable, "Trains")
        if not sources:
            raise PlanError("Planen har inga tåg.")
        if sum(len(self.plan.items(train, "Calls")) for train in sources) > MAX_CALLS:
            raise PlanError(f"Planen har fler än {MAX_CALLS} uppehåll.")
        trains: list[Train] = []
        shunting: list[Shunting] = []
        identities: dict[str, list[tuple[list[Weekday], str, str, int]]] = defaultdict(list)
        numbers: dict[str, int] = defaultdict(int)
        skipped_shunting_calls = 0
        for train in sources:
            category = self.categories.get(train.get("CategoryId"))
            number = _plain(train.get("Number"), 40)
            if category and category.get("IsShunting"):
                tasks = self._shunting(train, category, number)
                shunting.extend(tasks)
                skipped_shunting_calls += len(self.plan.items(train, "Calls")) - len(tasks)
                continue
            if not number:
                self.reading.left_out.append("Ett tåg utan nummer lästes inte.")
                continue
            days = weekdays(train.get("Sessions"))
            if not days:
                self.reading.left_out.append(f"Tåg {number} har inga trafikdagar i filen.")
                continue
            numbers[number] += 1
            plan_id = train.get("Id")
            train_id = (
                f"t{_id(plan_id)}" if plan_id is not None else f"n{_id(number)}-{numbers[number]}"
            )
            calls = self._calls(train, train_id, number)
            if len(calls) < 2:
                self.reading.left_out.append(f"Tåg {number} har färre än två uppehåll.")
                continue
            prefix = _plain((category or {}).get("Prefix"), 40)
            operator = self._company(train, category)
            at = f"Trains Id {plan_id}" if plan_id is not None else f"Trains, tåg {number}"
            self.reading.fact(f"train:{train_id}", at)
            route = f"{self._name(calls[0].place)}–{self._name(calls[-1].place)}"
            identities[number].append(
                (days, " ".join(p for p in (operator, prefix) if p), route, len(trains))
            )
            trains.append(
                Train(
                    id=train_id,
                    number=number,
                    train_type=prefix or None,
                    operator=operator or None,
                    days=days,
                    calls=calls,
                    source_ids={
                        key: str(value)
                        for key, value in (
                            ("planning_json", plan_id),
                            ("category", train.get("CategoryId")),
                        )
                        if value is not None
                    },
                )
            )
        if skipped_shunting_calls:
            self.reading.left_out.append(
                f"{skipped_shunting_calls} växlingsbesök pekar på ett spår som saknas."
            )
        if not trains:
            raise PlanError("Inget tåg i filen kunde kopplas till driftplatserna.")
        return self._separate(trains, identities), shunting

    def _name(self, place_id: str) -> str:
        return next((place.name for place in self.places if place.id == place_id), place_id)

    def _calls(self, train: dict[str, Any], train_id: str, number: str) -> list[Call]:
        ordered = sorted(self.plan.items(train, "Calls"), key=lambda c: _int(c.get("Sequence")))
        located: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for call in ordered:
            found = self.tracks.get(call.get("TrackId"))
            if found is None:
                self.reading.left_out.append(
                    f"Tåg {number}: ett uppehåll pekar på ett spår som saknas och lästes inte."
                )
                continue
            located.append((call, *found))
        last = len(located) - 1
        calls: list[Call] = []
        late_departures = 0
        for index, (call, location, track) in enumerate(located):
            plan_id = call.get("Id")
            call_id = (
                f"c{_id(plan_id)}"
                if plan_id is not None
                else f"{train_id}-{_int(call.get('Sequence'))}"
            )
            arrival, departure = clock(call.get("Arrival")), clock(call.get("Departure"))
            arrival_day, departure_day = day(call.get("Arrival")), day(call.get("Departure"))
            passage = 0 < index < last and arrival is not None and arrival == departure
            exchange = index in (0, last) or bool(call.get("IsArrival") or call.get("IsDeparture"))
            if index == 0:
                arrival, first_day = None, departure_day
            elif index == last:
                departure, first_day = None, arrival_day
            else:
                first_day = arrival_day if arrival is not None else departure_day
                if departure is not None and departure_day > first_day:
                    late_departures += 1
            notes = [
                text
                for note in self.plan.items(call, "Notes")
                if (text := _text(note.get("Text") or note.get("Note")))
            ]
            at = (
                f"Calls Id {plan_id}"
                if plan_id is not None
                else f"Tåg {number}, uppehåll {index + 1}"
            )
            self.reading.fact(f"call:{call_id}", at)
            self.call_ids[plan_id] = (train_id, call_id)
            calls.append(
                Call(
                    id=call_id,
                    place=self.place_ids[location["Id"]],
                    track=track or None,
                    arrival=arrival,
                    departure=departure,
                    day_offset=min(first_day, 7),
                    stops=not passage,
                    exchange=exchange or passage,
                    note=_plain(" ".join(notes)) or None,
                )
            )
        if late_departures:
            self.reading.notes.append(
                f"Tåg {number} går från ett uppehåll först nästa dygn; dygnet gäller ankomsten."
            )
        return calls

    def _shunting(
        self, train: dict[str, Any], category: dict[str, Any], number: str
    ) -> list[Shunting]:
        """A shunting category's calls, as shunting tasks at their places."""
        days = weekdays(train.get("Sessions"))
        label = " ".join(p for p in (self._company(train, category), number) if p) or "Växling"
        name = _plain(category.get("Name"))
        tasks: list[Shunting] = []
        for call in self.plan.items(train, "Calls"):
            found = self.tracks.get(call.get("TrackId"))
            if found is None:
                continue
            location, track = found
            start, end = clock(call.get("Arrival")), clock(call.get("Departure"))
            plan_id = call.get("Id")
            task_id = (
                f"v{_id(plan_id)}" if plan_id is not None else f"v{_id(number)}-{len(tasks) + 1}"
            )
            what = ", ".join(
                part
                for part in (
                    f"{start}–{end}" if start and end else start or "",
                    name,
                    f"spår {track}" if track else "",
                    _days_text(days),
                )
                if part
            )
            self.reading.fact(f"shunting:{task_id}", f"Trains Id {train.get('Id')}")
            tasks.append(
                Shunting(
                    id=task_id,
                    place=self.place_ids[location["Id"]],
                    name=label,
                    time=start,
                    description=what or None,
                )
            )
        return tasks

    def _separate(
        self, trains: list[Train], identities: dict[str, list[tuple[list[Weekday], str, str, int]]]
    ) -> list[Train]:
        """Trains that share a number on a day get a service_key each (F9): operator and
        abbreviation, and the route when that is not enough."""
        keys: dict[int, str] = {}
        shared: list[str] = []
        for number, uses in identities.items():
            clashing = {
                index
                for index, (days, *_rest) in enumerate(uses)
                for other, (other_days, *_more) in enumerate(uses)
                if other != index and set(days) & set(other_days)
            }
            if not clashing:
                continue
            shared.append(number)
            operators = [uses[index][1] for index in clashing]
            for index in clashing:
                _days, operator, route, position = uses[index]
                unique = operator and operators.count(operator) == 1
                keys[position] = operator if unique else " ".join(p for p in (operator, route) if p)
        if shared:
            self.reading.notes.append(
                f"{len(shared)} tågnummer delas av två tåg samma dag och hålls isär med bolag "
                f"och förkortning: {', '.join(sorted(shared, key=_number_order))}."
            )
        return [
            train.model_copy(update={"service_key": keys[index]}) if index in keys else train
            for index, train in enumerate(trains)
        ]

    # --- Duties and turns --------------------------------------------------------------------

    def _duties(self) -> list[Duty]:
        duties: list[Duty] = []
        empty = 0
        for duty in self.plan.items(self.data, "DriverDuties"):
            legs = list(self._legs(duty))
            plan_id = duty.get("Id")
            if not legs or plan_id is None:
                empty += 1
                continue
            duty_id = f"k{_id(plan_id)}"
            self.reading.fact(f"duty:{duty_id}", f"DriverDuties Id {plan_id}")
            name = _plain(duty.get("Identity"), 80) or str(plan_id)
            duties.append(Duty(id=duty_id, name=name, legs=legs))
        if empty:
            self.reading.left_out.append(f"{empty} köruppdrag har inga tåg i tidtabellen.")
        return duties

    def _legs(self, duty: dict[str, Any]) -> Iterator[DutyLeg]:
        for part in self.plan.items(duty, "Parts"):
            start = self.call_ids.get(part.get("FromId"))
            end = self.call_ids.get(part.get("ToId"))
            if start and end and start[0] == end[0]:
                yield DutyLeg(train=start[0], from_call=start[1], to_call=end[1])

    def _turns(self, known: set[str]) -> list[Turn]:
        turns: list[Turn] = []
        empty = 0
        for schedule in self.plan.items(self.data, "Schedules"):
            plan_id = schedule.get("Id")
            trains: list[str] = []
            for part in self.plan.items(schedule, "Parts"):
                found = self.call_ids.get(part.get("FromId"))
                if found and found[0] in known and found[0] not in trains:
                    trains.append(found[0])
            if plan_id is None or not trains:
                empty += 1
                continue
            turn_id = f"o{_id(plan_id)}"
            self.reading.fact(f"turn:{turn_id}", f"Schedules Id {plan_id}")
            name = _plain(schedule.get("Number"), 80) or str(plan_id)
            turns.append(Turn(id=turn_id, name=name, trains=trains))
        if empty:
            self.reading.left_out.append(f"{empty} omlopp har inga tåg i tidtabellen.")
        return turns

    # --- The rulebook ------------------------------------------------------------------------

    def _rulebook(self, trains: list[Train]) -> tuple[Rulebook, list[Question]]:
        """One rule per abbreviation the trains carry. The file's Content is the fact; where it
        is missing the rulebook decides; where both are silent, a question."""
        used = {train.source_ids.get("category") for train in trains}
        by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for category in self.categories.values():
            if str(category.get("Id")) not in used or category.get("IsShunting"):
                continue
            code = _plain(category.get("Prefix"), 40)
            if code:
                by_code[code].append(category)
            else:
                self.reading.notes.append(
                    f"Tågslaget {_plain(category.get('Name')) or category.get('Id')} har ingen "
                    "förkortning; tågen visas med bara numret."
                )
        rules: list[TrainTypeRule] = []
        questions: list[Question] = []
        for code, categories in sorted(by_code.items(), key=lambda item: rulebook.key(item[0])):
            names = list(dict.fromkeys(n for c in categories if (n := _plain(c.get("Name")))))
            origins = [
                self.reading.origin(f"TrainCategories Id {category.get('Id')}")
                for category in categories
            ]
            contents = {CONTENT.get(_int(category.get("Content"))) for category in categories}
            given = {content for content in contents if content is not None}
            if len(given) > 1:
                questions.append(self._content_question(code, categories))
                rules.append(
                    TrainTypeRule(
                        code=code, names=names, certainty=Certainty.UNSURE, origins=origins
                    )
                )
                continue
            if given and None not in contents:
                content = given.pop()
                rules.append(
                    TrainTypeRule(
                        code=code,
                        names=names,
                        content=content,
                        certainty=Certainty.SURE,
                        origins=origins,
                    )
                )
                continue
            known = rulebook.known(code)
            if known is not None and (not given or given == {known.content}):
                rules.append(
                    known.model_copy(update={"names": names, "origins": [*origins, *known.origins]})
                )
                continue
            questions.append(self._content_question(code, categories))
            rules.append(
                TrainTypeRule(code=code, names=names, certainty=Certainty.UNSURE, origins=origins)
            )
        for rule in rules:
            self.reading.facts.append(
                Fact(ref=f"train_type:{rule.code}", certainty=rule.certainty, origins=rule.origins)
            )
        return Rulebook(train_types=rules), questions

    def _content_question(self, code: str, categories: list[dict[str, Any]]) -> Question:
        names = ", ".join(n for c in categories if (n := _plain(c.get("Name")))) or code
        return Question(
            id=f"train-type-{rulebook.key(code) or 'x'}",
            cause="train_type",
            message=f"Vad kör tågslaget {code} ({names})? Filen och regelboken säger inget.",
            refs=[f"train_type:{code}"],
            alternatives=[
                Alternative(
                    value=content,
                    label=CONTENT_WORD[content].capitalize(),
                    origins=[
                        self.reading.origin(f"TrainCategories Id {category.get('Id')}")
                        for category in categories
                        if CONTENT.get(_int(category.get("Content"))) == content
                    ],
                )
                for content in ("passengers", "goods", "service")
            ],
        )

    # --- Settings and texts ------------------------------------------------------------------

    def _settings(self) -> tuple[TrafficWeek, Clock, date | None, date | None]:
        settings = self.plan.get(self.layout, "Settings") or {}
        general = self.plan.get(settings, "General") or {}
        speed_settings = self.plan.get(settings, "TimeAndSpeed") or {}
        at = "Layout.Settings"
        start = clock(general.get("FirstSessionStartTime"))
        if start is None:
            start = "06:00"
            self.reading.notes.append(
                "Filen anger ingen starttid för klockan; 06:00 tills du ändrar."
            )
        else:
            self.reading.fact("clock.start_time", at)
        speed = _float(speed_settings.get("FastClockSpeed"))
        if 0 < speed <= 60:
            self.reading.fact("clock.speed", at)
        else:
            speed = 1.0
            self.reading.notes.append("Filen anger ingen klockhastighet; 1× tills du ändrar.")
        first_weekday = _int(general.get("StartDay"))
        sessions = _int(general.get("MaxSessions"))
        week = TrafficWeek(
            start_weekday=WEEKDAYS[first_weekday - 1] if 1 <= first_weekday <= 7 else Weekday.MON,
            days=sessions if 1 <= sessions <= 31 else 1,
            runs_over_midnight=general.get("RunsOverMidnight") is True,
        )
        self.reading.fact("meet.traffic_week", at)
        dates = [_date(general.get(key)) for key in ("ValidFrom", "ValidTo")]
        return week, Clock(start_time=start, speed=speed), dates[0], dates[1]

    def _about(self) -> dict[Language, About]:
        instructions = _languages(self.data.get("GeneralInstructions"), self.language)
        program = _languages(self.data.get("Program"), self.language)
        about: dict[Language, About] = {}
        for language in dict.fromkeys([*instructions, *program]):
            about[language] = About(
                instructions=instructions.get(language), program=program.get(language)
            )
        return about


# --- Helpers -----------------------------------------------------------------------------------


def _id(value: Any) -> str:
    """The plan's id as part of an id: letters and digits only."""
    text = re.sub(r"[^A-Za-z0-9]", "", _text(value))
    return text[:60] or "x"


def _pair(start: Any, end: Any) -> str:
    def name(place: Any) -> str:
        return _text(place.get("Name") if isinstance(place, dict) else None) or "?"

    return f"{name(start)}–{name(end)}"


def _float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError:
        return None


def _dates(first: date | None, last: date | None) -> str:
    if first is None and last is None:
        return "utan datum"
    if first == last or last is None:
        return str(first)
    return f"{first or '?'}–{last}"


DAY_NAMES: Final = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"]


def _days_text(days: list[Weekday]) -> str:
    if not days or len(days) == 7:
        return "Dagl"
    indexes = [WEEKDAYS.index(d) for d in days]
    if indexes == list(range(indexes[0], indexes[-1] + 1)) and len(indexes) > 2:
        return f"{DAY_NAMES[indexes[0]]}–{DAY_NAMES[indexes[-1]]}"
    return ", ".join(DAY_NAMES[i] for i in indexes)


def _number_order(number: str) -> tuple[int, str]:
    return (int(number), number) if number.isdigit() else (1 << 30, number)
