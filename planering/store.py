"""Planering's file: the meets with their drafts and the sources as they came.

One SQLite file, shared with Synk (spec 7, SYNK-20). Planering makes the next version of the
draft (freeze); Synk keeps the versions, frozen, with their checksums (SYNK-08, SYNK-09).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Final

from contracts.common import Id, Language
from contracts.drift import DriftChange, ProposalStatus
from contracts.meet import (
    About,
    AttachmentKind,
    CoupledStation,
    Meet,
    MeetPackage,
    Place,
    PlaceKind,
    RemoteArea,
    Section,
    TrackKind,
    Train,
    hangs_together,
)
from contracts.planning import (
    PLANNER,
    Alternative,
    Answer,
    AssemblyLayout,
    CallChange,
    Certainty,
    Change,
    Check,
    ConfirmChange,
    DoubleTrackAnswer,
    Draft,
    Fact,
    ImportPreview,
    ImportReport,
    ImportResult,
    InstructionsChange,
    LetStand,
    MeetSummary,
    NewMeet,
    Origin,
    PlaceChange,
    Proposal,
    Question,
    RemoteAreaChange,
    SectionChange,
    SectionTracksChange,
    Source,
    SourceKind,
    StationChange,
    StationVersion,
    TakenChange,
    TrainChange,
    TrainDaysChange,
)
from contracts.reasons import TEXT_SV
from contracts.station_outside import StationOutside
from core import changes as driftchanges
from planering import assembly, compare
from planering.check import review
from planering.sanity import deviations

RESERVED: Final = {"provbanan"}
PDF: Final = "application/pdf"
MAX_MEETS: Final = 200

_TIME: Final = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meet (
    id TEXT PRIMARY KEY, created REAL NOT NULL, summary TEXT NOT NULL, draft TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_file (
    meet_id TEXT NOT NULL REFERENCES meet(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL, body BLOB NOT NULL,
    PRIMARY KEY (meet_id, source_id)
);
CREATE TABLE IF NOT EXISTS transcript (
    digest TEXT PRIMARY KEY, model TEXT NOT NULL, text TEXT NOT NULL, made REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pending (
    meet_id TEXT PRIMARY KEY REFERENCES meet(id) ON DELETE CASCADE,
    source TEXT NOT NULL, body BLOB NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposal (
    meet_id TEXT NOT NULL REFERENCES meet(id) ON DELETE CASCADE,
    id TEXT NOT NULL, made REAL NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (meet_id, id)
);
CREATE TABLE IF NOT EXISTS attachment_file (
    sha256 TEXT PRIMARY KEY, media_type TEXT NOT NULL, body BLOB NOT NULL, kept REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_assembly (
    meet_id TEXT PRIMARY KEY REFERENCES meet(id) ON DELETE CASCADE, layout TEXT NOT NULL
);
"""


class PlanningError(Exception):
    """Something Planering cannot do. The message is for the planner."""

    status = 409


class UnknownMeet(PlanningError):
    status = 404


class StaleDraft(PlanningError):
    """Someone else saved the draft since it was read (PLAN-38)."""

    status = 412


class UnknownProposal(PlanningError):
    status = 404


def slug(name: str) -> str:
    """A meet's id from its name: Värnamo Moduldagar → varnamo-moduldagar."""
    text = name.casefold().replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-") or "traff"


