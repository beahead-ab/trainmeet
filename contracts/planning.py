"""trainmeet.planning/1: Planering's meets, sources, draft, import and versions (steg 4a).

The import's principles (spec, trainmeet-hub-import.md 3, decided 2 November):
- Every fact in the draft carries its origin in a source and a certainty (principle 1).
- Code reads; train types and abbreviations go through one rulebook, and a missing rule is a
  question, never a guess (principles 2, 3 and 6).
- The same source always gives the same result (principle 7).

Tellurian's planning file (JSON) is level 4, the key: everything in it is sure. Participants and
vehicle contributions in the file are personal data and never come into the meet.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import Discriminator, Field, Tag

from contracts.common import Contract, Id, Language, Text, Weekday
from contracts.drift import DriftChange, ProposalStatus
from contracts.meet import (
    Attachment,
    ClearanceMode,
    Finding,
    MapPoint,
    Meet,
    MeetPackage,
    PlaceKind,
    TrackKind,
)
from contracts.station_outside import StationOutside

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
    PLANNING_JSON = "planning_json"  # Tellurians planeringsfil
    STATION_LISTS = "station_lists"  # Stationslistorna: ODT, Excel eller CSV (4c1)
    TRACK_PICTURE = "track_picture"  # Banbilden: Tellurians topologi-PDF (4c1)
    GRAPH_PICTURE = "graph_picture"  # Grafen som bild, avskriven av egen AI (4c2)
    STATION_OUTSIDE = "station_outside"  # Stationens utsida från TKL (IMPORT-10)
    CAD_ASSEMBLY = "cad_assembly"  # CAD:s anläggning (CAD-11, K4)


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


class ListVerdict(Contract):
    """Domen för en stationslista mot planeringsfilen (IMPORT-27): rad för rad."""

    document: Text = Field(description="Listans fil, till exempel Lek Lekby.odt.")
    place: Id | None = Field(default=None, description="Driftplatsen listan gäller, i planen.")
    rows: int = Field(ge=0, description="Listans rader, ett uppehåll på två rader räknat en gång.")
    agreeing: int = Field(ge=0, description="Rader som stämmer med planen.")
    differences: list[Text] = Field(
        default_factory=list, description="Det som skiljer, i klartext."
    )


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
    verdicts: list[ListVerdict] = Field(
        default_factory=list,
        description="Stationslistorna prövade mot planeringsfilen, en dom per lista (IMPORT-27).",
    )


class ImportResult(Contract):
    """What an import gives Planering: the package, its facts, rules, questions and report."""

    package: MeetPackage
    facts: list[Fact] = Field(default_factory=list)
    rulebook: Rulebook = Field(default_factory=Rulebook)
    questions: list[Question] = Field(default_factory=list)
    report: ImportReport
    checks_only: bool = Field(
        default=False,
        description=(
            "Underlaget prövas mot utkastet och ändrar det inte: stationslistorna mot "
            "planeringsfilen (IMPORT-27)."
        ),
    )


# --- Meets, the draft and versions ---------------------------------------------------------


class NewMeet(Contract):
    """Ny träff: a name, the dates and the country. Someone logged in with TrainMeet ID makes it
    from a meet in ID, where they are the club's admin or the organizer (ID10, #78)."""

    name: Text
    first_date: date | None = None
    last_date: date | None = None
    country: Literal["se", "dk", "no", "de"] = "se"
    id_meet: UUID | None = Field(
        default=None, description="Träffen i TrainMeet ID som träffen hör till (ID10)."
    )


class IdMeetChoice(Contract):
    """A meet in TrainMeet ID that the one logged in with ID may plan (ID10, PLAN-19): the
    club's admin or the organizer. hub_meet is the hub's meet already made from it, if any."""

    id: UUID
    name: Text
    club_name: Text
    starts_on: date
    ends_on: date
    hub_meet: Id | None = None


class Version(Contract):
    """A published version: frozen, never changed, never deleted (Ordlista)."""

    meet: Id
    number: int = Field(ge=1)
    published: datetime
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    conflicts: int = Field(default=0, ge=0)
    observations: int = Field(default=0, ge=0)
    withdrawn: datetime | None = Field(
        default=None,
        description="Tillbakadragen (PLAN-18): kan inte startas eller följas, men finns kvar.",
    )


