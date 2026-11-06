"""trainmeet.meet/1: the meet package. Everything needed to run a meet, in one package.

Built on the old Server's schema 3, made plain (spec 5.1 with the decisions of 4 November):
- The package is built on places (driftplatser) from the plan. Sections, calls and the
  protocols point at the place (H29). A station from TKL is coupled to a place, either
  in advance (its outside pinned here) or when it connects at the meet (H25, H28).
- The telephone number is a field on the place: the meet's game number, not personal data (H30).
- A call keeps the plan's track name. A table per place translates it to the station's
  track id when a station is coupled (H27, TKL14).
- US meets are not part of this format (F26).

Synk stores a published package as a frozen version with its checksum (common.checksum).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, model_validator

from contracts.common import Contract, Id, Language, Side, Text, TimeOfDay, Weekday
from contracts.station_outside import StationOutside

FORMAT: Final = "trainmeet.meet/1"


class ClearanceMode(StrEnum):
    """Klareringsläge. Requested: the receiving place answers. Direct: Drift answers at once
    if the section is free. The meet has one; a section may have the other (decided 1 Nov)."""

    REQUESTED = "requested"
    DIRECT = "direct"


class PlaceKind(StrEnum):
    """Platstyp (F2). Set from the plan; Drift may change manned/unmanned during the meet."""

    MANNED = "manned"  # bemannad: own box or TKL, clears trains
    REMOTE = "remote"  # fjärrstyrd: run from another place, named in remote_from
    UNMANNED = "unmanned"  # obemannad: the automation runs it
    SHADOW_YARD = "shadow_yard"  # skuggbangård: trains start and end here
    HALT = "halt"  # industri/hållplats: along a section, no clearance


class TrackKind(StrEnum):
    SINGLE = "single"
    DOUBLE = "double"


class Severity(StrEnum):
    """A published package carries no structural errors: those stop publishing."""

    CONFLICT = "conflict"
    OBSERVATION = "observation"


class AttachmentKind(StrEnum):
    CLOCK_FACE = "clock_face"  # urtavla, a .tmclock clock pack (F13)
    SKETCH = "sketch"  # träffskiss
    OVERVIEW = "overview"  # banöversiktens bild
    OTHER = "other"


# --- The meet ------------------------------------------------------------------------------


class TrafficWeek(Contract):
    """The planner's default game week (F8). Drift suggests it; the dispatcher may pick another."""

    start_weekday: Weekday = Weekday.MON
    days: int = Field(default=1, ge=1, le=31, description="Antal speldygn, Dag 1…N.")
    runs_over_midnight: bool = False


class Meet(Contract):
    id: Id
    name: Text
    country: Literal["se", "dk", "no", "de"] = "se"
    timezone: Text = "Europe/Stockholm"
    first_date: date | None = None
    last_date: date | None = None
    traffic_week: TrafficWeek = Field(default_factory=TrafficWeek)
    clearance_mode: ClearanceMode = ClearanceMode.REQUESTED
    settings: dict[str, object] = Field(
        default_factory=dict,
        description="Inställningarna i paketet (en av tre högar, T3). Fylls på när de byggs.",
    )


class Clock(Contract):
    start_time: TimeOfDay = Field(description="Modelltiden när klockan startar.")
    speed: float = Field(default=1.0, gt=0, le=60, description="Modellminuter per minut.")
    styles: list[Text] = Field(
        default_factory=lambda: ["analog"],
        description="Klockans stilar: analog, digital eller custom:<urtavlans id>.",
    )
    stop_reasons: list[Text] = Field(default_factory=list, description="Stoppskälen.")
    faces: list[Id] = Field(default_factory=list, description="Urtavlorna, som bilagor (F13).")


class Attachment(Contract):
    """A file the package carries, beside the package, with its own checksum."""

    id: Id
    kind: AttachmentKind
    filename: Text
    media_type: Text
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


# --- Places, stations and sections ----------------------------------------------------------


class PlanTrack(Contract):
    name: Text = Field(description="Spårets namn i planen, som tågbesöken använder.")
    sort_order: int = 0


class DefaultTrack(Contract):
    """Standard track per train type and direction at a place (B4)."""

    track: Text
    train_type: Text | None = Field(default=None, description="Tomt betyder alla tågslag.")
    towards: Side | None = Field(default=None, description="Tomt betyder båda riktningarna.")


class CoupledStation(Contract):
    """A station coupled to the place in advance: its outside pinned to a version (H28)."""

    station_id: Id
    version: int = Field(ge=1, description="Versionen av stationspaketet som gäller.")
    outside: StationOutside
    track_map: dict[Text, Id] = Field(
        default_factory=dict, description="Planens spårnamn → stationens spår-id."
    )
    exit_map: dict[Id, Id] = Field(
        default_factory=dict, description="Sträckans id → stationens utfart (H26)."
    )