class Planning:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ready = False
        self._lock = Lock()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path)) as db:
                    db.executescript(_SCHEMA)
                self._ready = True
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE")
                yield db

    # --- Reading -----------------------------------------------------------------------------

    def meets(self) -> list[MeetSummary]:
        """The meets, newest first. Their versions are Synk's: the hub puts them in."""
        with self._transaction() as db:
            rows = db.execute("SELECT summary FROM meet ORDER BY created DESC").fetchall()
            return [MeetSummary.model_validate_json(summary) for (summary,) in rows]

    def draft(self, meet_id: str) -> Draft:
        with self._transaction() as db:
            return self._draft(db, meet_id)

    def source_file(self, meet_id: str, source_id: str) -> tuple[Source, bytes]:
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            row = db.execute(
                "SELECT body FROM source_file WHERE meet_id=? AND source_id=?",
                (meet_id, source_id),
            ).fetchone()
            source = next((s for s in draft.sources if s.id == source_id), None)
            if row is None or source is None:
                raise UnknownMeet("Underlaget finns inte.")
            return source, bytes(row[0])

    def transcript(self, digest: str) -> str | None:
        """A page's transcription by AI (4c2), by the page's picture: the same page is never
        written down twice (IMPORT-15)."""
        with self._transaction() as db:
            row = db.execute("SELECT text FROM transcript WHERE digest=?", (digest,)).fetchone()
        return str(row[0]) if row else None

    def keep_transcript(self, digest: str, model: str, text: str) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO transcript VALUES (?, ?, ?, ?)",
                (digest, model, text, datetime.now(UTC).timestamp()),
            )

    def sources(self, meet_id: str) -> list[tuple[Source, bytes]]:
        """Every source of the draft as it came, for Underlaget som ZIP (PLAN-07)."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            bodies = dict(
                db.execute(
                    "SELECT source_id, body FROM source_file WHERE meet_id=?", (meet_id,)
                ).fetchall()
            )
        return [(s, bytes(bodies[s.id])) for s in draft.sources if s.id in bodies]

    # --- Träffens hem flyttar (H35, SYNK-16) ------------------------------------------------

    def export(
        self, meet_id: str
    ) -> tuple[datetime, Draft, list[tuple[str, bytes]], list[Proposal]]:
        """Everything the meet's home takes along: when it was made, the draft, the sources as
        they came and the proposals from Drift."""
        with self._transaction() as db:
            row = db.execute("SELECT created FROM meet WHERE id=?", (meet_id,)).fetchone()
            if row is None:
                raise UnknownMeet("Träffen finns inte.")
            draft = self._draft(db, meet_id)
            files = [
                (str(source), bytes(body))
                for source, body in db.execute(
                    "SELECT source_id, body FROM source_file WHERE meet_id=?", (meet_id,)
                )
            ]
            proposals = [
                Proposal.model_validate_json(body)
                for (body,) in db.execute(
                    "SELECT body FROM proposal WHERE meet_id=? ORDER BY made", (meet_id,)
                )
            ]
        return datetime.fromtimestamp(row[0], UTC), draft, files, proposals

    def adopt(
        self,
        created: datetime,
        draft: Draft,
        files: list[tuple[str, bytes]],
        proposals: list[Proposal],
    ) -> Draft:
        """The meet as the hub it comes from had it: it takes the place of what was here."""
        meet_id = draft.meet.id
        with self._transaction() as db:
            # Updated in place: in a file from step 4 the versions still point at the meet.
            for table in ("source_file", "proposal", "pending"):
                db.execute(f"DELETE FROM {table} WHERE meet_id=?", (meet_id,))
            db.execute(
                "INSERT INTO meet VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                " created=excluded.created, summary=excluded.summary, draft=excluded.draft",
                (meet_id, created.timestamp(), _summary(draft), draft.model_dump_json()),
            )
            db.executemany(
                "INSERT INTO source_file VALUES (?, ?, ?)",
                ((meet_id, source, body) for source, body in files),
            )
            db.executemany(
                "INSERT INTO proposal VALUES (?, ?, ?, ?)",
                ((meet_id, p.id, p.made.timestamp(), p.model_dump_json()) for p in proposals),
            )
            # CAD's assembly is also the package's attachment (CAD-12): kept by its checksum.
            bodies = dict(files)
            for source in draft.sources:
                if source.kind == SourceKind.CAD_ASSEMBLY and source.id in bodies:
                    db.execute(
                        "INSERT OR IGNORE INTO attachment_file VALUES (?, ?, ?, ?)",
                        (
                            source.sha256,
                            assembly.MEDIA_TYPE,
                            bodies[source.id],
                            datetime.now(UTC).timestamp(),
                        ),
                    )
        return draft

    def check(self, meet_id: str) -> Check:
        """Trafikkontrollen (PLAN-35): the findings, what stops publishing, and the
        double-track questions."""
        draft = self.draft(meet_id)
        found = review(draft)
        odd = deviations(draft.package, draft.let_stand) if draft.package else []
        return Check(
            findings=found.findings,
            blocking=found.blocking,
            double_track=found.double_track,
            deviations=odd,
        )

    # --- Changing ----------------------------------------------------------------------------

    def create(self, new: NewMeet) -> Draft:
        if new.first_date and new.last_date and new.last_date < new.first_date:
            raise PlanningError("Sista dagen kommer före första dagen.")
        with self._transaction() as db:
            if db.execute("SELECT count(*) FROM meet").fetchone()[0] >= MAX_MEETS:
                raise PlanningError(f"Hubben har redan {MAX_MEETS} träffar.")
            base = slug(new.name)
            meet_id, number = base, 1
            while (
                meet_id in RESERVED
                or db.execute("SELECT 1 FROM meet WHERE id=?", (meet_id,)).fetchone()
            ):
                number += 1
                meet_id = f"{base}-{number}"
            meet = Meet(
                id=meet_id,
                name=new.name,
                country=new.country,
                first_date=new.first_date,
                last_date=new.last_date,
                id_meet=new.id_meet,
            )
            draft = Draft(meet=meet)
            db.execute(
                "INSERT INTO meet VALUES (?, ?, ?, ?)",
                (meet_id, datetime.now(UTC).timestamp(), _summary(draft), draft.model_dump_json()),
            )
            return draft

    def preview(
        self, meet_id: str, source: Source, body: bytes, result: ImportResult
    ) -> ImportPreview:
        """Lägg till underlag, first step: what the source would change. Nothing changes in the
        draft; the source waits until it is laid in (one per meet, the newest)."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            db.execute(
                "INSERT OR REPLACE INTO pending VALUES (?, ?, ?, ?)",
                (meet_id, source.model_dump_json(), body, result.model_dump_json()),
            )
            return compare.preview(draft, _laid_in(draft, source, result), source, result)

    def stage_station(self, meet_id: str, source: Source, body: bytes) -> None:
        """Stationens utsida (IMPORT-10) waits to be laid in, as other sources do. It is coupled
        to a place of the plan, so the plan comes first."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if draft.package is None:
                raise PlanningError(
                    "Lägg till planeringsfilen eller stationslistorna först. Stationen kopplas "
                    "till en av deras driftplatser."
                )
            report = ImportReport(source=source.id, level=draft.report.level if draft.report else 4)
            result = ImportResult(package=draft.package, report=report)
            db.execute(
                "INSERT OR REPLACE INTO pending VALUES (?, ?, ?, ?)",
                (meet_id, source.model_dump_json(), body, result.model_dump_json()),
            )

    def stage_assembly(
        self, meet_id: str, source: Source, body: bytes, layout: AssemblyLayout
    ) -> ImportPreview:
        """CAD:s anläggning (CAD-11, K4) waits to be laid in, as other sources do: what it would
        give the plan's places and sections. It is matched to the plan, so the plan comes first."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if draft.package is None:
                raise PlanningError(
                    "Lägg till planeringsfilen eller stationslistorna först. Anläggningen ger "
                    "längder och platser till deras sträckor och driftplatser."
                )
            before = draft.assembly
            same = before is not None and any(
                s.id == before.source and s.sha256 == source.sha256 for s in draft.sources
            )
            fresh = draft if same else _with_assembly(draft, source, layout)
            given = len(fresh.lengths)
            matched = sum(1 for f in fresh.facts if f.ref.endswith(".modules"))
            notes = [
                f"Anläggningen {layout.name}, revision {layout.revision}: "
                f"{_count(layout.modules, 'modul', 'moduler')}, "
                f"{_count(len(layout.places), 'plats', 'platser')}. "
                f"{_count(matched, 'driftplats', 'driftplatser')} i planen finns i anläggningen, "
                f"och {_count(given, 'sträcka', 'sträckor')} får sin längd ur den."
            ]
            if same:
                notes.append("Samma anläggning som redan finns; inget ändras.")
            notes += [f"CAD: {problem}" for problem in layout.problems[:5]]
            level = max([s.level for s in draft.sources] or [source.level])
            report = ImportReport(source=source.id, level=level, notes=notes)
            result = ImportResult(package=draft.package, report=report)
            db.execute(
                "INSERT OR REPLACE INTO pending VALUES (?, ?, ?, ?)",
                (meet_id, source.model_dump_json(), body, result.model_dump_json()),
            )
            db.execute(
                "INSERT OR REPLACE INTO pending_assembly VALUES (?, ?)",
                (meet_id, layout.model_dump_json()),
            )
            preview = compare.preview(draft, fresh, source, result)
            return preview.model_copy(update={"lengths": 0 if same else given})

    def apply(self, meet_id: str, source_id: str) -> Draft:
        """Lägg in i utkastet: the waiting source comes into the draft."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT source, body, result FROM pending WHERE meet_id=?", (meet_id,)
            ).fetchone()
            if row is None or Source.model_validate_json(row[0]).id != source_id:
                self._draft(db, meet_id)
                raise PlanningError("Underlaget väntar inte längre. Lägg till det igen.")
            db.execute("DELETE FROM pending WHERE meet_id=?", (meet_id,))
            source = Source.model_validate_json(row[0])
            if source.kind == SourceKind.STATION_OUTSIDE:
                return self._add_station(db, meet_id, source, bytes(row[1]))
            if source.kind == SourceKind.CAD_ASSEMBLY:
                found = db.execute(
                    "SELECT layout FROM pending_assembly WHERE meet_id=?", (meet_id,)
                ).fetchone()
                db.execute("DELETE FROM pending_assembly WHERE meet_id=?", (meet_id,))
                if found is None:
                    raise PlanningError("Anläggningen väntar inte längre. Lägg till den igen.")
                layout = AssemblyLayout.model_validate_json(found[0])
                return self._add_assembly(db, meet_id, source, bytes(row[1]), layout)
            result = ImportResult.model_validate_json(row[2])
            return self._add(db, meet_id, source, bytes(row[1]), result)

    def _add_station(
        self, db: sqlite3.Connection, meet_id: str, source: Source, body: bytes
    ) -> Draft:
        """The station's outside among the sources (IMPORT-10). The same outside again changes
        nothing (IMPORT-31); a new one for the same station gets the next number, and a place
        coupled to the station follows it into the next version."""
        draft = self._draft(db, meet_id)
        outside = StationOutside.model_validate_json(body)
        before = next(
            (s for s in draft.stations if s.outside.station_id == outside.station_id), None
        )
        if before is not None and before.outside == outside:
            return draft
        if before is not None:
            db.execute(
                "DELETE FROM source_file WHERE meet_id=? AND source_id=?", (meet_id, before.source)
            )
        db.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?)", (meet_id, source.id, body)
        )
        kept = StationVersion(
            version=(before.version + 1) if before else 1, source=source.id, outside=outside
        )
        stations = [s for s in draft.stations if s.outside.station_id != outside.station_id]
        sources = [s for s in draft.sources if before is None or s.id != before.source]
        updated = draft.model_copy(
            update={"stations": [*stations, kept], "sources": [*sources, source]}
        )
        answers = {q.id: q.answer for q in draft.questions if q.answer is not None}
        return self._save(db, _replay(updated, answers))

    def _add_assembly(
        self,
        db: sqlite3.Connection,
        meet_id: str,
        source: Source,
        body: bytes,
        layout: AssemblyLayout,
    ) -> Draft:
        """CAD:s anläggning among the sources (CAD-11): kept as it came, also beside the package
        as its attachment, so that it goes with the versions to the Pi (CAD-12). The same
        assembly again changes nothing; a new one takes the place of the one before."""
        draft = self._draft(db, meet_id)
        before = draft.assembly
        if before is not None and any(
            s.id == before.source and s.sha256 == source.sha256 for s in draft.sources
        ):
            return draft
        for old in [s for s in draft.sources if s.kind == SourceKind.CAD_ASSEMBLY]:
            db.execute("DELETE FROM source_file WHERE meet_id=? AND source_id=?", (meet_id, old.id))
        db.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?)", (meet_id, source.id, body)
        )
        db.execute(
            "INSERT OR IGNORE INTO attachment_file VALUES (?, ?, ?, ?)",
            (source.sha256, assembly.MEDIA_TYPE, body, datetime.now(UTC).timestamp()),
        )
        return self._save(db, _with_assembly(draft, source, layout))

    def add_source(self, meet_id: str, source: Source, body: bytes, result: ImportResult) -> Draft:
        """A source read by Integrationer comes into the draft at once."""
        with self._transaction() as db:
            return self._add(db, meet_id, source, body, result)

    def _add(
        self,
        db: sqlite3.Connection,
        meet_id: str,
        source: Source,
        body: bytes,
        result: ImportResult,
    ) -> Draft:
        """A new planning file takes the place of the one before; the planner's changes and
        answers stay (principle 7)."""
        draft = self._draft(db, meet_id)
        for old in [s for s in draft.sources if s.kind == source.kind]:
            db.execute("DELETE FROM source_file WHERE meet_id=? AND source_id=?", (meet_id, old.id))
        db.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?, ?, ?)", (meet_id, source.id, body)
        )
        return self._save(db, _laid_in(draft, source, result))

    def change(self, meet_id: str, *changes: Change, revision: int | None = None) -> Draft:
        """The planner's changes, kept in order; the last change per field counts. Made against
        a revision that is no longer the draft's, they are refused (PLAN-38)."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if revision is not None and revision != draft.revision:
                raise StaleDraft(
                    "Någon annan har sparat utkastet under tiden. Det nya utkastet visas, med "
                    "dina ändringar ovanpå. Titta igenom dem och spara igen."
                )
            if draft.package is None:
                raise PlanningError("Lägg till underlag först.")
            known = _things(draft.package)
            known["confirm"] = {fact.ref for fact in draft.facts}
            kept = list(draft.changes)
            for change in changes:
                kind, target = _target(change)
                if isinstance(change, RemoteAreaChange):
                    _check_area(draft.package, change)
                elif target not in known[kind]:
                    raise PlanningError("Det finns inte i utkastet.")
                _check_value(draft.package, change)
                pool = {s.outside.station_id for s in draft.stations}
                if isinstance(change, StationChange) and change.station not in {None, *pool}:
                    raise PlanningError("Stationen finns inte bland underlagen.")
                if isinstance(change, StationChange) and any(
                    p.id == change.place and p.part_of for p in draft.package.places
                ):
                    raise PlanningError(
                        "Driftplatsen är en del av en station och följer stationens koppling. "
                        "Koppla stationen till sin egen driftplats."
                    )
                kept = [c for c in kept if _target(c) != (kind, target)] + [change]
            answers = {q.id: q.answer for q in draft.questions if q.answer is not None}
            draft = _replay(draft.model_copy(update={"changes": kept}), answers)
            assert draft.package is not None
            touched = {_train_of(draft.package, c) for c in changes} - {None}
            for train in draft.package.trains:
                if train.id in touched and not driftchanges.in_order(train.calls):
                    raise PlanningError(f"Tiderna för tåg {train.number} kommer inte i ordning.")
            return self._save(db, draft)

    def let_stand(self, meet_id: str, deviation: Id, given: LetStand) -> Draft:
        """Låt stå (PLAN-36): the deviation is put aside until the calls it is about change."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            found = next(
                (d for d in deviations(draft.package, {}) if d.id == deviation)
                if draft.package
                else iter(()),
                None,
            )
            if found is None:
                raise PlanningError("Avvikelsen finns inte längre.")
            if found.fingerprint != given.fingerprint:
                raise PlanningError("Tåget har ändrats sedan avvikelsen visades. Titta igen.")
            kept = {**draft.let_stand, deviation: given.fingerprint}
            return self._save(db, draft.model_copy(update={"let_stand": kept}))

    def take_back(self, meet_id: str, deviation: Id) -> Draft:
        """Ta tillbaka a Låt stå."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if deviation not in draft.let_stand:
                raise PlanningError("Avvikelsen står inte som lämnad.")
            kept = {k: v for k, v in draft.let_stand.items() if k != deviation}
            return self._save(db, draft.model_copy(update={"let_stand": kept}))

    def double_track(self, meet_id: str, section: Id, answer: DoubleTrackAnswer) -> Draft:
        """Dubbelspårsfrågan (PLAN-35): Ja makes the section double track, as the planner's
        change; Nej is kept with the fingerprint of the trains on it."""
        asked = next(
            (q for q in review(self.draft(meet_id)).double_track if q.section == section), None
        )
        if asked is None:
            raise PlanningError("Frågan ställs inte längre.")
        if asked.fingerprint != answer.fingerprint:
            raise PlanningError("Tågen på sträckan har ändrats sedan frågan ställdes. Titta igen.")
        if answer.double:
            return self.change(
                meet_id, SectionTracksChange(section=section, tracks=TrackKind.DOUBLE)
            )
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            declined = {**draft.double_track_declined, section: answer.fingerprint}
            return self._save(db, draft.model_copy(update={"double_track_declined": declined}))

    def answer(self, meet_id: str, answer: Answer) -> Draft:
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            question = next((q for q in draft.questions if q.id == answer.question), None)
            if question is None:
                raise PlanningError("Frågan finns inte.")
            if answer.value not in {a.value for a in question.alternatives}:
                raise PlanningError("Svaret är inte ett av alternativen.")
            answers = {q.id: q.answer for q in draft.questions if q.answer is not None}
            answers[question.id] = answer.value
            return self._save(db, _replay(draft, answers))

    def freeze(self, meet_id: str) -> MeetPackage:
        """The draft as the next version, with the traffic check's findings in it. Synk keeps
        it and gives it its number (SYNK-08)."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
        if draft.package is None:
            raise PlanningError("Lägg till underlag innan du publicerar.")
        found = review(draft)
        if found.blocking:
            raise PlanningError("Rätta det här innan du publicerar: " + " ".join(found.blocking))
        return MeetPackage.model_validate(
            draft.package.model_copy(
                update={"meet": draft.meet, "findings": found.findings}
            ).model_dump(mode="json")
        )

    # --- Förslag från Drift (4.4, PLAN-03) ------------------------------------------------------

    def propose(
        self,
        meet_id: str,
        version: int,
        change_id: str,
        change: DriftChange,
        train_number: str | None,
    ) -> None:
        """A driftändring becomes a proposal for the next version. A meet Planering does not
        have, such as Provbanan, has none; the same change twice is one proposal."""
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM meet WHERE id=?", (meet_id,)).fetchone() is None:
                return
            now = datetime.now(UTC)
            proposal = Proposal(
                id=change_id,
                meet=meet_id,
                version=version,
                change=change,
                train_number=train_number,
                made=now,
            )
            db.execute(
                "INSERT OR IGNORE INTO proposal VALUES (?, ?, ?, ?)",
                (meet_id, change_id, now.timestamp(), proposal.model_dump_json()),
            )

    def proposals(self, meet_id: str) -> list[Proposal]:
        """The proposals, newest first."""
        with self._transaction() as db:
            self._draft(db, meet_id)
            return [
                Proposal.model_validate_json(body)
                for (body,) in db.execute(
                    "SELECT body FROM proposal WHERE meet_id=? ORDER BY made DESC, id",
                    (meet_id,),
                )
            ]

    def answers(self, meet_id: str) -> dict[str, ProposalStatus]:
        """Planering's answer to each driftändring, for Drift to show (4.4)."""
        try:
            return {p.id: p.status for p in self.proposals(meet_id)}
        except UnknownMeet:
            return {}

    def withdraw(self, meet_id: str, change_id: str) -> None:
        """Släppt in Drift before Planering answered: no longer a proposal. One taken stays in
        the draft; the planner decides about it there."""
        with self._transaction() as db:
            proposal = self._find(db, meet_id, change_id)
            if proposal is not None and proposal.status == ProposalStatus.WAITING:
                self._answer(db, proposal, ProposalStatus.WITHDRAWN)

    def take(self, meet_id: str, change_id: str) -> Draft:
        """Ta med: the change is laid on the draft, and stays there when the sources are read
        again. It is made the same way as in Drift (core/changes.py)."""
        with self._transaction() as db:
            proposal = self._proposal(db, meet_id, change_id)
            if proposal.status != ProposalStatus.WAITING:
                raise PlanningError("Förslaget är redan besvarat.")
            draft = self._draft(db, meet_id)
            if draft.package is None:
                raise PlanningError("Lägg till underlag först.")
            try:
                package = driftchanges.apply(draft.package, proposal.change, proposal.id)
            except driftchanges.ChangeError as error:
                raise PlanningError(
                    f"Förslaget går inte att ta med i utkastet: {TEXT_SV[error.reason]}"
                ) from error
            draft = draft.model_copy(
                update={
                    "package": package,
                    "taken": [*draft.taken, TakenChange(id=proposal.id, change=proposal.change)],
                }
            )
            saved = self._save(db, draft)
            self._answer(db, proposal, ProposalStatus.TAKEN)
            return saved

    def reject(self, meet_id: str, change_id: str) -> Proposal:
        """Avslå: the next version is made without it. Drift sees the answer."""
        with self._transaction() as db:
            proposal = self._proposal(db, meet_id, change_id)
            if proposal.status != ProposalStatus.WAITING:
                raise PlanningError("Förslaget är redan besvarat.")
            return self._answer(db, proposal, ProposalStatus.REJECTED)

    @staticmethod
    def _find(db: sqlite3.Connection, meet_id: str, change_id: str) -> Proposal | None:
        row = db.execute(
            "SELECT body FROM proposal WHERE meet_id=? AND id=?", (meet_id, change_id)
        ).fetchone()
        return None if row is None else Proposal.model_validate_json(row[0])

    def _proposal(self, db: sqlite3.Connection, meet_id: str, change_id: str) -> Proposal:
        found = self._find(db, meet_id, change_id)
        if found is None:
            raise UnknownProposal("Förslaget finns inte.")
        return found

    @staticmethod
    def _answer(db: sqlite3.Connection, proposal: Proposal, status: ProposalStatus) -> Proposal:
        answered = proposal.model_copy(update={"status": status, "answered": datetime.now(UTC)})
        db.execute(
            "UPDATE proposal SET body=? WHERE meet_id=? AND id=?",
            (answered.model_dump_json(), proposal.meet, proposal.id),
        )
        return answered

    # --- Files beside the package (Attachment) ------------------------------------------------

    def keep_file(self, body: bytes, media_type: str) -> str:
        """A file the package carries beside it, such as the general instructions as PDF
        (PLAN-40), kept by its checksum. The same file twice is kept once."""
        digest = hashlib.sha256(body).hexdigest()
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO attachment_file VALUES (?, ?, ?, ?)",
                (digest, media_type, body, datetime.now(UTC).timestamp()),
            )
        return digest

    def file(self, digest: str) -> tuple[str, bytes] | None:
        """The file with the checksum, as kept: its media type and its bytes."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT media_type, body FROM attachment_file WHERE sha256=?", (digest,)
            ).fetchone()
        return None if row is None else (str(row[0]), bytes(row[1]))

    # --- Inside ------------------------------------------------------------------------------

    @staticmethod
    def _draft(db: sqlite3.Connection, meet_id: str) -> Draft:
        row = db.execute("SELECT draft FROM meet WHERE id=?", (meet_id,)).fetchone()
        if row is None:
            raise UnknownMeet("Träffen finns inte.")
        return Draft.model_validate_json(row[0])

    @staticmethod
    def _save(db: sqlite3.Connection, draft: Draft) -> Draft:
        """Save the draft as its next revision (PLAN-38)."""
        saved = draft.model_copy(update={"revision": draft.revision + 1})
        db.execute(
            "UPDATE meet SET summary=?, draft=? WHERE id=?",
            (_summary(saved), saved.model_dump_json(), saved.meet.id),
        )
        return saved


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _summary(draft: Draft) -> str:
    package = draft.package
    return MeetSummary(
        meet=draft.meet,
        level=max((s.level for s in draft.sources), default=None),
        places=len(package.places) if package else 0,
        trains=len(package.trains) if package else 0,
        sources=len(draft.sources),
        questions=sum(q.answer is None for q in draft.questions),
    ).model_dump_json()


def _target(change: Change) -> tuple[str, Id]:
    """Which field of which thing a change sets."""
    if isinstance(change, PlaceChange):
        return "place", change.place
    if isinstance(change, SectionTracksChange):
        return "tracks", change.section
    if isinstance(change, CallChange):
        return f"call.{change.field}", change.call
    if isinstance(change, TrainChange):
        return f"train.{change.field}", change.train
    if isinstance(change, TrainDaysChange):
        return "train.days", change.train
    if isinstance(change, ConfirmChange):
        return "confirm", change.confirm
    if isinstance(change, StationChange):
        return "station", change.place
    if isinstance(change, InstructionsChange):
        return "instructions", _instructions_target(change)
    if isinstance(change, RemoteAreaChange):
        return "remote_area", change.remote_area
    return "section", change.section


def _instructions_target(change: InstructionsChange) -> str:
    """The text in one language, or the PDF: the last change to each counts."""
    return "pdf" if change.instructions == "pdf" else f"text:{change.language.value}"


def _things(package: MeetPackage) -> dict[str, set[Id]]:
    """What each kind of change may point at in the draft."""
    places = {p.id for p in package.places}
    sections = {s.id for s in package.sections}
    calls = {c.id for t in package.trains for c in t.calls}
    trains = {t.id for t in package.trains}
    kinds: dict[str, set[Id]] = {
        "place": places,
        "station": places,
        "tracks": sections,
        "section": sections,
    }
    kinds.update({f"call.{field}": calls for field in ("arrival", "departure", "track")})
    kinds.update({f"train.{field}": trains for field in ("number", "note", "days")})
    kinds["instructions"] = {"pdf", *(f"text:{language.value}" for language in Language)}
    return kinds


def _check_value(package: MeetPackage, change: Change) -> None:
    """A time as TT:MM, a track the place has, and a train with a number."""
    if isinstance(change, CallChange) and change.value is not None:
        if change.field in ("arrival", "departure") and not _TIME.match(change.value):
            raise PlanningError("Skriv tiden som TT:MM, till exempel 06:15.")
        if change.field == "track":
            at = next(c.place for t in package.trains for c in t.calls if c.id == change.call)
            place = next(p for p in package.places if p.id == at)
            if place.tracks and change.value not in {t.name for t in place.tracks}:
                raise PlanningError(f"Spåret {change.value} finns inte på {place.name}.")
    if isinstance(change, TrainChange) and change.field == "number" and not change.value:
        raise PlanningError("Ett tåg måste ha ett nummer.")
    pdf = change.pdf if isinstance(change, InstructionsChange) else None
    if pdf is not None and (pdf.kind != AttachmentKind.INSTRUCTIONS or pdf.media_type != PDF):
        raise PlanningError("Instruktionerna läggs in som en PDF.")


def _check_area(package: MeetPackage, change: RemoteAreaChange) -> None:
    """A remote area (PLAN-33, FR2): known driftplatser, no halts, in no other area, that hang
    together along the line. With no name it is taken away."""
    if change.name is None:
        return
    places = {p.id: p for p in package.places}
    if not change.places:
        raise PlanningError("Ett fjärrområde har minst en driftplats.")
    for ref in change.places:
        place = places.get(ref)
        if place is None:
            raise PlanningError("Driftplatsen finns inte i utkastet.")
        if place.kind == PlaceKind.HALT:
            raise PlanningError(f"{place.name} är en hållplats och kan inte fjärrstyras.")
        other = next(
            (a for a in package.remote_areas if a.id != change.remote_area and ref in a.places),
            None,
        )
        if other is not None:
            raise PlanningError(f"{place.name} hör redan till fjärrområdet {other.name}.")
    if len(set(change.places)) != len(change.places):
        raise PlanningError("En driftplats står två gånger i fjärrområdet.")
    if not hangs_together(package, change.places):
        raise PlanningError("Fjärrområdet hänger inte ihop längs linjen.")


def _remote_areas(
    package: MeetPackage, places: dict[Id, Place], changes: list[Change]
) -> list[RemoteArea]:
    """The plan's remote areas after the planner's changes (PLAN-04, PLAN-33, FR49). A place in
    an area is planned as remote-controlled from it, not from another place; one taken out of
    every area is manned again."""
    areas = {area.id: area for area in package.remote_areas}
    for change in changes:
        if not isinstance(change, RemoteAreaChange):
            continue
        if change.name is None:
            areas.pop(change.remote_area, None)
            continue
        areas[change.remote_area] = RemoteArea(
            id=change.remote_area,
            name=change.name,
            places=[ref for ref in change.places if ref in places],
        )
    member = {ref: area.id for area in areas.values() for ref in area.places}
    for place_id, place in list(places.items()):
        if place_id in member:
            places[place_id] = place.model_copy(
                update={
                    "kind": PlaceKind.REMOTE,
                    "remote_area": member[place_id],
                    "remote_from": None,
                }
            )
        elif place.remote_area is not None:
            places[place_id] = place.model_copy(
                update={"kind": PlaceKind.MANNED, "remote_area": None}
            )
    return [area for area in areas.values() if area.places]


def _train_of(package: MeetPackage, change: Change) -> Id | None:
    """The train a call's time changes, whose times must still come in order."""
    if isinstance(change, CallChange) and change.field != "track":
        return next((t.id for t in package.trains for c in t.calls if c.id == change.call), None)
    return None


