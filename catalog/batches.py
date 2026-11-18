"""Flera foton i en omgång (#52 del b, CAT-146–CAT-153). Ported from TrainCatalog's
catalog_batch (models.py, views.py and worker.py).

A batch is up to 30 photos, one per vehicle (CAT-147). Each photo is a card of its own
(0011_omgangar.sql): a draft, not a vehicle. The cards are in tables of their own, so the
vehicle list, the sharing, the tags, the lookup, the trips and the export never see them
(CAT-148); only Godkänn alla makes vehicles of them.

A batch, in order:
1. The photos come, in one request or in several with the same batch id. Each is checked and
   made anew without metadata (catalog/pictures.py, CAT-123, CAT-124), and only that picture is
   kept, in the pictures' store, until the card is approved or removed. The original file's
   SHA-256 is kept with the card, unique per owner: the same file again gives the card it
   already is, in this batch or another (CAT-149).
2. The queue (work_once()) reads the waiting cards one at a time, in the order the batches and
   the photos came (CAT-147). Each is a reading of its own through catalog/reading.py: the same
   reservation, hold, draw and give-back as one reading, with its own limit of 30 an hour
   (CAT-146). The card is tied to its reading in the transaction that writes the reading down,
   and gets the suggestions in the one that ends it. The queue is the cards in the database, so
   a restart loses nothing (CAT-151): readings that never finished are given up and their
   reservations given back (recover()), and their cards fail, to be read again without
   anything drawn twice.
3. When ID says the tokens are not enough, the card and the batch's other waiting cards become
   manual, with a message (CAT-152). The hour's limit, the day's cap and a reading already
   running make the queue wait for the batch instead; it goes on by itself.
4. Godkänn alla (approve()) makes vehicles of every open card of the batch in one transaction
   under the owner's lock, or of none (CAT-150). Each gets the values the owner saw and kept
   (CAT-136), through the fleet's own checks, and its photo as its main picture. A photo left
   to fill in by hand, manual or failed, stops it while it has no kind, litt or number.

Only the owner reads with AI, and a club's administrators in the club's fleet (CAT-46).
Someone who edits a shared fleet leaves photos for the owner without AI (CAT-153): their cards
are manual from the start and cost no tokens, and they see only the batches they left, and
those cards only until they are approved.

The photos and the AI's answers are never written to the log.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from catalog.access import Work
from catalog.db import Database
from catalog.fleet import Fleet, Refused, ai_sources
from catalog.pictures import Kept, Pictures, Prepared, prepare
from catalog.prototypes import suggest
from catalog.reading import Readings, without_id
from contracts.catalog import (
    MAX_BATCH_PHOTOS,
    Batch,
    BatchApproval,
    BatchAsk,
    BatchCard,
    BatchCardChange,
    BatchCardStatus,
    BatchSummary,
    Confidence,
    ProblemCode,
    Reading,
    VehicleFields,
    VehicleStatus,
)

LOGGER = logging.getLogger("catalog.batches")

MAX_OPEN: Final = 60
"""Drafts an owner may have waiting for approval at once. They do not count in the storage
until they are approved, so this keeps what is stored unpaid within bounds: two full batches."""
IDLE: Final = 30.0
"""How long the queue sleeps, in seconds, when nothing waits: it wakes at once for a new batch
here, and finds the others' and the batches that waited for the hour within this time."""
WAIT_BUSY: Final = 30
"""Seconds the queue waits when the person is reading something else (CAT-146)."""
WAIT_CAP: Final = 3600
"""Seconds the queue waits when the day's cap in TrainMeet ID is reached (TK15)."""

