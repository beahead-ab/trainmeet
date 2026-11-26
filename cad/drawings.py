"""Ladda upp ritning (#89 del c4, CAD6, CAD-31, STUDIO-01, STUDIO-03): a station's drawing read by
the image chain's profile Stationsritning (cad/bildkedjan/ritning*.py) into a ritningsavläsning
for Studio, as a job outside the request.

A drawing, in order:
1. The upload (start()): the file through the drawing's intake: a PDF's pages listed as vector
   or raster, an SVG, or a picture through the photo's intake (its metadata gone). The file is
   kept, not counted in the owner's 100 MB, for KEEP_DAYS. The same file uploaded again by the
   same person is the same job. The pages and the price are shown before anything is read.
2. Läs (read()): one page, with AI for a raster page's text or without. The first time a picture
   goes to AI, the person sees what is sent and to whom, and the yes is kept (as the photo's).
   The job's key is the file's checksum, the page, AI or not, and the reader's version: the same
   key is the stored read, at no cost.
3. The queue (work_once()) reads one job at a time. A vector page is read by code, free (R1). A
   raster page is straightened and its lines found by code; its text is transcribed by AI
   through TrainMeet ID's meter: reserved before, read with hold, the answer checked failing
   closed, then 12 tokens drawn the first time this page is transcribed, or everything given
   back (CAD3, CAD-29, TOKEN-09). The account's own AI costs nothing. The answer is kept as a
   transcript under its own question version, so the same page is never transcribed again (R2).
4. The read: the graph in the drawing's coordinates, the labels, the symbols, the boundaries, the
   questions with the legend first, and the straightened drawing as Studio's underlay (R3, R4).
   The owner's answers (answer()) change the read at once, without reading or paying again.

The chain never makes a station: Studio does, from the read, by the standard interlocking, and
everything is a proposal until the owner confirms it (TKL23, TKL27). The drawing and the AI's
answers are never written to the log.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import cv2
from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from cad.bildkedjan import intake, ritning, ritning_in
from cad.db import Database
from cad.errors import Refused, invalid
from cad.library import Who
from cad.meter import Meter, failed, no_tokens
from cad.store import Store, StoreFailed, new_key
from contracts.cad import (
    DrawingAi,
    DrawingAnswers,
    DrawingJob,
    DrawingJobState,
    DrawingPage,
    DrawingPageKind,
    DrawingPrice,
    DrawingRead,
    DrawingReadAsk,
    DrawingStart,
    DrawingUnderlay,
    ProblemCode,
    ReadBy,
)
from contracts.tokens import (
    TOKENS_PER_PAGE,
    MeterImage,
    MeterRead,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
    TokenReserve,
)

LOGGER = logging.getLogger("cad.drawings")

API = "/api/cad/1/drawings"
KEEP_DAYS: Final = 30
"""The drawing and its underlay are kept this long: Studio keeps its own model, not CAD's file."""
CONSENT_KIND: Final = "ai_drawing_consent"
CONSENT_VERSION: Final = "2026-11-26"
"""Asked again when what is sent, or to whom, changes: on 26 November the pictures went to
Anthropic's own API, outside the EU, instead of Bedrock in the EU."""
TRAINMEETS_AI: Final = "TrainMeets AI: Claude hos Anthropic, utanför EU"
MAX_TOKENS: Final = 6000
"""The transcription of a page with a few hundred texts."""
IDLE: Final = 5.0
SWEEP_EVERY: Final = timedelta(minutes=10)
UNDERLAY_SIDE: Final = 2400
STEPS: Final = {
    "prepare": (10, "Tar in ritningen"),
    "read": (40, "Läser linjer och symboler"),
    "ai": (60, "AI:n skriver av texten"),
    "assemble": (85, "Gör ritningsavläsningen"),
    "done": (100, "Klart"),
}
NAMES: Final = {"pdf": "Ritning.pdf", "svg": "Ritning.svg", "image": "Ritning.jpg"}
ENDINGS: Final = {"pdf": "pdf", "svg": "svg", "image": "jpg"}
KEPT: Final = "underlay_kept"
"""In the job's result: the underlay's size and transform, which the answers keep."""


def _now() -> datetime:
    return datetime.now(UTC)