def _laid_in(draft: Draft, source: Source, result: ImportResult) -> Draft:
    """The draft with the source in it, the meet's own name and dates kept, and the planner's
    changes and answers on top."""
    if result.checks_only:
        # Stationslistorna prövade mot planeringsfilen (IMPORT-27): the draft stays as it is;
        # the source is kept and its verdicts go with the report.
        report = draft.report or result.report
        if result.report.verdicts:
            report = report.model_copy(update={"verdicts": result.report.verdicts})
        return draft.model_copy(
            update={
                "sources": [s for s in draft.sources if s.kind != source.kind] + [source],
                "report": report,
            }
        )
    meet = draft.meet.model_copy(
        update={
            "traffic_week": result.package.meet.traffic_week,
            "first_date": draft.meet.first_date or result.package.meet.first_date,
            "last_date": draft.meet.last_date or result.package.meet.last_date,
        }
    )
    answers = {q.id: q.answer for q in draft.questions if q.answer is not None}
    fresh = Draft(
        meet=meet,
        revision=draft.revision,
        package=result.package.model_copy(update={"meet": meet}),
        facts=result.facts,
        rulebook=result.rulebook,
        sources=[s for s in draft.sources if s.kind != source.kind] + [source],
        questions=result.questions,
        report=result.report,
        changes=draft.changes,
        taken=draft.taken,
        double_track_declined=draft.double_track_declined,
        let_stand=draft.let_stand,
        stations=draft.stations,
        assembly=draft.assembly,
    )
    return _lay_taken(_replay(fresh, answers))