BY_HAND: Final = "Utan AI: fyll i fälten för hand."
TOKENS_OUT: Final = "Tokens tog slut. Fyll i resten för hand eller köp tokens i TrainMeet ID."
CUT_OFF: Final = "Avläsningen avbröts. Läs av igen: inget dras två gånger."
NOT_READ: Final = "Fotot kunde inte läsas. Läs av igen, eller fyll i fälten för hand."
BUSY: Final = "En annan avläsning pågår. Omgången fortsätter strax."
CAP: Final = "Taket för tokens per dygn är nått i TrainMeet ID. Omgången fortsätter om en timme."
UNFILLED: Final = (
    "Ett foto att fylla i för hand saknar slag, littera och nummer. Fyll i det eller ta bort det."
)

_OPEN: Final = "status <> 'approved'"
_CARD: Final = (
    "id, batch_id, position, status, version, fields, suggestions, question, warnings, message, "
    "reading_id, attempts, width, height, bytes, display_key, thumb_key, vehicle_id"
)
_BY_HAND: Final = frozenset({BatchCardStatus.FAILED, BatchCardStatus.MANUAL})
"""A photo the AI did not read: filled in by hand before it is approved (CAT-152, CAT-153)."""
_FILLED: Final = frozenset(
    {BatchCardStatus.READY, BatchCardStatus.REVIEW, BatchCardStatus.FAILED, BatchCardStatus.MANUAL}
)


def _no_batch() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Omgången finns inte.")


def _no_card() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Fotot finns inte i omgången.")


def _changed(message: str) -> Refused:
    return Refused(409, ProblemCode.CHANGED, message)


def _empty() -> dict[str, Any]:
    return VehicleFields().model_dump(mode="json")