def _bad(message: str, status: int = 422) -> Refused:
    return Refused(status, ProblemCode.BAD_DRAWING, message)


def _busy() -> Refused:
    return Refused(409, ProblemCode.BUSY, "Ritningen läses redan. Vänta tills det är klart.")


def _gone() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Ritningen finns inte, eller så är den inte din.")


def _sent(to: str) -> str:
    return (
        f"Ritningens sida, utan platsuppgifter och annan metadata, skickas till {to}. AI:n skriver "
        "bara av texten; spåren, växlarna och signalerna läser CAD själv."
    )


def job_key(sha256: str, page: int, ai: bool) -> str:
    """The job's key (bildkedjan, Jobbet är nyckeln): the file, the page, AI or not, and the
    reader's version. The same key, the same read."""
    data = {
        "file": sha256,
        "page": page,
        "ai": ai,
        "profile": ritning.PROFILE,
        "reader": ritning.READER_VERSION,
        "question": ritning_in.TRANSCRIPT_VERSION,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class Drawings:
    def __init__(self, db: Database, store: Store, meter: Meter | None) -> None:
        self.db = db
        self.store = store
        self.meter = meter
        self._wake = threading.Event()
        self._last_sweep = datetime.min.replace(tzinfo=UTC)

    # --- The consent and the price --------------------------------------------------------------

    def given(self, person: UUID) -> bool:
        with self.db.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM privacy_event WHERE person_id = %s AND kind = %s AND version = %s",
                (person, CONSENT_KIND, CONSENT_VERSION),
            ).fetchone()
        return found is not None

    def _ai(self, who: Who) -> DrawingAi:
        """Whether AI can transcribe here, what is sent and to whom, and the balance."""
        base = DrawingAi(
            available=False,
            given=self.given(who.person),
            version=CONSENT_VERSION,
            sent_to=TRAINMEETS_AI,
            text=_sent(TRAINMEETS_AI),
        )
        if self.meter is None:
            return base.model_copy(update={"message": "AI-avskriften kräver TrainMeet ID."})
        try:
            balance = self.meter.balance(who.person, self._payer(who.person))
        except Refused as refused:
            return base.model_copy(update={"message": refused.message})
        sent_to = f"din egen AI ({balance.own_ai})" if balance.own_ai else TRAINMEETS_AI
        return base.model_copy(
            update={
                "available": True,
                "sent_to": sent_to,
                "text": _sent(sent_to),
                "balance": balance.available,
            }
        )

    @staticmethod
    def _payer(person: UUID) -> TokenOwner:
        return TokenOwner(kind=TokenOwnerKind.PERSON, id=person)

    @staticmethod
    def _price(row: dict[str, Any], page: DrawingPage, ai: DrawingAi | None) -> DrawingPrice:
        if page.kind == DrawingPageKind.VECTOR:
            return DrawingPrice(
                tokens=0,
                why="vector",
                text="Gratis: sidan har ritade linjer och text, som koden läser utan AI.",
            )
        setup = row.get("setup") or {}
        if row["state"] == "done" and setup.get("page") == page.number and not setup.get("ai"):
            return DrawingPrice(tokens=0, why="no_ai", text="Utan AI: gratis, utan texten.")
        if row["paid"] and setup.get("page") == page.number:
            return DrawingPrice(tokens=0, why="same", text="Ingår: sidan är redan avskriven.")
        if ai is not None and ai.available and ai.sent_to != TRAINMEETS_AI:
            return DrawingPrice(tokens=0, why="own_ai", text="Din egen AI skriver av: gratis.")
        return DrawingPrice(
            tokens=TOKENS_PER_PAGE,
            why="first",
            text=f"{TOKENS_PER_PAGE} tokens för sidan när AI:n skriver av texten. Utan AI: "
            "gratis, utan texten. Samma sida igen: gratis.",
        )

    # --- Files --------------------------------------------------------------------------------

    def _put(
        self,
        conn: Connection[DictRow],
        job: UUID,
        owner: UUID,
        kind: str,
        data: bytes,
        ending: str,
        *,
        size: tuple[int, int] | None = None,
        sha: str | None = None,
    ) -> str:
        key = new_key(owner, ending)
        try:
            self.store.put(key, data)
        except StoreFailed as error:
            raise Refused(
                503, ProblemCode.UNAVAILABLE, "Ritningen kan inte sparas just nu."
            ) from error
        conn.execute(
            "INSERT INTO drawing_file (key, job_id, owner_id, kind, bytes, width, height, until, "
            "sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                key,
                job,
                owner,
                kind,
                len(data),
                size[0] if size else None,
                size[1] if size else None,
                _now() + timedelta(days=KEEP_DAYS),
                sha,
            ),
        )
        return key

    def _file(self, conn: Connection[DictRow], job: UUID, kind: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM drawing_file WHERE job_id = %s AND kind = %s AND removed_at IS NULL "
            "AND until > now() ORDER BY created_at DESC LIMIT 1",
            (job, kind),
        ).fetchone()
        return dict(row) if row else None

    def sweep(self) -> int:
        """The files past their day deleted. How many."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "UPDATE drawing_file SET removed_at = now() WHERE removed_at IS NULL AND "
                "until <= now() RETURNING key"
            ).fetchall()
        for row in rows:
            try:
                self.store.delete(str(row["key"]))
            except StoreFailed:
                LOGGER.warning("En ritning kunde inte tas bort nu; det försöks igen.")
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE drawing_file SET removed_at = NULL WHERE key = %s", (row["key"],)
                    )
        self._last_sweep = _now()
        return len(rows)

    # --- 1. The upload --------------------------------------------------------------------------

    def start(self, who: Who, start: DrawingStart, data: bytes) -> DrawingJob:
        """The drawing taken in and its pages listed; the job waits for Läs. The same file from
        the same person is the same job."""
        try:
            taken = ritning_in.take(data)
        except ritning_in.Refused as refused:
            raise _bad(refused.message, refused.status) from refused
        pages = [
            DrawingPage(
                number=p.number,
                kind=DrawingPageKind(p.kind),
                width=round(max(p.width, 1.0), 2),
                height=round(max(p.height, 1.0), 2),
                text=p.text,
                tokens=0 if p.kind == "vector" else TOKENS_PER_PAGE,
            )
            for p in taken.pages
        ]
        with self.db.transaction() as conn:
            same = conn.execute(
                "SELECT j.id FROM drawing_job j JOIN drawing_file f ON f.job_id = j.id "
                "AND f.kind = 'original' AND f.removed_at IS NULL AND f.until > now() "
                "WHERE j.person_id = %s AND j.sha256 = %s AND j.state <> 'failed' "
                "ORDER BY j.created_at DESC LIMIT 1",
                (who.person, taken.sha256),
            ).fetchone()
            if same is not None:
                return self._answer(self._row(conn, same["id"]), who)
            job = uuid.uuid4()
            info = {
                "name": start.name or NAMES[taken.format],
                "format": taken.format,
                "pages": [p.model_dump(mode="json") for p in pages],
            }
            conn.execute(
                "INSERT INTO drawing_job (id, person_id, person_name, sha256, key, state, start, "
                "chain) VALUES (%s, %s, %s, %s, %s, 'waiting', %s, %s)",
                (
                    job,
                    who.person,
                    who.name,
                    taken.sha256,
                    "0" * 64,
                    Jsonb(info),
                    ritning.READER_VERSION,
                ),
            )
            self._put(
                conn,
                job,
                who.person,
                "original",
                taken.file,
                ENDINGS[taken.format],
                sha=taken.sha256,
            )
        return self.job(who, job)

    # --- Reading the job ----------------------------------------------------------------------

    def _row(self, conn: Connection[DictRow], job: UUID) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM drawing_job WHERE id = %s", (job,)).fetchone()
        if row is None:
            raise _gone()
        return dict(row)

    def _own(self, who: Who, job: UUID) -> dict[str, Any]:
        """The job, only for the person who uploaded it."""
        with self.db.transaction() as conn:
            row = self._row(conn, job)
        if row["person_id"] != who.person:
            raise _gone()
        return row

    def job(self, who: Who, job: UUID) -> DrawingJob:
        return self._answer(self._own(who, job), who)

    def _answer(self, row: dict[str, Any], who: Who | None = None) -> DrawingJob:
        start = row["start"]
        pages = [DrawingPage.model_validate(p) for p in start["pages"]]
        setup = row["setup"] or {}
        number = int(setup.get("page") or 1)
        page = pages[min(number, len(pages)) - 1]
        ai = self._ai(who) if who is not None else None
        found = _read_of(row) if row["state"] == "done" else None
        return DrawingJob(
            id=row["id"],
            name=str(start["name"])[:120],
            state=DrawingJobState(row["state"]),
            progress=row["progress"],
            step=row["step"] or "Väntar på Läs",
            created_at=row["created_at"],
            format=start["format"],
            pages=pages,
            page=page.number,
            price=self._price(row, page, ai),
            ai=ai
            or DrawingAi(
                available=False,
                given=False,
                version=CONSENT_VERSION,
                sent_to=TRAINMEETS_AI,
                text=_sent(TRAINMEETS_AI),
            ),
            read=found,
            cost=row["cost"],
            chain=row["chain"],
            key=row["key"],
            message=row["message"],
        )

    # --- 2. Läs ---------------------------------------------------------------------------------

    def read(self, who: Who, job: UUID, ask: DrawingReadAsk) -> DrawingJob:
        """One page, with or without AI: the job waits in the queue, or the same read that was
        done before is given back."""
        row = self._own(who, job)
        if row["state"] in ("queued", "running"):
            raise _busy()
        pages = [DrawingPage.model_validate(p) for p in row["start"]["pages"]]
        if ask.page > len(pages):
            raise invalid(f"Ritningen har {len(pages)} sidor.")
        page = pages[ask.page - 1]
        use_ai = ask.ai and page.kind == DrawingPageKind.RASTER
        if use_ai:
            if self.meter is None:
                raise Refused(503, ProblemCode.UNAVAILABLE, "AI-avskriften kräver TrainMeet ID.")
            if not ask.consent and not self.given(who.person):
                raise Refused(
                    422,
                    ProblemCode.CONSENT_REQUIRED,
                    "Säg först ja till att ritningens sida skickas till AI:n.",
                )
        key = job_key(row["sha256"], ask.page, use_ai)
        with self.db.transaction() as conn:
            if use_ai and ask.consent:
                conn.execute(
                    "INSERT INTO privacy_event (person_id, kind, version) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (who.person, CONSENT_KIND, CONSENT_VERSION),
                )
            same = conn.execute(
                "SELECT id FROM drawing_job WHERE person_id = %s AND key = %s AND state = 'done' "
                "ORDER BY (id = %s) DESC, created_at DESC LIMIT 1",
                (who.person, key, job),
            ).fetchone()
            if same is not None:
                # The same drawing, page and input: the stored read, at no cost.
                return self._answer(self._row(conn, same["id"]), who)
            running = conn.execute(
                "SELECT 1 FROM drawing_job WHERE person_id = %s AND state IN ('queued', 'running')",
                (who.person,),
            ).fetchone()
            if running is not None:
                raise _busy()
            conn.execute(
                "UPDATE drawing_job SET state = 'queued', key = %s, setup = %s, progress = 0, "
                "step = 'I kön', message = NULL, answers = '{}'::jsonb, result = NULL, "
                "words = NULL, updated_at = now() WHERE id = %s",
                (key, Jsonb({"page": ask.page, "ai": use_ai}), job),
            )
        self.wake()
        return self.job(who, job)

    # --- 3. The queue ---------------------------------------------------------------------------

    def wake(self) -> None:
        self._wake.set()

    def run(self, stop: threading.Event) -> None:
        """The worker thread: the queue, one job at a time, and the sweep now and then."""
        self.recover()
        while not stop.is_set():
            try:
                busy = self.work_once()
                if _now() - self._last_sweep > SWEEP_EVERY:
                    self.sweep()
            except Exception as error:  # the database or the store, for a moment
                LOGGER.warning("Ritningskön stannade en stund: %s", type(error).__name__)
                busy = False
            if not busy and not stop.is_set():
                self._wake.wait(IDLE)
                self._wake.clear()

    def work(self) -> int:
        """The queue until it is empty: for the tests."""
        count = 0
        while self.work_once():
            count += 1
        return count

    def recover(self) -> int:
        """Jobs that were running when the process stopped wait again; their reservations go
        back."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "UPDATE drawing_job SET state = 'queued', step = 'I kön igen' "
                "WHERE state = 'running' RETURNING reservation"
            ).fetchall()
        for row in rows:
            if row["reservation"] is not None:
                self._give_back(row["reservation"])
        return len(rows)

    def work_once(self) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM drawing_job WHERE state = 'queued' ORDER BY updated_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE drawing_job SET state = 'running', updated_at = now() WHERE id = %s",
                (row["id"],),
            )
        job = dict(row)
        try:
            self._run(job)
        except (Refused, StoreFailed, ritning_in.Refused, intake.Refused) as error:
            self._fail(job, getattr(error, "message", None) or str(error))
        except Exception:
            LOGGER.exception("Ritningen kunde inte läsas.")
            self._fail(job, "Ritningen kunde inte läsas. Försök igen, eller ladda upp en bild.")
        return True

    def _fail(self, job: dict[str, Any], message: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE drawing_job SET state = 'failed', message = %s, step = 'Stannade', "
                "updated_at = now() WHERE id = %s",
                (message, job["id"]),
            )

    def _step(self, job: UUID, name: str) -> None:
        progress, text = STEPS[name]
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE drawing_job SET progress = %s, step = %s, updated_at = now() WHERE id = %s",
                (progress, text, job),
            )

    def _page(self, job: dict[str, Any], number: int) -> ritning_in.Page:
        """The page as code reads it, from the kept file: the drawing is read again, never what
        was made of it before."""
        with self.db.transaction() as conn:
            original = self._file(conn, job["id"], "original")
        if original is None:
            raise _bad("Ritningen finns inte längre. Ladda upp den igen.", 410)
        data = self.store.get(str(original["key"]))
        kind = job["start"]["format"]
        if kind == "pdf":
            page = ritning_in.pdf_pages(data, only=number)[0]
        elif kind == "svg":
            page = ritning_in.svg_page(data)
        else:
            page = ritning_in.take(data).pages[0]
        if page.kind == "raster":
            assert page.pixels is not None
            page = ritning_in.raster_page(page.pixels, number)
        return page

    def _run(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        setup = job["setup"] or {}
        number = int(setup.get("page") or 1)
        self._step(job_id, "prepare")
        self._step(job_id, "read")
        page = self._page(job, number)
        message: str | None = None
        if page.kind == "raster" and setup.get("ai"):
            self._step(job_id, "ai")
            try:
                page.words = self._transcribe(job, page)
            except Refused as refused:
                message = f"AI:n kunde inte skriva av texten: {refused.message}"
                page.words = []
        self._step(job_id, "assemble")
        pixels, transform = ritning.render(page, UNDERLAY_SIDE)
        if page.kind == "raster":
            ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 85])
            ending = "jpg"
        else:
            ok, encoded = cv2.imencode(".png", pixels)
            ending = "png"
        if not ok:
            raise _bad("Ritningen kunde inte ritas som underlag.")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE drawing_file SET removed_at = now() WHERE job_id = %s AND kind = "
                "'underlay' AND removed_at IS NULL",
                (job_id,),
            )
            self._put(
                conn,
                job_id,
                job["person_id"],
                "underlay",
                bytes(encoded.tobytes()),
                ending,
                size=(int(pixels.shape[1]), int(pixels.shape[0])),
            )
            kept = {"transform": list(transform), "size": [pixels.shape[1], pixels.shape[0]]}
            conn.execute(
                "UPDATE drawing_job SET words = %s, result = %s WHERE id = %s",
                (
                    Jsonb([_word_json(w) for w in page.words if w.read_by == ReadBy.AI]),
                    Jsonb({KEPT: kept}),
                    job_id,
                ),
            )
        self._assemble(job_id, page, {}, message)

    def _assemble(
        self, job_id: UUID, page: ritning_in.Page, answers: dict[str, str], message: str | None
    ) -> DrawingRead:
        """The read from the page and the owner's answers, kept as the job's result."""
        found = ritning.read(page, answers)
        made = ritning.assemble(found, page)
        with self.db.transaction() as conn:
            row = self._row(conn, job_id)
        kept = dict((row["result"] or {}).get(KEPT) or {})
        pages = [DrawingPage.model_validate(p) for p in row["start"]["pages"]]
        number = int((row["setup"] or {}).get("page") or 1)
        size = kept.get("size") or [1, 1]
        underlay = DrawingUnderlay(
            url=f"{API}/{job_id}/underlay",
            width=max(1, int(size[0])),
            height=max(1, int(size[1])),
            transform=ritning.underlay_matrix(tuple(kept.get("transform") or (1, 0, 0, 1, 0, 0))),
        )
        notes = list(made.notes)
        if message:
            notes.insert(0, message)
        read = DrawingRead(
            job=job_id,
            page=number,
            kind=DrawingPageKind(page.kind),
            graph=made.graph,
            boundaries=made.boundaries,
            questions=made.questions,
            underlay=underlay,
            summary=made.summary,
            price=_read_price(row, pages[number - 1]),
            cost=row["cost"],
            notes=notes,
        )
        stored = {**read.model_dump(mode="json"), KEPT: kept}
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE drawing_job SET state = 'done', progress = 100, step = %s, result = %s, "
                "answers = %s, updated_at = now() WHERE id = %s",
                (STEPS["done"][1], Jsonb(stored), Jsonb(answers), job_id),
            )
        LOGGER.info("En ritning är läst: %s", ritning.summary_json(found))
        return read

    # --- AI through ID's meter (R2) -------------------------------------------------------------

    def _transcribe(self, job: dict[str, Any], page: ritning_in.Page) -> list[ritning_in.Word]:
        """The page's text, from a stored transcript of the same picture and question, or from
        the meter: reserved before, drawn or given back after."""
        meter = self.meter
        if meter is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "AI-avskriften kräver TrainMeet ID.")
        picture, _ = ritning_in.ai_picture(page)
        checksum = hashlib.sha256(picture).hexdigest()
        with self.db.transaction() as conn:
            kept = conn.execute(
                "SELECT answer, model FROM photo_transcript WHERE checksum = %s AND question = %s "
                "ORDER BY created_at LIMIT 1",
                (checksum, ritning_in.TRANSCRIPT_VERSION),
            ).fetchone()
        if kept is not None:
            # The same page is never transcribed again: the transcript, at no cost.
            try:
                words = ritning_in.understand(str(kept["answer"]), page)
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE drawing_job SET model = %s WHERE id = %s",
                        (str(kept["model"]), job["id"]),
                    )
                return words
            except ritning_in.Unreadable:
                LOGGER.warning("En sparad avskrift av en ritning gick inte att läsa.")
        payer = self._payer(job["person_id"])
        balance = meter.balance(job["person_id"], payer)
        with self.db.transaction() as conn:
            paid = bool(self._row(conn, job["id"])["paid"])
        # A page already paid for is read again at no cost, but the meter reads no picture on
        # less than a picture's price: it is held while the meter reads, and all of it goes back.
        needed = 0 if balance.own_ai else TOKENS_PER_PAGE
        if needed > balance.available:
            raise no_tokens(needed, balance.available)
        reservation: TokenReservation | None = None
        try:
            reservation = meter.reserve(
                TokenReserve(
                    person=job["person_id"],
                    owner=payer,
                    amount=needed,
                    key=f"cad-ritning-{job['id']}-{checksum[:16]}",
                    what="Avskrift av en ritning till Studio",
                )
            )
            if reservation.state is not TokenReservationState.HELD:
                raise failed()
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE drawing_job SET reservation = %s WHERE id = %s",
                    (reservation.id, job["id"]),
                )
            answer = meter.read(
                MeterRead(
                    reservation=reservation.id,
                    prompt=ritning_in.transcript_prompt(),
                    images=[
                        MeterImage(media_type="image/jpeg", data=base64.b64encode(picture).decode())
                    ],
                    max_tokens=MAX_TOKENS,
                    hold=True,
                )
            )
            words = ritning_in.understand(answer.text, page)
            if not 0 <= answer.cost <= reservation.amount:
                raise ritning_in.Unreadable()
        except ritning_in.Unreadable:
            LOGGER.warning("AI-avskriften av en ritning följde inte formen.")
            if reservation is not None:
                self._give_back(reservation.id)
            raise failed("AI-avskriften kunde inte läsas. Inget drogs.") from None
        except Exception:
            if reservation is not None:
                self._give_back(reservation.id)
            raise
        cost = 0 if paid else answer.cost
        try:
            if cost:
                meter.draw(reservation.id, cost)
            else:
                self._give_back(reservation.id)
        except Refused:
            if self._give_back(reservation.id):
                raise
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO photo_transcript (checksum, question, model, answer) VALUES (%s, %s, "
                "%s, %s) ON CONFLICT DO NOTHING",
                (checksum, ritning_in.TRANSCRIPT_VERSION, answer.model, answer.text),
            )
            conn.execute(
                "UPDATE drawing_job SET model = %s, cost = cost + %s, paid = paid OR %s, "
                "reservation = NULL WHERE id = %s",
                (answer.model, cost, cost > 0 or bool(balance.own_ai), job["id"]),
            )
        return words

    def _give_back(self, reservation: UUID) -> bool:
        if self.meter is None:
            return True
        try:
            return self.meter.give_back(reservation)
        except Refused:
            LOGGER.warning("Ritningens reservation kunde inte lämnas tillbaka nu.")
            return True

    # --- 4. The answers, and the underlay ----------------------------------------------------

    def answer(self, who: Who, job: UUID, answers: DrawingAnswers) -> DrawingJob:
        """The owner's answers: the read made again from the same page and transcript, without
        reading or paying again."""
        row = self._own(who, job)
        if row["state"] != "done" or not row["result"]:
            raise Refused(409, ProblemCode.BUSY, "Ritningen är inte läst än.")
        found = _read_of(row)
        assert found is not None
        questions = {q.key: q for q in found.questions}
        given = dict(row["answers"] or {})
        for item in answers.answers:
            question = questions.get(item.key)
            if question is None:
                raise invalid("Frågan finns inte i den här avläsningen.")
            if item.answer not in {c.id for c in question.choices}:
                raise invalid("Svaret är inte ett av frågans val.")
            given[item.key] = item.answer
        page = self._page(row, found.page)
        page.words = (
            [_word_of(w) for w in row["words"] or []] if page.kind == "raster" else page.words
        )
        self._assemble(row["id"], page, given, None)
        return self.job(who, job)

    def underlay(self, who: Who, job: UUID) -> tuple[bytes, str]:
        """The straightened drawing, for Studio's underlay: the bytes and their type."""
        row = self._own(who, job)
        with self.db.transaction() as conn:
            found = self._file(conn, row["id"], "underlay")
        if found is None:
            raise _gone()
        key = str(found["key"])
        try:
            data = self.store.get(key)
        except StoreFailed as error:
            raise Refused(
                503, ProblemCode.UNAVAILABLE, "Underlaget går inte att läsa nu."
            ) from error
        return data, "image/png" if key.endswith(".png") else "image/jpeg"