class MeetSummary(Contract):
    """A meet in the list: its draft at a glance and its versions."""

    meet: Meet
    level: int | None = Field(default=None, ge=1, le=4)
    places: int = 0
    trains: int = 0
    sources: int = 0
    questions: int = 0
    versions: list[Version] = Field(default_factory=list)
    home: Text | None = Field(
        default=None,
        description="Molnhubben träffen följs från (SYNK-02): utkastet finns där, versionerna här.",
    )
    may_plan: bool = Field(
        default=False,
        description="Får den som frågar planera träffen? Hubbens PIN, eller Administratör eller "
        "Arrangör i TrainMeet ID (PLAN-19, #78).",
    )
    may_publish: bool = Field(
        default=False,
        description="Får den som frågar publicera träffens versioner? Hubbens PIN, "
        "Administratör, eller Arrangör med Får publicera på träffen i TrainMeet ID (PLAN-19, "
        "PLAN-24).",
    )
    may_withdraw: bool = Field(
        default=False,
        description="Får den som frågar dra tillbaka en version? Hubbens PIN eller "
        "Administratör i TrainMeet ID, som i gamla Cloud (PLAN-24).",
    )


class PlaceChange(Contract):
    """A change to one place in the draft. Only the fields sent are changed."""

    place: Id
    phone: Text | None = None


class StationChange(Contract):
    """Koppla en station till driftplatsen i förväg (PLAN-05): its outside is pinned in the
    next version (PLAN-11). Empty station: koppla bort."""

    place: Id
    station: Id | None = Field(description="Stationens id bland utkastets stationer, eller tomt.")


class StationVersion(Contract):
    """En stations utsida bland utkastets underlag (IMPORT-10). En ny utsida för samma station
    får nästa nummer; samma utsida igen ändrar inget (IMPORT-31)."""

    version: int = Field(ge=1)
    source: Id
    outside: StationOutside


class RemoteAreaChange(Contract):
    """Ett fjärrområde i utkastet (PLAN-04, PLAN-33, FR49): a name and a row of driftplatser that
    hangs together along the line. Each of them is planned as remote-controlled from the area;
    a place taken out of the area is manned again. No name takes the area away."""

    remote_area: Id
    name: Text | None = Field(default=None, description="Fjärrområdets namn, eller tomt.")
    places: list[Id] = Field(default_factory=list, max_length=100)


class SectionChange(Contract):
    """A change to one section in the draft. Clearance mode empty follows the meet."""

    section: Id
    clearance_mode: ClearanceMode | None = None


class TrainMeetAi(Contract):
    """TrainMeets AI genom mätaren (#79, TOKEN-28, TK12): offered in the cloud hub to someone
    logged in with TrainMeet ID. Egen AI is the first choice; before TrainMeets AI is used the
    planner is told where the pages go and who pays (TK16)."""

    payer: Text = Field(description="Vems saldo som betalar: klubbens, eller personens.")
    available: int = Field(ge=0, description="Det saldot har kvar nu.")
    price: int = Field(ge=0, description="12 tokens per sida som inte är avskriven (TOKEN-14).")
    where: Text = Field(
        default="Claude i Amazon Bedrock i Stockholm",
        description="Var sidorna läses (TK14), som sägs innan de skickas (TK12).",
    )
    own_ai: Text | None = Field(
        default=None,
        description="Den som betalar har egen AI på kontot (TOKEN-03): sidorna läses av den "
        "modellen, och inga tokens dras (TK4).",
    )


class AiPages(Contract):
    """Sidor att skriva av (IMPORT-05): what a scanned file needs before AI starts. Nothing is
    sent to the AI until the planner says Skriv av."""

    filename: Text
    pages: int = Field(ge=1)
    saved: int = Field(
        ge=0, description="Sidor som redan är avskrivna; de används igen och kostar inget."
    )
    model: Text | None = Field(
        default=None, description="Den egna AI:n som skriver av; tomt när ingen är inkopplad."
    )
    tokens: int = Field(
        default=0,
        ge=0,
        description="Ungefär så många tokens kostar sidorna som inte är avskrivna att skicka: "
        "bilderna och uppmaningen. Svaret kommer till.",
    )
    trainmeet_ai: TrainMeetAi | None = Field(
        default=None,
        description="TrainMeets AI som tillval, där den finns för den som frågar (#79).",
    )


