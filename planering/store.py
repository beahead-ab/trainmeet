"""Planering's file: the meets with their drafts, the sources as they came, and the versions.

One SQLite file (spec 7: Planering and Synk share one; Synk comes later). A version is frozen:
it is written once with its checksum and never changed or deleted.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Final

from contracts.common import Id, checksum
from contracts.drift import DriftChange, ProposalStatus
from contracts.meet import Meet, MeetPackage, Place, Section, TrackKind, Train
from contracts.planning import (
    PLANNER,
    Answer,
    CallChange,
    Certainty,
    Change,
    Check,
    ConfirmChange,
    DoubleTrackAnswer,
    Draft,
    Fact,
    ImportPreview,
    ImportResult,
    LetStand,
    MeetSummary,
    NewMeet,
    Origin,
    PlaceChange,
    Proposal,
    SectionChange,
    SectionTracksChange,
    Source,
    TakenChange,
    TrainChange,
    TrainDaysChange,
    Version,
)
from contracts.reasons import TEXT_SV
from core import changes as driftchanges
from planering import compare
from planering.check import review
from planering.sanity import deviations

RESERVED: Final = {"provbanan"}
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
CREATE TABLE IF NOT EXISTS pending (
    meet_id TEXT PRIMARY KEY REFERENCES meet(id) ON DELETE CASCADE,
    source TEXT NOT NULL, body BLOB NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS version (
    meet_id TEXT NOT NULL REFERENCES meet(id),
    number INTEGER NOT NULL, info TEXT NOT NULL, package TEXT NOT NULL,
    PRIMARY KEY (meet_id, number)
);
CREATE TABLE IF NOT EXISTS proposal (
    meet_id TEXT NOT NULL REFERENCES meet(id) ON DELETE CASCADE,
    id TEXT NOT NULL, made REAL NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (meet_id, id)
);
"""


class PlanningError(Exception):
    """Something Planering cannot do. The message is for the planner."""

    status = 409


class UnknownMeet(PlanningError):
    status = 404


class UnknownVersion(PlanningError):
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
        with self._transaction() as db:
            rows = db.execute("SELECT id, summary FROM meet ORDER BY created DESC").fetchall()
            return [
                MeetSummary.model_validate_json(summary).model_copy(
                    update={"versions": self._versions(db, meet_id)}
                )
                for meet_id, summary in rows
            ]

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

    def versions(self, meet_id: str) -> list[Version]:
        with self._transaction() as db:
            self._draft(db, meet_id)
            return self._versions(db, meet_id)

    def package(self, meet_id: str, number: int) -> MeetPackage:
        with self._transaction() as db:
            row = db.execute(
                "SELECT package FROM version WHERE meet_id=? AND number=?", (meet_id, number)
            ).fetchone()
        if row is None:
            raise UnknownVersion("Den versionen av träffen finns inte.")
        return MeetPackage.model_validate_json(row[0])

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
            result = ImportResult.model_validate_json(row[2])
            return self._add(db, meet_id, source, bytes(row[1]), result)

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
                if target not in known[kind]:
                    raise PlanningError("Det finns inte i utkastet.")
                _check_value(draft.package, change)
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

    def publish(self, meet_id: str) -> Version:
        """The draft as the next version, with the traffic check's findings in it."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if draft.package is None:
                raise PlanningError("Lägg till underlag innan du publicerar.")
            found = review(draft)
            if found.blocking:
                raise PlanningError(
                    "Rätta det här innan du publicerar: " + " ".join(found.blocking)
                )
            findings = found.findings
            package = MeetPackage.model_validate(
                draft.package.model_copy(
                    update={"meet": draft.meet, "findings": findings}
                ).model_dump(mode="json")
            )
            data = package.model_dump(mode="json")
            digest = checksum(data)
            versions = self._versions(db, meet_id)
            if versions and versions[-1].checksum == digest:
                raise PlanningError(f"Utkastet är detsamma som version {versions[-1].number}.")
            version = Version(
                meet=meet_id,
                number=(versions[-1].number + 1) if versions else 1,
                published=datetime.now(UTC),
                checksum=digest,
                conflicts=sum(f.severity == "conflict" for f in findings),
                observations=sum(f.severity == "observation" for f in findings),
            )
            db.execute(
                "INSERT INTO version VALUES (?, ?, ?, ?)",
                (meet_id, version.number, version.model_dump_json(), package.model_dump_json()),
            )
            return version

    def withdraw_version(self, meet_id: str, number: int) -> Version:
        """Dra tillbaka en version (PLAN-18, F21): it can no longer be started or switched to,
        but it stays, frozen, so that history and logs hold. A meet that runs it goes on, with
        a warning (H68)."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT info FROM version WHERE meet_id=? AND number=?", (meet_id, number)
            ).fetchone()
            if row is None:
                raise UnknownVersion("Versionen finns inte.")
            version = Version.model_validate_json(row[0])
            if version.withdrawn is not None:
                raise PlanningError("Versionen är redan tillbakadragen.")
            withdrawn = version.model_copy(update={"withdrawn": datetime.now(UTC)})
            db.execute(
                "UPDATE version SET info=? WHERE meet_id=? AND number=?",
                (withdrawn.model_dump_json(), meet_id, number),
            )
            return withdrawn

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

    @staticmethod
    def _versions(db: sqlite3.Connection, meet_id: str) -> list[Version]:
        return [
            Version.model_validate_json(info)
            for (info,) in db.execute(
                "SELECT info FROM version WHERE meet_id=? ORDER BY number", (meet_id,)
            )
        ]


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
    return "section", change.section


def _things(package: MeetPackage) -> dict[str, set[Id]]:
    """What each kind of change may point at in the draft."""
    places = {p.id for p in package.places}
    sections = {s.id for s in package.sections}
    calls = {c.id for t in package.trains for c in t.calls}
    trains = {t.id for t in package.trains}
    kinds: dict[str, set[Id]] = {"place": places, "tracks": sections, "section": sections}
    kinds.update({f"call.{field}": calls for field in ("arrival", "departure", "track")})
    kinds.update({f"train.{field}": trains for field in ("number", "note", "days")})
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
    )
    return _lay_taken(_replay(fresh, answers))


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
    """The planner's changes and answers on top of what the sources gave."""
    package = draft.package
    if package is None:
        return draft
    facts = {fact.ref: fact for fact in draft.facts}
    planner = [Origin(source=PLANNER, at="Planering")]
    places: dict[Id, Place] = {p.id: p for p in package.places}
    sections: dict[Id, Section] = {s.id: s for s in package.sections}
    trains: dict[Id, Train] = {t.id: t for t in package.trains}
    owner = {c.id: t.id for t in package.trains for c in t.calls}
    for change in draft.changes:
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
        elif isinstance(change, SectionChange) and change.section in sections:
            sections[change.section] = sections[change.section].model_copy(
                update={"clearance_mode": change.clearance_mode}
            )
            ref = f"section:{change.section}.clearance_mode"
        else:
            continue
        facts[ref] = Fact(ref=ref, certainty=Certainty.CONFIRMED, origins=planner)
    questions = [q.model_copy(update={"answer": answers.get(q.id)}) for q in draft.questions]
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
    return draft.model_copy(
        update={
            "package": package.model_copy(
                update={
                    "places": list(places.values()),
                    "sections": list(sections.values()),
                    "trains": list(trains.values()),
                }
            ),
            "facts": list(facts.values()),
            "questions": questions,
            "rulebook": draft.rulebook.model_copy(update={"train_types": rules}),
        }
    )