def _read_price(row: dict[str, Any], page: DrawingPage) -> DrawingPrice:
    """What this read cost: nothing for a vector page or without AI, the tokens drawn when AI
    transcribed the page, nothing when its transcript was there already or own AI wrote it."""
    if page.kind == DrawingPageKind.VECTOR:
        return DrawingPrice(tokens=0, why="vector", text="Gratis: läst av koden utan AI.")
    if not (row["setup"] or {}).get("ai") or row["model"] is None:
        return DrawingPrice(tokens=0, why="no_ai", text="Gratis: utan AI:s avskrift. Inget drogs.")
    if row["cost"] > 0:
        return DrawingPrice(
            tokens=row["cost"], why="first", text=f"{row['cost']} tokens: AI:n skrev av sidan."
        )
    return DrawingPrice(
        tokens=0,
        why="same",
        text="Ingår: sidan var redan avskriven, eller din egen AI skrev av den.",
    )


def _read_of(row: dict[str, Any]) -> DrawingRead | None:
    """The job's read as kept, without what only CAD keeps with it."""
    if not row["result"] or "graph" not in row["result"]:
        return None
    return DrawingRead.model_validate({k: v for k, v in row["result"].items() if k != KEPT})


def _word_json(word: ritning_in.Word) -> dict[str, Any]:
    return {"text": word.text, "box": list(word.box)}


def _word_of(data: dict[str, Any]) -> ritning_in.Word:
    x0, y0, x1, y1 = (float(v) for v in data["box"])
    return ritning_in.Word(str(data["text"])[:80], (x0, y0, x1, y1), ReadBy.AI)