class PictureLink(Contract):
    """A line on the track picture between two signatures: two side by side is double track."""

    a: Text
    b: Text
    double: bool = False


class TrackPicture(Contract):
    """Banbilden som bakgrund i Bana (PLAN-02): the signatures where the picture has them, in
    the same units as the draft's map (reference_layout), and the lines between them."""

    source: Id
    page: int = Field(ge=1)
    points: dict[Text, MapPoint] = Field(default_factory=dict)
    links: list[PictureLink] = Field(default_factory=list)
    photo: MapPoint | None = Field(
        default=None,
        description=(
            "En fotograferad banbild (4c2, IMPORT-17): bildens bredd och höjd i kartans "
            "enheter, från övre vänstra hörnet. Bilden hämtas från /picture/photo."
        ),
    )


class ConfirmChange(Contract):
    """Bekräfta (IMPORT-04, PLAN-02): the planner approves what a source gave, as it is. An
    osäker or trolig fact becomes bekräftad, which counts as säker."""

    confirm: Text = Field(description="Faktumets ref, till exempel section:s-gdo-r.")


class SectionTracksChange(Contract):
    """Enkel- eller dubbelspår for one section in the draft."""

    section: Id
    tracks: TrackKind


class CallChange(Contract):
    """One field of a tågbesök in the draft (PLAN-01): its arrival, its departure or its track.
    Empty clears it."""

    call: Id
    field: Literal["arrival", "departure", "track"]
    value: Text | None = None


class TrainChange(Contract):
    """One field of a train in the draft (PLAN-01): its number or its note. Empty clears the
    note; a train always has a number."""

    train: Id
    field: Literal["number", "note"]
    value: Text | None = None


class TrainDaysChange(Contract):
    """A train's days in the draft (PLAN-01)."""

    train: Id
    days: list[Weekday] = Field(min_length=1, max_length=7)


INSTRUCTIONS_MAX: Final = 20_000
"""The general instructions as text, in characters (PLAN-40)."""


class ClockChange(Contract):
    """En urtavla i utkastet, eller vilken stil den analoga klockan visar (F13, SKARM-05).

    add lägger in klockpaketet som bilaga. remove tar bort det och ställer tillbaka
    analog om den stilen visades. style väljer analog eller custom:<id>."""

    clock: Literal["add", "remove", "style"]
    face: Id | None = None
    attachment: Attachment | None = Field(
        default=None, description="Klockpaketet, sparat bredvid paketet med sin kontrollsumma."
    )
    style: str | None = Field(
        default=None, max_length=48, description="analog eller custom:<urtavlans id>."
    )


class ClockPackSeen(Contract):
    """Ett klockpaket i en fil, innan något sparas: förhandsvisningen och varningarna."""

    id: Id
    name: Text
    version: Text
    warnings: list[str] = Field(default_factory=list)
    replaces: bool = False
    unchanged: bool = False
    layers: dict[str, str] = Field(
        default_factory=dict, description="Lagren som data-adresser, för förhandsvisningen."
    )
    dark: dict[str, str] = Field(default_factory=dict)


class ClockCheck(Contract):
    """Vad en uppladdad fil innehåller, utan att något sparas."""

    packs: list[ClockPackSeen] = Field(default_factory=list)


class ClockStamp(Contract):
    """Intyget om rätten att använda tavlan: vem och när, utan personens namn."""

    id: Id
    name: Text
    filename: Text
    at: datetime
    by: Text = Field(description="pin, eller personens id i TrainMeet ID.")
    warnings: list[str] = Field(default_factory=list)


class ClockStamps(Contract):
    faces: list[ClockStamp] = Field(default_factory=list)


class ClockStyleChoice(Contract):
    """Vilken stil den analoga klockskärmen visar."""

    style: str = Field(max_length=48, description="analog eller custom:<urtavlans id>.")


class ClockRemove(Contract):
    face: Id