class Place(Contract):
    """Driftplats: a place from the plan. Sections, calls and protocols point here."""

    id: Id
    code: Text = Field(description="Signaturen, till exempel Nby.")
    name: Text
    kind: PlaceKind
    remote_from: Id | None = Field(default=None, description="Driftplatsen som fjärrstyr.")
    phone: Text | None = Field(default=None, description="Träffens leknummer (H30).")
    aliases: list[Text] = Field(default_factory=list)
    tracks: list[PlanTrack] = Field(default_factory=list)
    default_tracks: list[DefaultTrack] = Field(default_factory=list)
    station: CoupledStation | None = None
    instructions: dict[Language, str] = Field(default_factory=dict)
    source_ids: dict[str, str] = Field(
        default_factory=dict, description="Planens käll-id:n, till exempel för Tellurian."
    )


class SectionPart(Contract):
    """Delsträcka: the physical piece between two places, for map, graph and detection."""

    id: Id
    from_place: Id
    to_place: Id


class Section(Contract):
    """Sträcka: the plan's clearance section between two places that clear to each other (F1).
    A train gets clearance once for the whole section, even past halts along it."""

    id: Id
    place_a: Id
    place_b: Id
    tracks: TrackKind = TrackKind.SINGLE
    clearance_mode: ClearanceMode | None = Field(
        default=None, description="Bara om sträckan avviker från träffens grundläge."
    )
    side_at_a: Side | None = Field(default=None, description="Sidan vid place_a (F3).")
    side_at_b: Side | None = Field(default=None, description="Sidan vid place_b (F3).")
    parts: list[SectionPart] = Field(
        default_factory=list, description="Delsträckorna i ordning från place_a till place_b."
    )
    source_ids: dict[str, str] = Field(default_factory=dict)


# --- Trains -------------------------------------------------------------------------------------


class Call(Contract):
    """Tågbesök: what Drift keeps track of. A train number alone is never a key (A1)."""

    id: Id
    place: Id
    track: Text | None = Field(default=None, description="Planens spårnamn.")
    arrival: TimeOfDay | None = None
    departure: TimeOfDay | None = None
    day_offset: int = Field(default=0, ge=0, le=7, description="Speldygn efter tågets första.")
    stops: bool = Field(default=True, description="Falskt för ej uppehåll.")
    exchange: bool = Field(
        default=True, description="Falskt för uppehåll utan utbyte: tåget står men lastar inte."
    )
    note: Text | None = None


class Train(Contract):
    id: Id
    number: Text = Field(description="Tågnumret, för inmatning och visning.")
    service_key: Text | None = Field(
        default=None, description="Håller isär två tåg med samma nummer samma dag (F9)."
    )
    train_type: Text | None = Field(default=None, description="Tågslaget.")
    operator: Text | None = None
    days: list[Weekday] = Field(min_length=1, description="Trafikdagarna.")
    manual: bool = Field(default=False, description="Körs manuellt (F10).")
    calls: list[Call] = Field(min_length=1)
    note: Text | None = None
    source_ids: dict[str, str] = Field(default_factory=dict)


class DutyLeg(Contract):
    train: Id
    from_call: Id
    to_call: Id


class Duty(Contract):
    """Köruppdrag. Stored from the start (F23); Lokföraren uses them from step 7."""

    id: Id
    name: Text
    legs: list[DutyLeg] = Field(default_factory=list)


class Turn(Contract):
    """Omlopp: the trains one set of vehicles runs, in order."""

    id: Id
    name: Text
    trains: list[Id] = Field(default_factory=list)


class Shunting(Contract):
    """Växlingsuppdrag at a place."""

    id: Id
    place: Id
    name: Text
    time: TimeOfDay | None = None
    description: str | None = None


# --- Display, about and findings -----------------------------------------------------------


class GraphPage(Contract):
    id: Id
    name: Text
    places: list[Id] = Field(min_length=2)


class Display(Contract):
    graph_order: list[Id] = Field(default_factory=list, description="Platserna i grafen.")
    graph_pages: list[GraphPage] = Field(default_factory=list)


class About(Contract):
    title: Text | None = None
    description: str | None = None
    instructions: str | None = None
    program: str | None = Field(default=None, description="Träffens program, som fasta tider.")


class Finding(Contract):
    """From the traffic check (Planering): shown, but does not stop publishing."""

    id: Id
    severity: Severity
    code: Text
    message: Text
    refs: list[Id] = Field(default_factory=list)


# --- The package ---------------------------------------------------------------------------


class MeetPackage(Contract):
    format: Literal["trainmeet.meet/1"] = FORMAT
    meet: Meet
    clock: Clock
    attachments: list[Attachment] = Field(default_factory=list)
    places: list[Place] = Field(min_length=1)
    sections: list[Section] = Field(default_factory=list)
    trains: list[Train] = Field(default_factory=list)
    duties: list[Duty] = Field(default_factory=list)
    turns: list[Turn] = Field(default_factory=list)
    shunting: list[Shunting] = Field(default_factory=list)
    display: Display = Field(default_factory=Display)
    about: dict[Language, About] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> MeetPackage:
        problems = _structural_problems(self)
        if problems:
            raise ValueError(" ".join(problems))
        return self