def _with_assembly(draft: Draft, source: Source, layout: AssemblyLayout) -> Draft:
    """The draft with CAD's assembly as its source, in place of any before (CAD-11)."""
    sources = [s for s in draft.sources if s.kind != SourceKind.CAD_ASSEMBLY] + [source]
    answers = {q.id: q.answer for q in draft.questions if q.answer is not None}
    updated = draft.model_copy(
        update={"sources": sources, "assembly": layout.model_copy(update={"source": source.id})}
    )
    return _replay(updated, answers)


def _lay_taken(draft: Draft) -> Draft:
    """The driftändringar taken from Drift, on the draft read anew. One that no longer fits the
    source, because what it pointed at is gone, is left out of the package but kept."""
    package = draft.package
    if package is None:
        return draft
    for taken in draft.taken:
        try:
            package = driftchanges.apply(package, taken.change, taken.id)
        except driftchanges.ChangeError:
            continue
    return draft.model_copy(update={"package": package})


def _replay(draft: Draft, answers: Mapping[str, str]) -> Draft:
    """The planner's changes and answers on top of what the sources gave. The stations are
    coupled anew each time, their parts first (PLAN-34), so that a change to a part's place
    counts as one to any other place."""
    package = draft.package
    if package is None:
        return draft
    # What earlier couplings made is undone here and made again from the changes below.
    made = {p.id for p in package.places if PART_SOURCE in p.source_ids}
    facts = {
        fact.ref: fact
        for fact in draft.facts
        if not any(fact.ref == f"place:{i}" or fact.ref.startswith(f"place:{i}.") for i in made)
    }
    planner = [Origin(source=PLANNER, at="Planering")]
    places: dict[Id, Place] = {
        p.id: p.model_copy(update={"part_of": None, "station": None}) if p.part_of else p
        for p in package.places
        if p.id not in made
    }
    sections: dict[Id, Section] = {s.id: s for s in package.sections}
    trains: dict[Id, Train] = {t.id: t for t in package.trains}
    owner = {c.id: t.id for t in package.trains for c in t.calls}
    coupled: dict[Id, Id | None] = {
        change.place: change.station
        for change in draft.changes
        if isinstance(change, StationChange) and change.place in places
    }
    pool = {s.outside.station_id: s for s in draft.stations}
    places, part_questions, part_facts = _parts(places, coupled, pool, answers)
    facts.update({fact.ref: fact for fact in part_facts})
    # CAD:s anläggning (CAD-11): laid on anew each time, before the planner's changes, so that
    # the planner's own choice of single or double track counts over the answer, and a length
    # can be confirmed.
    facts = {ref: fact for ref, fact in facts.items() if not assembly.is_cad_fact(ref)}
    laid: assembly.Laid | None = None
    if draft.assembly is not None:
        source = next((s for s in draft.sources if s.id == draft.assembly.source), None)
        laid = assembly.lay(places, sections, draft.assembly, answers, source)
        sections = laid.sections
        facts.update({fact.ref: fact for fact in laid.facts})
    about = dict(package.about)
    attachments = list(package.attachments)
    for change in draft.changes:
        if isinstance(change, InstructionsChange):
            # De allmänna instruktionerna (PLAN-40): the text in about, the PDF as attachment.
            if change.instructions == "pdf":
                attachments = [a for a in attachments if a.kind != AttachmentKind.INSTRUCTIONS]
                attachments += [change.pdf] if change.pdf is not None else []
            else:
                text = (change.text or "").strip() or None
                kept_about = about.get(change.language) or About()
                about[change.language] = kept_about.model_copy(update={"instructions": text})
            continue
        if isinstance(change, ConfirmChange):
            found = facts.get(change.confirm)
            if found is not None and found.certainty in (Certainty.UNSURE, Certainty.LIKELY):
                kept = [o for o in found.origins if o.source != PLANNER]
                facts[found.ref] = found.model_copy(
                    update={"certainty": Certainty.CONFIRMED, "origins": [*kept, *planner]}
                )
            continue
        if isinstance(change, CallChange) and change.call in owner:
            train = trains[owner[change.call]]
            trains[train.id] = train.model_copy(
                update={
                    "calls": [
                        c.model_copy(update={change.field: change.value})
                        if c.id == change.call
                        else c
                        for c in train.calls
                    ]
                }
            )
            ref = f"call:{change.call}.{change.field}"
        elif isinstance(change, TrainChange) and change.train in trains:
            trains[change.train] = trains[change.train].model_copy(
                update={change.field: change.value}
            )
            ref = f"train:{change.train}.{change.field}"
        elif isinstance(change, TrainDaysChange) and change.train in trains:
            trains[change.train] = trains[change.train].model_copy(update={"days": change.days})
            ref = f"train:{change.train}.days"
        elif isinstance(change, PlaceChange) and change.place in places:
            places[change.place] = places[change.place].model_copy(update={"phone": change.phone})
            ref = f"place:{change.place}.phone"
        elif isinstance(change, SectionTracksChange) and change.section in sections:
            sections[change.section] = sections[change.section].model_copy(
                update={"tracks": change.tracks}
            )
            ref = f"section:{change.section}.tracks"
        elif isinstance(change, StationChange) and change.place in coupled:
            ref = f"place:{change.place}.station"
        elif isinstance(change, SectionChange) and change.section in sections:
            sections[change.section] = sections[change.section].model_copy(
                update={"clearance_mode": change.clearance_mode}
            )
            ref = f"section:{change.section}.clearance_mode"
        else:
            continue
        facts[ref] = Fact(ref=ref, certainty=Certainty.CONFIRMED, origins=planner)
    questions = [
        q.model_copy(update={"answer": answers.get(q.id)})
        for q in draft.questions
        if q.cause not in (STATION_TRACK, STATION_PART) and q.cause not in assembly.CAUSES
    ] + part_questions
    if laid is not None:
        questions += laid.questions
    for place_id, place in list(places.items()):
        if place_id in coupled:
            entry = pool.get(coupled[place_id] or "")
            if entry is None:
                places[place_id] = place.model_copy(update={"station": None})
                continue
            link = CoupledStation(
                station_id=entry.outside.station_id, version=entry.version, outside=entry.outside
            )
        elif place.part_of is not None and place.station is not None:
            link = place.station
        else:
            continue
        named = [t.name for t in place.tracks] or sorted(
            {c.track for t in trains.values() for c in t.calls if c.place == place_id and c.track}
        )
        track_map, asked = _station_tracks(place, named, link.outside, answers)
        questions += asked
        places[place_id] = place.model_copy(
            update={"station": link.model_copy(update={"track_map": track_map})}
        )
    areas = _remote_areas(package, places, list(draft.changes))
    facts = {ref: fact for ref, fact in facts.items() if not ref.startswith("remote_area:")}
    for area in areas:
        facts[f"remote_area:{area.id}"] = Fact(
            ref=f"remote_area:{area.id}", certainty=Certainty.CONFIRMED, origins=planner
        )
    rules = []
    for rule in draft.rulebook.train_types:
        question = next((q for q in questions if f"train_type:{rule.code}" in q.refs), None)
        if question is not None and question.answer is not None:
            origins = [*[o for o in rule.origins if o.source != PLANNER], *planner]
            rule = rule.model_copy(
                update={
                    "content": question.answer,
                    "certainty": Certainty.CONFIRMED,
                    "origins": origins,
                }
            )
            facts[f"train_type:{rule.code}"] = Fact(
                ref=f"train_type:{rule.code}", certainty=Certainty.CONFIRMED, origins=origins
            )
        rules.append(rule)
    display = package.display
    attachments = [a for a in attachments if a.id != assembly.ATTACHMENT]
    if laid is not None:
        if laid.layout is not None:
            display = display.model_copy(update={"reference_layout": laid.layout})
        if laid.attachment is not None:
            attachments.append(laid.attachment)
    return draft.model_copy(
        update={
            "package": package.model_copy(
                update={
                    "places": list(places.values()),
                    "sections": list(sections.values()),
                    "trains": list(trains.values()),
                    "about": about,
                    "attachments": attachments,
                    "remote_areas": areas,
                    "display": display,
                }
            ),
            "facts": list(facts.values()),
            "questions": questions,
            "rulebook": draft.rulebook.model_copy(update={"train_types": rules}),
            "lengths": laid.lengths if laid is not None else [],
        }
    )