class InstructionsChange(Contract):
    """De allmänna instruktionerna som köruppdragen hänvisar till (PLAN-40, LOK-34, LF21): en
    text per språk, eller en PDF. De står i träffpaketet, texten i about och PDF:en som bilaga,
    och följer med nästa version till Drift och Lokföraren. Tomt tar bort."""

    instructions: Literal["text", "pdf"]
    language: Language = Field(default=Language.SV, description="Textens språk.")
    text: str | None = Field(default=None, max_length=INSTRUCTIONS_MAX)
    pdf: Attachment | None = Field(
        default=None, description="PDF:en, sparad bredvid paketet med sin kontrollsumma."
    )


def _change_kind(value: Any) -> str:
    """Which change it is, from its fields: a place, a section's tracks or its clearance, a
    call, a train's field or its days, the general instructions, or a remote area."""
    if isinstance(value, dict):
        for key, kind in (
            ("clock", "clock"),
            ("remote_area", "remote_area"),
            ("instructions", "instructions"),
            ("confirm", "confirm"),
            ("station", "station"),
            ("call", "call"),
            ("days", "days"),
            ("train", "train"),
            ("place", "place"),
            ("tracks", "tracks"),
        ):
            if key in value:
                return kind
        return "section"
    for model, kind in (
        (ClockChange, "clock"),
        (RemoteAreaChange, "remote_area"),
        (InstructionsChange, "instructions"),
        (ConfirmChange, "confirm"),
        (StationChange, "station"),
        (CallChange, "call"),
        (TrainDaysChange, "days"),
        (TrainChange, "train"),
        (PlaceChange, "place"),
        (SectionTracksChange, "tracks"),
    ):
        if isinstance(value, model):
            return kind
    return "section"


Change = Annotated[
    Annotated[ClockChange, Tag("clock")]
    | Annotated[PlaceChange, Tag("place")]
    | Annotated[SectionTracksChange, Tag("tracks")]
    | Annotated[SectionChange, Tag("section")]
    | Annotated[CallChange, Tag("call")]
    | Annotated[TrainChange, Tag("train")]
    | Annotated[TrainDaysChange, Tag("days")]
    | Annotated[ConfirmChange, Tag("confirm")]
    | Annotated[StationChange, Tag("station")]
    | Annotated[InstructionsChange, Tag("instructions")]
    | Annotated[RemoteAreaChange, Tag("remote_area")],
    Discriminator(_change_kind),
]


class Changes(Contract):
    """Several changes saved at once (Spara in Data). They are kept in order. They carry the
    draft's revision they were made against: one saved by someone else in between is refused,
    so that no change is written over in silence (PLAN-38)."""

    revision: int = Field(ge=0, description="Utkastets revision som ändringarna gjordes mot.")
    changes: list[Change] = Field(min_length=1, max_length=500)


class Proposal(Contract):
    """Förslag från Drift (4.4, PLAN-03): a driftändring made during the meet, for the next
    version. The planner takes it into the draft (Ta med) or rejects it (Avslå); Drift sees the
    answer."""

    id: Id = Field(description="Driftändringens id i Drift.")
    meet: Id
    version: int = Field(ge=1, description="Versionen som kördes när ändringen gjordes.")
    change: DriftChange
    train_number: Text | None = Field(default=None, description="Tågets nummer då.")
    made: datetime
    status: ProposalStatus = ProposalStatus.WAITING
    answered: datetime | None = None


class TakenChange(Contract):
    """A driftändring taken into the draft. It is laid on again when the sources are read
    again, after the planner's own changes."""

    id: Id
    change: DriftChange


class Answer(Contract):
    """The planner's answer to a question: one of its alternatives."""

    question: Id
    value: Text


# --- CAD:s anläggning som underlag (CAD-11, CAD-12, K4) -----------------------------------
#
# Integrationer reads the assembly CAD gave (trainmeet.cad-assembly/1, kept as it came) into its
# places and the tracks between them, in the model's mm. Planering lays it on the draft each time
# the draft is read again, as it couples the stations: a place in the assembly is a driftplats of
# the plan by its name or its station, or by the planner's answer; the tracks between two places
# give the section between them its length; and what differs is a question, never a silent
# change (CAD-30). The plan's places and sections stay the plan's: the Hub owns Bana (CAD-09).