def _duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in ids:
        (repeated if value in seen else seen).add(value)
    return sorted(repeated)


def _structural_problems(package: MeetPackage) -> list[str]:
    """Structural errors: a package with any of these cannot be published (spec 4.1)."""
    problems: list[str] = []
    places = {p.id: p for p in package.places}
    sections = {s.id: s for s in package.sections}
    calls = {c.id: (t.id, c) for t in package.trains for c in t.calls}
    attachments = {a.id for a in package.attachments}

    for label, ids in (
        ("driftplatser", [p.id for p in package.places]),
        ("sträckor", [s.id for s in package.sections]),
        ("delsträckor", [part.id for s in package.sections for part in s.parts]),
        ("tåg", [t.id for t in package.trains]),
        ("tågbesök", [c.id for t in package.trains for c in t.calls]),
        ("köruppdrag", [d.id for d in package.duties]),
        ("omlopp", [t.id for t in package.turns]),
        ("växlingsuppdrag", [s.id for s in package.shunting]),
        ("bilagor", [a.id for a in package.attachments]),
    ):
        for dup in _duplicates(ids):
            problems.append(f"Två {label} har id {dup}.")

    def place_ref(ref: str, where: str) -> None:
        if ref not in places:
            problems.append(f"{where} pekar på en okänd driftplats: {ref}.")

    for place in package.places:
        if place.kind == PlaceKind.REMOTE:
            if place.remote_from is None:
                problems.append(f"Driftplatsen {place.id} är fjärrstyrd men saknar remote_from.")
            elif place.remote_from == place.id:
                problems.append(f"Driftplatsen {place.id} kan inte fjärrstyra sig själv.")
        if place.remote_from is not None:
            place_ref(place.remote_from, f"Driftplatsen {place.id}")
        names = [t.name for t in place.tracks]
        for dup in _duplicates([n.casefold() for n in names]):
            problems.append(f"Driftplatsen {place.id} har två spår som heter {dup}.")
        known = set(names)
        for default in place.default_tracks:
            if known and default.track not in known:
                problems.append(f"Standardspåret {default.track} finns inte på {place.id}.")
        if place.station is not None:
            station_tracks = {t.id for t in place.station.outside.tracks}
            station_exits = {e.id for e in place.station.outside.exits}
            if place.station.station_id != place.station.outside.station_id:
                problems.append(f"Stationen vid {place.id} och dess utsida har olika id.")
            for plan_name, track_id in place.station.track_map.items():
                if known and plan_name not in known:
                    problems.append(f"Spårtabellen vid {place.id} har okänt planspår {plan_name}.")
                if track_id not in station_tracks:
                    problems.append(f"Spårtabellen vid {place.id} pekar på okänt spår {track_id}.")
            for section_id, exit_id in place.station.exit_map.items():
                if section_id not in sections:
                    problems.append(
                        f"Utfartstabellen vid {place.id} har okänd sträcka {section_id}."
                    )
                if exit_id not in station_exits:
                    problems.append(f"Utfartstabellen vid {place.id} har okänd utfart {exit_id}.")

    for section in package.sections:
        where = f"Sträckan {section.id}"
        place_ref(section.place_a, where)
        place_ref(section.place_b, where)
        if section.place_a == section.place_b:
            problems.append(f"{where} börjar och slutar på samma driftplats.")
        if section.parts:
            chain = [section.parts[0].from_place] + [p.to_place for p in section.parts]
            linked = all(
                a.to_place == b.from_place
                for a, b in zip(section.parts, section.parts[1:], strict=False)
            )
            if not linked or chain[0] != section.place_a or chain[-1] != section.place_b:
                problems.append(f"{where}: delsträckorna går inte i följd från a till b.")
            for ref in chain:
                place_ref(ref, f"En delsträcka i {section.id}")

    for train in package.trains:
        for call in train.calls:
            where = f"Tåg {train.number} ({train.id})"
            if call.place not in places:
                place_ref(call.place, where)
                continue
            known = {t.name for t in places[call.place].tracks}
            if call.track is not None and known and call.track not in known:
                problems.append(f"{where} har spår {call.track} som inte finns på {call.place}.")

    for duty in package.duties:
        for leg in duty.legs:
            for ref in (leg.from_call, leg.to_call):
                if ref not in calls or calls[ref][0] != leg.train:
                    problems.append(f"Köruppdraget {duty.id} pekar på ett okänt tågbesök {ref}.")
    train_ids = {t.id for t in package.trains}
    for turn in package.turns:
        for ref in turn.trains:
            if ref not in train_ids:
                problems.append(f"Omloppet {turn.id} pekar på ett okänt tåg {ref}.")
    for task in package.shunting:
        place_ref(task.place, f"Växlingsuppdraget {task.id}")
    for ref in package.display.graph_order:
        place_ref(ref, "Grafens ordning")
    for page in package.display.graph_pages:
        for ref in page.places:
            place_ref(ref, f"Grafsidan {page.id}")
    for face in package.clock.faces:
        if face not in attachments:
            problems.append(f"Urtavlan {face} finns inte bland bilagorna.")
    return problems
