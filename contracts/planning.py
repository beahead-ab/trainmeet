"""trainmeet.planning/1: Planering's meets, sources, draft, import and versions (steg 4a).

The import's principles (spec, trainmeet-hub-import.md 3, decided 2 November):
- Every fact in the draft carries its origin in a source and a certainty (principle 1).
- Code reads; train types and abbreviations go through one rulebook, and a missing rule is a
  question, never a guess (principles 2, 3 and 6).
- The same source always gives the same result (principle 7).

Stefan's planning file (JSON) is level 4, the key: everything in it is sure. Participants and
vehicle contributions in the file are personal data and never come into the meet.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from contracts.common import Contract, Id, Text
from contracts.meet import ClearanceMode, Finding, Meet, MeetPackage, PlaceKind

FORMAT: Final = "trainmeet.planning/1"
PLANNER: Final = "planner"
"""The origin of a change made by hand in Planering."""


class Certainty(StrEnum):
    """Säkerhet per faktum (import 6)."""

    SURE = "sure"  # säker: JSON or Access, or the same value in two independent sources
    LIKELY = "likely"  # trolig: one source read with code
    UNSURE = "unsure"  # osäker: transcribed by AI or derived, and not confirmed
    CONFIRMED = "confirmed"  # bekräftad: the planner approved it; counts as sure


class SourceKind(StrEnum):
    PLANNING_JSON = "planning_json"  # Stefans planeringsfil


class Source(Contract):
    """Underlag: a file added to the meet. Kept as it came, so it can be read again."""

    id: Id
    kind: SourceKind
    filename: Text
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    level: int = Field(ge=1, le=4, description="Underlagsnivån filen ger (import 4).")
    added: datetime


class Origin(Contract):
    source: Id = Field(description="Underlaget, eller planner för en ändring i Planering.")
    at: Text = Field(description="Var i underlaget, till exempel Trains Id 27.")


class Fact(Contract):
    """What the draft knows about one thing, where it comes from and how sure it is."""

    ref: Text = Field(
        description="Vad det gäller: place:p5, section:d16, train:t27, call:c161, "
        "eller ett fält som place:p5.phone."
    )
    certainty: Certainty
    origins: list[Origin] = Field(min_length=1)
    note: Text | None = Field(default=None, description="Hur en regel bestämde värdet.")


# --- The rulebook --------------------------------------------------------------------------

TrainContent = Literal["passengers", "goods", "service"]


class TrainTypeRule(Contract):
    """A train type in the rulebook: the abbreviation trains carry, and what it carries."""

    code: Text = Field(description="Förkortningen, som tågen visar den: Pt, X, RE.")
    names: list[Text] = Field(default_factory=list, description="Tågslagens namn i underlaget.")
    content: TrainContent | None = Field(
        default=None, description="Resande, gods eller tjänst. Tomt tills en regel finns."
    )
    certainty: Certainty
    origins: list[Origin] = Field(min_length=1)


class Rulebook(Contract):
    """Regelboken: the meet's train types. Read by every source; added to by the planner."""

    train_types: list[TrainTypeRule] = Field(default_factory=list)


# --- Questions and the report --------------------------------------------------------------


class Alternative(Contract):
    value: Text
    label: Text
    origins: list[Origin] = Field(default_factory=list)


class Question(Contract):
    """Asked only where a rule is missing or two equal sources disagree (import 3.6)."""

    id: Id
    cause: Text = Field(description="Orsaken, som frågorna grupperas efter.")
    message: Text
    refs: list[Text] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    answer: Text | None = None


class ImportReport(Contract):
    """Importrapporten: the level, what the source gave, what rules decided, what was left out."""

    source: Id
    level: int = Field(ge=1, le=4)
    places: dict[PlaceKind, int] = Field(default_factory=dict)
    sections: int = 0
    parts: int = 0
    trains: int = 0
    calls: int = 0
    duties: int = 0
    turns: int = 0
    shunting: int = 0
    train_types: int = 0
    notes: list[Text] = Field(
        default_factory=list, description="Vad reglerna bestämde, i klartext."
    )
    left_out: list[Text] = Field(
        default_factory=list, description="Det som inte lästes in, och varför."
    )


class ImportResult(Contract):
    """What an import gives Planering: the package, its facts, rules, questions and report."""

    package: MeetPackage
    facts: list[Fact] = Field(default_factory=list)
    rulebook: Rulebook = Field(default_factory=Rulebook)
    questions: list[Question] = Field(default_factory=list)
    report: ImportReport


# --- Meets, the draft and versions ---------------------------------------------------------


class NewMeet(Contract):
    """Ny träff: a name, the dates and the country."""

    name: Text
    first_date: date | None = None
    last_date: date | None = None
    country: Literal["se", "dk", "no", "de"] = "se"


class Draft(Contract):
    """Utkastet: what Planering works on until it is published as a version."""

    format: Literal["trainmeet.planning/1"] = FORMAT
    meet: Meet
    package: MeetPackage | None = Field(default=None, description="Tomt tills underlag finns.")
    facts: list[Fact] = Field(default_factory=list)
    rulebook: Rulebook = Field(default_factory=Rulebook)
    sources: list[Source] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    report: ImportReport | None = None


class Version(Contract):
    """A published version: frozen, never changed, never deleted (Ordlista)."""

    meet: Id
    number: int = Field(ge=1)
    published: datetime
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    conflicts: int = Field(default=0, ge=0)
    observations: int = Field(default=0, ge=0)


class MeetSummary(Contract):
    """A meet in the list: its draft at a glance and its versions."""

    meet: Meet
    level: int | None = Field(default=None, ge=1, le=4)
    places: int = 0
    trains: int = 0
    sources: int = 0
    questions: int = 0
    versions: list[Version] = Field(default_factory=list)


class PlaceChange(Contract):
    """A change to one place in the draft. Only the fields sent are changed."""

    place: Id
    phone: Text | None = None


class SectionChange(Contract):
    """A change to one section in the draft. Clearance mode empty follows the meet."""

    section: Id
    clearance_mode: ClearanceMode | None = None


class Check(Contract):
    """Trafikkontrollen of the draft: what publishing would carry in its findings."""

    findings: list[Finding] = Field(default_factory=list)