STATION_TRACK: Final = "station_track"
STATION_PART: Final = "station_part"
NEW_PART: Final = "new"
"""The answer that a place of the plan is not the part: the part gets a place of its own."""
PART_SOURCE: Final = "station_part"
"""source_ids key of a place made from a station's part: the part's id."""


def _parts(
    places: dict[Id, Place],
    coupled: Mapping[Id, Id | None],
    pool: Mapping[Id, StationVersion],
    answers: Mapping[str, str],
) -> tuple[dict[Id, Place], list[Question], list[Fact]]:
    """The parts of the coupled stations that are their own driftplatser (PLAN-34, TKL101).
    A place of the plan with the part's id or name is linked to the station as the part, and
    the planner is asked to confirm it, as with the tracks; a No gives the part a place of its
    own. A part the plan does not have becomes a manned place right after the station's,
    linked to the same station. A place coupled to a station itself is never a part."""
    asked: list[Question] = []
    facts: list[Fact] = []
    taken = {place for place, station in coupled.items() if station}
    for home_id, station_id in coupled.items():
        entry = pool.get(station_id or "")
        if entry is None:
            continue
        outside, home, after = entry.outside, places[home_id], home_id
        for part in outside.parts:
            link = CoupledStation(
                station_id=outside.station_id, version=entry.version, outside=outside, part=part.id
            )
            found = _part_in_plan(places, part.id, part.name, taken)
            question_id = _question_id(f"station-part:{home_id}:", part.id)
            answer = answers.get(question_id)
            if found is not None:
                asked.append(
                    Question(
                        id=question_id,
                        cause=STATION_PART,
                        message=f"Är driftplatsen {found.name} i planen delen {part.name} av "
                        f"stationen {outside.name} i {home.name}?",
                        refs=[f"place:{found.id}", f"place:{home_id}"],
                        alternatives=[
                            Alternative(value=found.id, label=f"Ja, {found.name} är delen"),
                            Alternative(value=NEW_PART, label=f"Nej, en ny driftplats {part.name}"),
                        ],
                        answer=answer if answer in (found.id, NEW_PART) else None,
                    )
                )
                if answer != NEW_PART:
                    taken.add(found.id)
                    places[found.id] = found.model_copy(
                        update={"part_of": home_id, "station": link}
                    )
                    continue
            new = Place(
                id=_free_id(part.id, places),
                code=part.code or part.name,
                name=part.name,
                kind=PlaceKind.MANNED,
                part_of=home_id,
                station=link,
                source_ids={PART_SOURCE: part.id},
            )
            taken.add(new.id)
            places = _after(places, after, new)
            after = new.id
            facts.append(
                Fact(
                    ref=f"place:{new.id}",
                    certainty=Certainty.SURE,
                    origins=[Origin(source=entry.source, at=f"Delen {part.id}")],
                    note=f"En del av stationen {outside.name} som bemannas för sig.",
                )
            )
    return places, asked, facts


