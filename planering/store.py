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
from contracts.meet import Meet, MeetPackage, Place, Section
from contracts.planning import (
    PLANNER,
    Answer,
    Certainty,
    Change,
    Check,
    Draft,
    Fact,
    ImportPreview,
    ImportResult,
    MeetSummary,
    NewMeet,
    Origin,
    PlaceChange,
    SectionChange,
    SectionTracksChange,
    Source,
    Version,
)
from planering import compare
from planering.check import check

RESERVED: Final = {"provbanan"}
MAX_MEETS: Final = 200

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
"""


class PlanningError(Exception):
    """Something Planering cannot do. The message is for the planner."""

    status = 409


class UnknownMeet(PlanningError):
    status = 404


class UnknownVersion(PlanningError):
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

    def check(self, meet_id: str) -> Check:
        return Check(findings=check(self.draft(meet_id)))

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
        fresh = _laid_in(draft, source, result)
        self._save(db, fresh)
        return fresh

    def change(self, meet_id: str, *changes: Change) -> Draft:
        """The planner's changes, kept in order; the last change per field counts."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if draft.package is None:
                raise PlanningError("Lägg till underlag först.")
            places = {p.id for p in draft.package.places}
            sections = {s.id for s in draft.package.sections}
            kept = list(draft.changes)
            for change in changes:
                kind, target = _target(change)
                if target not in (places if kind == "place" else sections):
                    raise PlanningError("Det finns inte i utkastet.")
                kept = [c for c in kept if _target(c) != (kind, target)] + [change]
            draft = draft.model_copy(update={"changes": kept})
            answers = {q.id: q.answer for q in draft.questions if q.answer is not None}
            draft = _replay(draft, answers)
            self._save(db, draft)
            return draft

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
            draft = _replay(draft, answers)
            self._save(db, draft)
            return draft

    def publish(self, meet_id: str) -> Version:
        """The draft as the next version, with the traffic check's findings in it."""
        with self._transaction() as db:
            draft = self._draft(db, meet_id)
            if draft.package is None:
                raise PlanningError("Lägg till underlag innan du publicerar.")
            findings = check(draft)
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

    # --- Inside ------------------------------------------------------------------------------

    @staticmethod
    def _draft(db: sqlite3.Connection, meet_id: str) -> Draft:
        row = db.execute("SELECT draft FROM meet WHERE id=?", (meet_id,)).fetchone()
        if row is None:
            raise UnknownMeet("Träffen finns inte.")
        return Draft.model_validate_json(row[0])

    @staticmethod
    def _save(db: sqlite3.Connection, draft: Draft) -> None:
        db.execute(
            "UPDATE meet SET summary=?, draft=? WHERE id=?",
            (_summary(draft), draft.model_dump_json(), draft.meet.id),
        )

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
    return "section", change.section


def _laid_in(draft: Draft, source: Source, result: ImportResult) -> Draft:
    """The draft with the source in it, the meet's own name and dates kept, and the planner's
    changes and answers on top."""
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
        package=result.package.model_copy(update={"meet": meet}),
        facts=result.facts,
        rulebook=result.rulebook,
        sources=[s for s in draft.sources if s.kind != source.kind] + [source],
        questions=result.questions,
        report=result.report,
        changes=draft.changes,
    )
    return _replay(fresh, answers)


def _replay(draft: Draft, answers: Mapping[str, str]) -> Draft:
    """The planner's changes and answers on top of what the sources gave."""
    package = draft.package
    if package is None:
        return draft
    facts = {fact.ref: fact for fact in draft.facts}
    planner = [Origin(source=PLANNER, at="Planering")]
    places: dict[Id, Place] = {p.id: p for p in package.places}
    sections: dict[Id, Section] = {s.id: s for s in package.sections}
    for change in draft.changes:
        if isinstance(change, PlaceChange) and change.place in places:
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
                update={"places": list(places.values()), "sections": list(sections.values())}
            ),
            "facts": list(facts.values()),
            "questions": questions,
            "rulebook": draft.rulebook.model_copy(update={"train_types": rules}),
        }
    )