class Batches:
    def __init__(
        self,
        db: Database,
        readings: Readings,
        pictures: Pictures,
        *,
        max_open: int = MAX_OPEN,
        idle: float = IDLE,
    ) -> None:
        self.db = db
        self.readings = readings
        self.pictures = pictures
        self.max_open = max_open
        self.idle = idle
        self._wake = threading.Event()

    # --- Reading the batches ---------------------------------------------------------------

    def _batch(
        self, conn: Connection[DictRow], work: Work, batch: UUID, *, lock: bool = False
    ) -> DictRow:
        """The batch, as the right lets it be seen: the owner's every batch, someone else's only
        the ones they left (CAT-153)."""
        row = conn.execute(
            "SELECT id, owner_id, created_by, ai, club, created_at, "
            "CASE WHEN wait_until > now() THEN wait_until END AS wait_until, "
            "CASE WHEN wait_until > now() THEN wait_message END AS wait_message "
            "FROM batch WHERE id = %s AND owner_id = %s" + (" FOR UPDATE" if lock else ""),
            (batch, work.owner),
        ).fetchone()
        if row is None or not (work.own or row["created_by"] == work.person):
            raise _no_batch()
        return row

    def _card(self, row: DictRow, conn: Connection[DictRow] | None = None) -> BatchCard:
        """The card; with conn, also the reviewed prototype its litt and operator match now
        (CAT-141), only as a suggestion (CAT-136)."""
        picture = (
            self.pictures.links(row["display_key"], row["thumb_key"])
            if row["display_key"] is not None
            else None
        )
        card = BatchCard.model_validate(
            {
                "id": row["id"],
                "batch": row["batch_id"],
                "position": row["position"],
                "status": row["status"],
                "version": row["version"],
                "values": row["fields"],
                "suggestions": row["suggestions"],
                "question": row["question"],
                "warnings": row["warnings"],
                "message": row["message"],
                "picture": picture,
                "vehicle": row["vehicle_id"],
                "attempts": row["attempts"],
            }
        )
        if conn is None:
            return card
        found = suggest(conn, card.values.litt, card.values.operator)
        return card.model_copy(update={"prototype": found})

    def _read_card(
        self, conn: Connection[DictRow], work: Work, batch: UUID, card: UUID, *, lock: bool = False
    ) -> DictRow:
        row = conn.execute(
            f"SELECT {_CARD} FROM batch_card WHERE id = %s AND batch_id = %s"
            + (" FOR UPDATE" if lock else ""),
            (card, batch),
        ).fetchone()
        if row is None or (not work.own and row["status"] == BatchCardStatus.APPROVED):
            raise _no_card()
        return row

    def _shown(self, conn: Connection[DictRow], work: Work, row: DictRow) -> Batch:
        cards = conn.execute(
            f"SELECT {_CARD} FROM batch_card WHERE batch_id = %s"
            + ("" if work.own else f" AND {_OPEN}")
            + " ORDER BY position",
            (row["id"],),
        ).fetchall()
        return Batch(
            id=row["id"],
            ai=row["ai"],
            mine=row["created_by"] == work.person,
            created_at=row["created_at"],
            cards=[self._card(card, conn) for card in cards],
            waiting_until=row["wait_until"],
            message=row["wait_message"],
        )

    def get(self, work: Work, batch: UUID) -> Batch:
        with self.db.transaction() as conn:
            return self._shown(conn, work, self._batch(conn, work, batch))

    def batches(self, work: Work) -> list[BatchSummary]:
        """The batches with photos still to approve, newest first: the owner's all, someone
        else's only the ones they left, with only their cards not approved (CAT-153)."""
        mine_only = "" if work.own else " AND b.created_by = %(person)s"
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT b.id, b.ai, b.created_by, b.created_at, c.status FROM batch b "
                "JOIN batch_card c ON c.batch_id = b.id WHERE b.owner_id = %(owner)s"
                + mine_only
                + ("" if work.own else f" AND c.{_OPEN}")
                + " ORDER BY b.created_at DESC, b.id",
                {"owner": work.owner, "person": work.person},
            ).fetchall()
        found: dict[UUID, tuple[DictRow, dict[BatchCardStatus, int]]] = {}
        for row in rows:
            _, counts = found.setdefault(row["id"], (row, dict.fromkeys(BatchCardStatus, 0)))
            counts[BatchCardStatus(row["status"])] += 1
        return [
            BatchSummary(
                id=row["id"],
                ai=row["ai"],
                mine=row["created_by"] == work.person,
                created_at=row["created_at"],
                cards=sum(counts.values()),
                open=sum(counts.values()) - counts[BatchCardStatus.APPROVED],
                counts=counts,
            )
            for row, counts in found.values()
            if sum(counts.values()) > counts[BatchCardStatus.APPROVED]
        ]

    # --- The photos come (CAT-147, CAT-149) ---------------------------------------------------

    def add(self, work: Work, ask: BatchAsk, photos: Sequence[bytes], *, club: bool) -> Batch:
        """The photos, as cards of the batch: a new batch, or more photos for the same id. The
        same file as a card the owner has already gives that card, listed in already
        (CAT-149). The right is checked before: to edit at least (catalog/access.py)."""
        if not 1 <= len(photos) <= MAX_BATCH_PHOTOS:
            raise Refused(422, ProblemCode.BAD_PICTURE, f"Välj 1–{MAX_BATCH_PHOTOS} foton.")
        if ask.ai:
            if not work.own:  # CAT-46, CAT-153
                raise Refused(
                    403,
                    ProblemCode.FORBIDDEN,
                    "Bara ägaren läser av med AI. Lämna fotona till ägaren utan AI.",
                )
            if not self.readings.available:
                raise without_id()
            if not ask.consent and not self.readings.given(work.person):
                raise Refused(
                    422,
                    ProblemCode.CONSENT_REQUIRED,
                    "Säg först ja till att fotona skickas till AI:n.",
                )
        # Checked and made anew without metadata before anything is kept (CAT-123, CAT-124).
        # The hash is of the file as it came: the same file is the same draft (CAT-149).
        order: list[str] = []
        prepared: dict[str, Prepared] = {}
        for number, data in enumerate(photos, start=1):
            sha = hashlib.sha256(data).hexdigest()
            order.append(sha)
            if sha in prepared:
                continue
            try:
                prepared[sha] = prepare(data)
            except Refused as refused:
                raise Refused(
                    refused.status, refused.code, f"Foto {number}: {refused.message}"
                ) from None
        # A first look without a lock, so that a refused batch stores nothing.
        with self.db.transaction() as conn:
            self._same_batch(conn, work, ask)
            known = self._known(conn, work.owner, list(prepared))
            self._room(conn, work.owner, ask.id, sum(1 for sha in prepared if sha not in known))
        new = [sha for sha in prepared if sha not in known]

        def save(conn: Connection[DictRow], kept: list[Kept]) -> tuple[dict[str, UUID], set[str]]:
            # The decisive look, under the owner's lock (CAT-40).
            self._open_batch(conn, work, ask, club)
            found = self._known(conn, work.owner, list(prepared))
            fresh = [(sha, files) for sha, files in zip(new, kept, strict=True) if sha not in found]
            self._room(conn, work.owner, ask.id, len(fresh))
            row = conn.execute(
                "SELECT coalesce(max(position) + 1, 0) AS next FROM batch_card WHERE batch_id = %s",
                (ask.id,),
            ).fetchone()
            assert row is not None
            status = BatchCardStatus.WAITING if ask.ai else BatchCardStatus.MANUAL
            for position, (sha, files) in enumerate(fresh, start=row["next"]):
                conn.execute(
                    "INSERT INTO batch_card (id, batch_id, owner_id, position, status, sha256, "
                    "fields, message, width, height, bytes, display_key, thumb_key) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        uuid.uuid4(),
                        ask.id,
                        work.owner,
                        position,
                        status.value,
                        sha,
                        Jsonb(_empty()),
                        "" if ask.ai else BY_HAND,
                        files.width,
                        files.height,
                        files.bytes,
                        files.display_key,
                        files.thumb_key,
                    ),
                )
            if ask.ai and ask.consent:
                self.readings.agree(conn, work.person)
            held = {key for _, files in fresh for key in (files.display_key, files.thumb_key)}
            return found, held

        before = self.pictures.keep_drafts(work.owner, [prepared[sha] for sha in new], save)
        if ask.ai:
            self.wake()
        already = list(dict.fromkeys(before[sha] for sha in order if sha in before))
        return self.get(work, ask.id).model_copy(update={"already": already})

    def _same_batch(self, conn: Connection[DictRow], work: Work, ask: BatchAsk) -> DictRow | None:
        """The batch with the id, if it is there: the same person's in the same fleet, read
        the same way. Another's id is not taken over."""
        row = conn.execute(
            "SELECT owner_id, created_by, ai FROM batch WHERE id = %s", (ask.id,)
        ).fetchone()
        if row is not None and (
            row["owner_id"] != work.owner or row["created_by"] != work.person or row["ai"] != ask.ai
        ):
            raise _changed("Omgångens id används redan för något annat. Starta en ny omgång.")
        return row

    def _open_batch(self, conn: Connection[DictRow], work: Work, ask: BatchAsk, club: bool) -> None:
        conn.execute(
            "INSERT INTO batch (id, owner_id, created_by, ai, club) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (ask.id, work.owner, work.person, ask.ai, club),
        )
        conn.execute("SELECT 1 FROM batch WHERE id = %s FOR UPDATE", (ask.id,))
        self._same_batch(conn, work, ask)

    @staticmethod
    def _known(conn: Connection[DictRow], owner: UUID, hashes: list[str]) -> dict[str, UUID]:
        """The owner's cards that are these files already (CAT-149)."""
        rows = conn.execute(
            "SELECT sha256, id FROM batch_card WHERE owner_id = %s AND sha256 = ANY(%s)",
            (owner, hashes),
        ).fetchall()
        return {row["sha256"]: row["id"] for row in rows}

    def _room(self, conn: Connection[DictRow], owner: UUID, batch: UUID, more: int) -> None:
        """At most 30 photos in a batch (CAT-147), and at most MAX_OPEN drafts waiting for the
        owner's approval."""
        if more == 0:
            return
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE batch_id = %s) AS here, "
            f"count(*) FILTER (WHERE {_OPEN}) AS open FROM batch_card WHERE owner_id = %s",
            (batch, owner),
        ).fetchone()
        assert row is not None
        if row["here"] + more > MAX_BATCH_PHOTOS:
            raise Refused(
                422,
                ProblemCode.TOO_MANY_PICTURES,
                f"Högst {MAX_BATCH_PHOTOS} foton i en omgång. Starta en ny omgång för resten.",
            )
        if row["open"] + more > self.max_open:
            raise Refused(
                422,
                ProblemCode.TOO_MANY_PICTURES,
                f"Högst {self.max_open} utkast kan vänta på att godkännas. Godkänn eller ta "
                "bort några först.",
            )

    # --- The owner's changes ------------------------------------------------------------------

    def change(self, work: Work, batch: UUID, card: UUID, change: BatchCardChange) -> BatchCard:
        """The values of a card, as the owner writes them, built on the version seen (CAT-136).
        Someone who edits the fleet changes the cards they left, but the place stays the
        owner's (CAT-71). The values are checked as a vehicle's when the batch is approved."""
        with self.db.owner_transaction(work.owner) as conn:
            self._batch(conn, work, batch)
            row = self._read_card(conn, work, batch, card, lock=True)
            self._changeable(row)
            if row["version"] != change.version:
                raise _changed("Utkastet har ändrats. Öppna omgången igen.")
            values = change.values
            if not work.own:
                place = row["fields"].get("place")
                values = values.model_copy(update={"place": UUID(place) if place else None})
            changed = conn.execute(
                f"UPDATE batch_card SET fields = %s, version = version + 1 WHERE id = %s "
                f"RETURNING {_CARD}",
                (Jsonb(values.model_dump(mode="json")), card),
            ).fetchone()
            assert changed is not None
            return self._card(changed, conn)

    @staticmethod
    def _changeable(row: DictRow) -> None:
        if row["status"] == BatchCardStatus.APPROVED:
            raise _changed("Fotot är redan godkänt och är ett fordon nu.")
        if row["status"] in (BatchCardStatus.WAITING, BatchCardStatus.READING):
            raise Refused(409, ProblemCode.READING_BUSY, "Vänta tills fotot är läst.")

    def remove_card(self, work: Work, batch: UUID, card: UUID) -> None:
        """A card not approved, and its files with the next sweep. One being read now is not
        used when the answer comes, and costs nothing (CAT-145)."""
        with self.db.owner_transaction(work.owner) as conn:
            self._batch(conn, work, batch, lock=True)
            row = self._read_card(conn, work, batch, card, lock=True)
            if row["status"] == BatchCardStatus.APPROVED:
                raise _changed("Fotot är redan godkänt och är ett fordon nu.")
            if row["reading_id"] is not None:
                self.readings.discard(conn, [row["reading_id"]])
            conn.execute("DELETE FROM batch_card WHERE id = %s", (card,))
            conn.execute(
                "DELETE FROM batch WHERE id = %s AND NOT EXISTS "
                "(SELECT 1 FROM batch_card WHERE batch_id = %s)",
                (batch, batch),
            )

    def remove(self, work: Work, batch: UUID) -> None:
        """The batch's cards not approved, and their files with the next sweep. The vehicles
        made from it stay, and so does the batch, for them: their files are never two drafts
        (CAT-149)."""
        with self.db.owner_transaction(work.owner) as conn:
            self._batch(conn, work, batch, lock=True)
            gone = conn.execute(
                f"DELETE FROM batch_card WHERE batch_id = %s AND {_OPEN} RETURNING reading_id",
                (batch,),
            ).fetchall()
            self.readings.discard(
                conn, [row["reading_id"] for row in gone if row["reading_id"] is not None]
            )
            conn.execute(
                "DELETE FROM batch WHERE id = %s AND NOT EXISTS "
                "(SELECT 1 FROM batch_card WHERE batch_id = %s)",
                (batch, batch),
            )

    def retry(self, work: Work, batch: UUID, card: UUID) -> BatchCard:
        """A photo that could not be read, or was left when the tokens ran out, back in the
        queue (CAT-151, CAT-152). Only in a batch read with AI; the consent given for it
        holds."""
        if not self.readings.available:
            raise without_id()
        with self.db.owner_transaction(work.owner) as conn:
            found = self._batch(conn, work, batch, lock=True)
            row = self._read_card(conn, work, batch, card, lock=True)
            if not found["ai"]:
                raise _changed("Omgången läses inte med AI. Fyll i fälten för hand.")
            if row["status"] not in (BatchCardStatus.FAILED, BatchCardStatus.MANUAL):
                raise _changed("Bara ett foto som inte blev läst kan läsas av igen.")
            again = conn.execute(
                f"UPDATE batch_card SET status = 'waiting', message = '' WHERE id = %s "
                f"RETURNING {_CARD}",
                (card,),
            ).fetchone()
            assert again is not None
        self.wake()
        return self._card(again)

    # --- Godkänn alla (CAT-150) -----------------------------------------------------------------

    def approve(self, work: Work, batch: UUID, approval: BatchApproval, *, club: bool) -> Batch:
        """Every open card of the batch becomes a vehicle, in one transaction under the owner's
        lock, or none does (CAT-150). Only the owner, checked before. Each vehicle gets the
        card's values as the owner saw them, the AI as the source of a value it suggested and
        nobody changed, and the photo as its main picture, which from now on counts in the
        owner's storage (CAT-131): what that needs over the free level is paid first (CAT-132).
        """
        seen = {card.id: card.version for card in approval.cards}
        # A first look without a lock: nothing is paid for a batch that cannot be approved.
        with self.db.transaction() as conn:
            self._batch(conn, work, batch)
            rows = self._open_cards(conn, batch)
            self._judge(conn, work.owner, rows, seen)
        grow = sum(int(row["bytes"]) for row in rows)

        def save(conn: Connection[DictRow]) -> None:
            found = self._batch(conn, work, batch, lock=True)
            rows = self._open_cards(conn, batch, lock=True)
            self._judge(conn, work.owner, rows, seen)
            for row in rows:
                values = VehicleFields.model_validate(row["fields"])
                vehicle = Fleet.insert(
                    conn, work.owner, values, ai_sources(values, row["suggestions"])
                )
                kept = Kept(
                    row["display_key"], row["thumb_key"], row["width"], row["height"], row["bytes"]
                )
                Pictures.adopt(conn, work.owner, vehicle, kept, found["created_by"])
                conn.execute(
                    "UPDATE batch_card SET status = 'approved', vehicle_id = %s, approved_at = "
                    "now(), display_key = NULL, thumb_key = NULL, message = '', "
                    "version = version + 1 WHERE id = %s",
                    (vehicle, row["id"]),
                )

        self.pictures.save_within(work.owner, grow, club, save)
        return self.get(work, batch)

    @staticmethod
    def _open_cards(conn: Connection[DictRow], batch: UUID, *, lock: bool = False) -> list[DictRow]:
        return conn.execute(
            f"SELECT {_CARD} FROM batch_card WHERE batch_id = %s AND {_OPEN} ORDER BY position"
            + (" FOR UPDATE" if lock else ""),
            (batch,),
        ).fetchall()

    @staticmethod
    def _judge(
        conn: Connection[DictRow], owner: UUID, rows: list[DictRow], seen: dict[UUID, int]
    ) -> None:
        """Can every open card become a vehicle, as the owner saw it? Refused for all if not."""
        if any(BatchCardStatus(row["status"]) not in _FILLED for row in rows):
            raise Refused(409, ProblemCode.READING_BUSY, "Vänta tills alla foton är lästa.")
        if {row["id"]: row["version"] for row in rows} != seen:
            raise _changed(
                "Omgången har ändrats sedan den visades. Öppna den igen och godkänn på nytt."
            )
        stopped: list[tuple[UUID, Refused]] = []
        for row in rows:
            values = VehicleFields.model_validate(row["fields"])
            try:
                if row["status"] in _BY_HAND and not (values.kind or values.litt or values.number):
                    raise Refused(422, ProblemCode.NOT_READY, UNFILLED)
                Fleet.check(conn, owner, values)
            except Refused as refused:
                stopped.append((row["id"], refused))
        if stopped:
            first = stopped[0][1]
            many = "Ett utkast behöver" if len(stopped) == 1 else f"{len(stopped)} utkast behöver"
            raise Refused(
                422,
                first.code,
                f"Inget godkändes. {many} ändras först: {first.message}",
                cards=[card for card, _ in stopped],
            )

    # --- The queue (CAT-147, CAT-151, CAT-152) ----------------------------------------------------

    def wake(self) -> None:
        """Something waits in the queue: the worker starts at once instead of after IDLE."""
        self._wake.set()

    def run(self, stop: threading.Event) -> None:
        """The worker thread: the queue, one card at a time, until stop is set."""
        while not stop.is_set():
            try:
                busy = self.work_once()
            except Exception as error:  # the database or the store, for a moment
                LOGGER.warning("Kön för flera foton stannade en stund: %s", type(error).__name__)
                busy = False
            if not busy and not stop.is_set():
                self._wake.wait(self.idle)
                self._wake.clear()

    def work(self) -> int:
        """The queue until nothing waits that can be read now. How many cards were taken."""
        taken = 0
        while self.work_once():
            taken += 1
        return taken

    def recover(self) -> int:
        """Before each turn of the queue, and so after a restart (CAT-151): readings that never
        finished are given up and their reservations given back. A card whose reading is done
        gets its suggestions; one whose reading failed or is gone fails, to be read again, and
        nothing is drawn twice. How many cards were taken care of."""
        self.readings.recover()
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT c.id, r.status AS reading, r.result FROM batch_card c "
                "LEFT JOIN reading r ON r.id = c.reading_id "
                "WHERE c.status = 'reading' AND (r.id IS NULL OR r.status <> 'pending') "
                "FOR UPDATE OF c SKIP LOCKED"
            ).fetchall()
            for row in rows:
                if row["reading"] == "done":
                    self._apply(conn, row["id"], Reading.model_validate(row["result"]))
                else:
                    conn.execute(
                        "UPDATE batch_card SET status = 'failed', message = %s WHERE id = %s",
                        (CUT_OFF, row["id"]),
                    )
        if rows:
            LOGGER.info("Kön tog hand om %d avbrutna foton.", len(rows))
        return len(rows)

    def work_once(self) -> bool:
        """The first waiting card, in the order the batches and the photos came (CAT-147), read
        as a reading of its own. False when none can be read now."""
        self.recover()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT c.id, c.batch_id, c.display_key, b.owner_id, b.created_by, b.club "
                "FROM batch_card c JOIN batch b ON b.id = c.batch_id "
                "WHERE c.status = 'waiting' AND b.ai "
                "AND (b.wait_until IS NULL OR b.wait_until <= now()) "
                "ORDER BY b.created_at, b.id, c.position LIMIT 1"
            ).fetchone()
        if row is None:
            return False
        card, batch, reading = row["id"], row["batch_id"], uuid.uuid4()

        def claim(conn: Connection[DictRow]) -> bool:
            taken = conn.execute(
                "UPDATE batch_card SET status = 'reading', reading_id = %s, "
                "attempts = attempts + 1 WHERE id = %s AND status = 'waiting'",
                (reading, card),
            )
            conn.execute(
                "UPDATE batch SET wait_until = NULL, wait_message = NULL WHERE id = %s "
                "AND wait_until IS NOT NULL",
                (batch,),
            )
            return taken.rowcount == 1

        try:
            picture = self.pictures.fetch(row["display_key"])
            self.readings.read_for_batch(
                row["created_by"],
                row["owner_id"],
                reading,
                picture,
                club=row["club"],
                claim=claim,
                done=lambda conn, result: self._apply(conn, card, result),
            )
        except Refused as refused:
            self._refused(card, batch, reading, refused)
        except Exception as error:
            LOGGER.warning("Ett foto i en omgång kunde inte läsas: %s", type(error).__name__)
            self._fail(card, reading, NOT_READ)
        return True

    def _apply(self, conn: Connection[DictRow], card: UUID, result: Reading) -> None:
        """The reading's suggestions in the card's values, in the transaction that ends the
        reading. Ready when nothing needs checking, else to review (CAT-140)."""
        row = conn.execute(
            "SELECT fields FROM batch_card WHERE id = %s AND status = 'reading' "
            "AND reading_id = %s FOR UPDATE",
            (card, result.id),
        ).fetchone()
        if row is None:  # removed meanwhile
            return
        values = VehicleFields.model_validate(
            {**row["fields"], **{name: s.value for name, s in result.suggestions.items()}}
        )
        complete = values.kind is not None and bool(values.litt or values.number)
        status = VehicleStatus.READY if complete else VehicleStatus.DRAFT
        values = values.model_copy(update={"status": status})
        check = (
            not complete
            or bool(result.warnings)
            or result.question is not None
            or any(s.confidence is Confidence.LOW for s in result.suggestions.values())
        )
        conn.execute(
            "UPDATE batch_card SET status = %s, fields = %s, suggestions = %s, question = %s, "
            "warnings = %s, message = '', version = version + 1 WHERE id = %s",
            (
                (BatchCardStatus.REVIEW if check else BatchCardStatus.READY).value,
                Jsonb(values.model_dump(mode="json")),
                Jsonb({k: s.model_dump(mode="json") for k, s in result.suggestions.items()}),
                Jsonb(result.question.model_dump(mode="json")) if result.question else None,
                Jsonb(result.warnings),
                card,
            ),
        )

    def _refused(self, card: UUID, batch: UUID, reading: UUID, refused: Refused) -> None:
        """What ID's or Catalog's no means for the card and its batch. Only this turn's own
        reading is changed: another worker may have taken the card meanwhile."""
        if refused.code is ProblemCode.NO_TOKENS:
            # The tokens ran out: this photo and the rest are filled in by hand (CAT-152).
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE batch_card SET status = 'manual', message = %s WHERE batch_id = %s "
                    "AND (status = 'waiting' OR (status = 'reading' AND reading_id = %s))",
                    (TOKENS_OUT, batch, reading),
                )
            return
        if refused.status == 429 or refused.code is ProblemCode.READING_BUSY:
            # The hour's limit, the day's cap, or another reading now: the queue waits for the
            # batch and goes on by itself; nothing becomes manual (CAT-146).
            if refused.retry_after is not None:
                wait, message = refused.retry_after, refused.message
            elif refused.code is ProblemCode.READING_BUSY:
                wait, message = WAIT_BUSY, BUSY
            else:
                wait, message = WAIT_CAP, CAP
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE batch_card SET status = 'waiting', reading_id = NULL "
                    "WHERE id = %s AND status = 'reading' AND reading_id = %s",
                    (card, reading),
                )
                conn.execute(
                    "UPDATE batch SET wait_until = now() + make_interval(secs => %s), "
                    "wait_message = %s WHERE id = %s",
                    (wait, message, batch),
                )
            return
        if refused.code is ProblemCode.CHANGED:
            return  # removed while it was read: the answer was not used, nothing was drawn
        self._fail(card, reading, refused.message)

    def _fail(self, card: UUID, reading: UUID, message: str) -> None:
        """The card failed: still waiting, as when its photo could not be fetched, or read in
        this turn's own reading."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE batch_card SET status = 'failed', message = %s WHERE id = %s "
                "AND (status = 'waiting' OR (status = 'reading' AND reading_id = %s))",
                (message, card, reading),
            )