def _part_in_plan(
    places: Mapping[Id, Place], part_id: str, name: str, taken: set[Id]
) -> Place | None:
    """The place of the plan that is the part: the same id, else the same name. A halt has no
    clearance and no TKL, so it is never a part."""
    free = [p for p in places.values() if p.id not in taken and p.kind != PlaceKind.HALT]
    by_id = [p for p in free if p.id == part_id]
    by_name = [p for p in free if p.name.casefold() == name.casefold()]
    found = by_id or by_name
    return found[0] if len(found) == 1 else None


def _free_id(wanted: str, places: Mapping[Id, Place]) -> str:
    """The part's id as the place's, or with a number after it when the plan has the id."""
    found, number = wanted, 1
    while found in places:
        number += 1
        found = f"{wanted[: 80 - len(str(number)) - 1]}-{number}"
    return found


def _after(places: dict[Id, Place], after: Id, place: Place) -> dict[Id, Place]:
    """The places in order, with the new one right after the given one (PLAN-34)."""
    ordered: dict[Id, Place] = {}
    for key, value in places.items():
        ordered[key] = value
        if key == after:
            ordered[place.id] = place
    return ordered


def _question_id(prefix: str, name: str) -> str:
    """A question's id: the prefix and the name with only an id's characters, within 80."""
    return (prefix + re.sub(r"[^A-Za-z0-9]+", "-", name)[:40])[:80]


def _station_tracks(
    place: Place, named: list[str], outside: StationOutside, answers: Mapping[str, str]
) -> tuple[dict[str, str], list[Question]]:
    """Planens spår mot stationens (IMPORT-18, H27): a name that is the station track's id or
    label is taken as it is; one that differs becomes a question, and the answer is kept."""
    ids = {t.id for t in outside.tracks}
    found: dict[str, str] = {}
    asked: list[Question] = []
    for name in named:
        key = name.casefold().removeprefix("spår ").strip()
        match = [
            t.id
            for t in outside.tracks
            if key in (t.id.casefold(), t.label.casefold().removeprefix("spår ").strip())
        ]
        if len(match) == 1:
            found[name] = match[0]
            continue
        question_id = _question_id(f"station-track:{place.id}:", name)
        answer = answers.get(question_id)
        if answer in ids:
            found[name] = answer
        asked.append(
            Question(
                id=question_id,
                cause=STATION_TRACK,
                message=f"Vilket spår i stationen {outside.name} är planens spår {name} i "
                f"{place.name}?",
                refs=[f"place:{place.id}.station"],
                alternatives=[Alternative(value=t.id, label=t.label) for t in outside.tracks],
                answer=answer if answer in ids else None,
            )
        )
    return found, asked