class AssemblyPlace(Contract):
    """A place in the assembly: modules joined to each other that have a switch or are used by a
    station in TKL (Används i)."""

    id: Id = Field(description="Fast så länge platsens första modul är densamma.")
    name: Text = Field(description="Stationens namn, eller modulernas.")
    stations: list[Text] = Field(
        default_factory=list, description="Stationerna i TKL som använder modulerna."
    )
    station_ids: list[Id] = Field(
        default_factory=list, description="Samma stationer, med TKL:s egna id:n."
    )
    modules: list[Text] = Field(min_length=1, description="Modulerna, M-001 Namn.")
    at: MapPoint = Field(description="Platsens mitt i anläggningen, i mm.")
    switches: int = Field(default=0, ge=0)


class AssemblyLink(Contract):
    """The tracks between two places of the assembly through modules without switches, with
    their length along the track."""

    id: Id
    a: Id
    b: Id
    length: float = Field(ge=0, description="Längs spåret i modellen, i mm; medel över spåren.")
    tracks: int = Field(ge=1, description="Spår bredvid varandra.")
    modules: list[Text] = Field(default_factory=list, description="Modulerna emellan, i ordning.")


class AssemblyThrough(Contract):
    """Through a place, from one link to another: the shortest way along its tracks."""

    place: Id
    a: Id
    b: Id
    length: float = Field(ge=0, description="I modellen, i mm.")


class AssemblyLayout(Contract):
    """CAD:s anläggning som underlag (K4, CAD-11), as Integrationer read it."""

    source: Id
    assembly: UUID
    name: Text
    revision: int = Field(ge=1)
    scale: Text = Field(description="Skalan: H0, N eller 0.")
    ratio: float = Field(gt=0, description="Skalans förhållande: 87 för H0.")
    places: list[AssemblyPlace] = Field(default_factory=list)
    links: list[AssemblyLink] = Field(default_factory=list)
    through: list[AssemblyThrough] = Field(default_factory=list)
    modules: int = Field(default=0, ge=0, description="Modulerna i anläggningen.")
    problems: list[Text] = Field(default_factory=list, description="Det CAD:s kontroll fann.")


class SectionLength(Contract):
    """Längden i Bana (CAD-11): a section's length along the track in the model, from CAD's
    assembly: from where the tracks leave one driftplats's modules to where they reach the
    other's, through the places between."""

    section: Id
    length: float = Field(gt=0, description="I modellen, i mm.")
    prototype: float = Field(gt=0, description="I förebilden, i meter: längden gånger skalan.")
    tracks: int = Field(ge=1)
    links: list[Id] = Field(default_factory=list, description="Anläggningens spår emellan.")


class CadChoice(Contract):
    """An assembly in TrainMeet CAD the planner may add (Anläggning från CAD)."""

    id: UUID
    name: Text
    scale: Text
    modules: int = Field(ge=0)
    revision: int = Field(ge=1)
    problems: int = Field(default=0, ge=0)
    owner: Text
    changed_at: datetime


class CadAssemblies(Contract):
    """Anläggning från CAD in Lägg till underlag: the planner's assemblies in CAD, or why the way
    is grey (no CAD for this hub, or not logged in with TrainMeet ID)."""

    available: bool
    reason: Text | None = None
    assemblies: list[CadChoice] = Field(default_factory=list)


class Draft(Contract):
    """Utkastet: what Planering works on until it is published as a version."""

    format: Literal["trainmeet.planning/1"] = FORMAT
    meet: Meet
    revision: int = Field(
        default=0, ge=0, description="Räknas upp varje gång utkastet sparas (PLAN-38)."
    )
    package: MeetPackage | None = Field(default=None, description="Tomt tills underlag finns.")
    facts: list[Fact] = Field(default_factory=list)
    rulebook: Rulebook = Field(default_factory=Rulebook)
    sources: list[Source] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    report: ImportReport | None = None
    changes: list[Change] = Field(
        default_factory=list,
        description="Planerarens ändringar, i ordning. De gäller även när underlaget läses om.",
    )
    taken: list[TakenChange] = Field(
        default_factory=list, description="Förslagen från Drift som tagits med, i ordning."
    )
    let_stand: dict[Id, str] = Field(
        default_factory=dict,
        description="Låt stå i rimlighetskontrollen: avvikelsen och fingeravtrycket (PLAN-36).",
    )
    double_track_declined: dict[Id, str] = Field(
        default_factory=dict,
        description="Nej på dubbelspårsfrågan: sträckan och fingeravtrycket av tågen på den.",
    )
    stations: list[StationVersion] = Field(
        default_factory=list, description="Stationernas utsidor bland underlagen (IMPORT-10)."
    )
    assembly: AssemblyLayout | None = Field(
        default=None, description="CAD:s anläggning bland underlagen (CAD-11, K4)."
    )
    lengths: list[SectionLength] = Field(
        default_factory=list, description="Sträckornas längder ur anläggningen (CAD-11)."
    )


class DoubleTrackQuestion(Contract):
    """Dubbelspårsfrågan (PLAN-35): a single-track section with at least two A conflicts. A No
    is kept with the fingerprint, and the question comes back only when the trains change."""

    section: Id
    conflicts: int = Field(ge=2)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    message: Text


class DoubleTrackAnswer(Contract):
    """Ja makes the section double track; Nej keeps it single for these trains."""

    double: bool
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class Deviation(Contract):
    """Rimlighetskontrollen (PLAN-36): a train whose running time or stop is unlike the other
    trains' between the same places or at the same place. Advice, never an error: it does not
    stop publishing and does not go with the version."""

    id: Id = Field(description="Vad och var, aldrig när: slag, tåg och driftplatser.")
    kind: Literal["slow_leg", "fast_leg", "backwards_leg", "backwards_dwell", "long_dwell"]
    title: Text
    message: Text
    train: Id
    train_number: Text
    calls: list[Id] = Field(description="Tågbesöken, det där avvikelsen är först.")
    days: list[Weekday]
    minutes: int
    usual: int | None = Field(default=None, description="De andra tågens median, i minuter.")
    samples: int = Field(ge=0, description="Antal andra tåg i jämförelsen.")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    let_stand: bool = Field(default=False, description="Låt stå, så länge tågbesöken är desamma.")


class LetStand(Contract):
    """Låt stå: the deviation as the planner saw it."""

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class Check(Contract):
    """Trafikkontrollen of the draft (PLAN-35): what publishing would carry in its findings,
    the structural errors that stop publishing, and the double-track questions."""

    findings: list[Finding] = Field(default_factory=list)
    blocking: list[Text] = Field(
        default_factory=list, description="Strukturfel. De stoppar publiceringen."
    )
    double_track: list[DoubleTrackQuestion] = Field(default_factory=list)
    deviations: list[Deviation] = Field(
        default_factory=list, description="Rimlighetskontrollen. Råd, inte regler (PLAN-36)."
    )


class Difference(Contract):
    """What one kind of thing does in the draft if a source is laid in."""

    added: int = Field(default=0, ge=0)
    removed: int = Field(default=0, ge=0)
    changed: int = Field(default=0, ge=0)


class ImportPreview(Contract):
    """Lägg till underlag before anything changes: the level, what the source gave and exactly
    what changes in the draft. Laid in with Lägg in i utkastet."""

    source: Source
    report: ImportReport
    first: bool = Field(description="Sant när utkastet inte har något underlag än.")
    places: Difference = Field(default_factory=Difference)
    sections: Difference = Field(default_factory=Difference)
    trains: Difference = Field(default_factory=Difference)
    lines: Difference = Field(default_factory=Difference, description="Grafens linjer.")
    times: int = Field(default=0, ge=0, description="Tider som ändras i tågbesök som finns kvar.")
    tracks: int = Field(default=0, ge=0, description="Spår som ändras i tågbesök som finns kvar.")
    questions: int = Field(default=0, ge=0)
    kept: int = Field(default=0, ge=0, description="Planerarens ändringar som står kvar.")
    lengths: int = Field(
        default=0, ge=0, description="Sträckor som får sin längd ur CAD:s anläggning (CAD-11)."
    )
