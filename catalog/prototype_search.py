"""Webbsökningen efter förebildens typuppgifter (#53 del b, CAT-11, CAT-166–CAT-172, CAT-219).
Ported from TrainCatalog's catalog/research_provider.py and catalog/research_views.py: the
rules for the sources (catalog/evidence.py, catalog/publishers.py) and what is done with a
search. The old code asked another provider and wrote the facts on a vehicle; here the search
goes through TrainMeet ID's meter to Claude's web search (C40), and fills the catalog, never a
vehicle (CAT-171).

What leaves Catalog is the marking and nothing else (CAT-166): the litt, the operator, the kind
and the field profile, with the keys, English labels and units of the fields to find, which come
from Catalog's own field register (catalog/prototype_fields.py). Never a picture, the person's
name or account, a vehicle's number or notes: the search is not tied to a vehicle at all. The
meter writes the prompt itself from that (id/search.py), and searches with Claude's web search
in Anthropic's API, outside the EU; Catalog never holds a key. The first time, the person sees
what is sent and to whom, and the yes is kept as a privacy event of its own (CAT-142).

A search is a reading record of the kind web search (0015_webbsokning.sql, CAT-143), and runs as
a reading does (catalog/reading.py):
1. Under the person's lock: a search that never finished is given up. The same id and marking
   give the stored search (CAT-144); one reading or search at a time per person, and at most 10
   searches an hour (CAT-146). Then the search is written down as pending.
2. Outside any transaction: 24 tokens are reserved from the person's own balance (CAT-172), and
   the meter searches with hold. The search always uses TrainMeet's key, also for an account
   with own AI, which has no web search.
3. The answer is checked by Catalog's own code (catalog/evidence.py): a value is kept only with
   a source from the real search whose excerpt holds it. Then the 24 tokens are drawn, and the
   search is done. Whatever fails gives the reservation back.

The result is a proposal for the person, who sends it to the review queue as it is or after
changing it (PrototypeProposal.search, catalog/prototypes.py): the evidence follows the fields,
and the reviewer sees each field's value, source, publisher and excerpt. When that proposal is
approved, the search's tokens come back (CAT-172, settle()); when it is rejected, they do not.

Without the key at the meter the search is not connected, and says so (CAT-219).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import ValidationError

from catalog import evidence
from catalog.db import Database
from catalog.fleet import Refused
from catalog.prototype_fields import BY_KEY, PROFILES
from catalog.prototypes import suggest
from catalog.reading import Readings, _failed, no_tokens, search_off, without_id
from contracts.catalog import (
    SEARCH_PRICE,
    FieldProfile,
    ProblemCode,
    PrototypeSearch,
    PrototypeSearchAsk,
    PrototypeSearchConsent,
    PrototypeSearchSummary,
    ReadingStatus,
)
from contracts.tokens import (
    MeterSearch,
    MeterSearchAnswer,
    MeterSearchField,
    MeterSearchState,
    TokenBalance,
    TokenOwner,
    TokenOwnerKind,
    TokenReservation,
    TokenReservationState,
    TokenReserve,
)

LOGGER = logging.getLogger("catalog.search")

PER_HOUR: Final = 10
"""Searches a person may start in an hour (CAT-146)."""
CONSENT_KIND: Final = "web_search_consent"
CONSENT_VERSION: Final = "2026-11-21"
"""The version of what the person says yes to (CAT-142, C40). A new text needs a new yes."""
SENT_TO: Final = "Claudes webbsökning hos Anthropic, utanför EU"
SENT: Final = (
    "Bara märkningen skickas: littera, bolag, slag och fältprofil. Inga bilder, inget namn, "
    "inget konto, inga fordonsnummer och inga anteckningar. Sökningen görs av Claudes "
    "webbsökning hos Anthropic och behandlas utanför EU."
)
NOT_SEARCHED: Final = frozenset({"litt", "operator", "description"})
"""The litt and the operator are the marking that is searched for, and the description is the
proposer's own words: the search fills the rest of the profile's fields."""
MOST_UNSENT: Final = 10
STOCKHOLM: Final = ZoneInfo("Europe/Stockholm")


class SearchMeter(Protocol):
    """TrainMeet ID's tokens and meter, as Catalog uses them for a web search
    (catalog/reading.py, IdMeter)."""

    def balance(self, person: UUID, owner: TokenOwner) -> TokenBalance: ...

    def reserve(self, asked: TokenReserve) -> TokenReservation: ...

    def search_state(self) -> MeterSearchState: ...

    def search(self, asked: MeterSearch) -> MeterSearchAnswer: ...

    def draw(self, reservation: UUID, amount: int) -> None: ...

    def give_back(self, reservation: UUID) -> bool: ...

    def refund(self, reservation: UUID) -> bool | None: ...


def wanted(profile: FieldProfile) -> list[str]:
    """The keys a search fills for the profile, in the profile's order."""
    return [key for key in PROFILES[profile].keys if key not in NOT_SEARCHED]


def fields_for(profile: FieldProfile) -> list[MeterSearchField]:
    """The fields as the meter gets them: the key, the English label, the unit and the kind,
    all from the field register."""
    labels = PROFILES[profile].labels
    return [
        MeterSearchField(
            key=key,
            label=labels.get(key, ("", BY_KEY[key].label_en))[1],
            unit=BY_KEY[key].unit,
            kind=BY_KEY[key].kind.value,
        )
        for key in wanted(profile)
    ]


def marking(ask: PrototypeSearchAsk, reservation: UUID) -> MeterSearch:
    """What is sent to the meter for the search: the marking, and nothing else (CAT-166)."""
    return MeterSearch(
        reservation=reservation,
        litt=ask.litt,
        operator=ask.operator,
        kind=ask.kind.value if ask.kind is not None else None,
        profile=ask.profile.value,
        fields=fields_for(ask.profile),
        hold=True,
    )


def _basis(person: UUID, ask: PrototypeSearchAsk) -> str:
    """What was searched: the marking, by the person."""
    kind = ask.kind.value if ask.kind is not None else ""
    text = "|".join((str(person), ask.litt, ask.operator, kind, ask.profile.value))
    return hashlib.sha256(text.encode()).hexdigest()


def _busy(message: str) -> Refused:
    return Refused(409, ProblemCode.READING_BUSY, message)


def _changed(message: str) -> Refused:
    return Refused(409, ProblemCode.CHANGED, message)


def no_search() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Sökningen finns inte.")


def source_text(searched_at: datetime) -> str:
    """What stands as the source of a proposal from a search: when, and where the sources are."""
    day = searched_at.astimezone(STOCKHOLM).date().isoformat()
    return f"Webbsökning {day}. Källorna står per fält."


class Searches:
    def __init__(
        self,
        db: Database,
        readings: Readings,
        meter: SearchMeter | None,
        *,
        per_hour: int = PER_HOUR,
    ) -> None:
        """readings are the readings of photos, which share the rule of one at a time per
        person and the giving up of what never finished. meter is TrainMeet ID's; without ID's
        API there is none, and no search."""
        self.db = db
        self.readings = readings
        self.meter = meter
        self.per_hour = per_hour

    # --- The consent, the price and the balance (CAT-142, CAT-172, CAT-219) --------------------

    def given(self, person: UUID) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM privacy_event WHERE person_id = %s AND kind = %s AND version = %s",
                (person, CONSENT_KIND, CONSENT_VERSION),
            ).fetchone()
        return row is not None

    def consent(self, person: UUID) -> PrototypeSearchConsent:
        """What is sent and to whom, the price and the balance, and whether the search can be
        used here at all. The person's searches that are not sent yet are listed, so that a
        search that was paid for is never lost."""
        unknown = PrototypeSearchConsent(
            available=False,
            given=self.given(person),
            version=CONSENT_VERSION,
            sent_to=SENT_TO,
            text=SENT,
            price=SEARCH_PRICE,
            unsent=self.unsent(person),
        )
        if self.meter is None:
            return unknown.model_copy(update={"message": "Webbsökningen kräver TrainMeet ID."})
        try:
            state = self.meter.search_state()
            if not state.available:
                return unknown.model_copy(update={"message": search_off().message})
            balance = self.meter.balance(person, _payer(person))
        except Refused as refused:
            return unknown.model_copy(update={"message": refused.message})
        return unknown.model_copy(
            update={
                "available": True,
                "balance": balance.available,
                "payer": balance.title,
                "own_ai": balance.own_ai,
            }
        )

    def unsent(self, person: UUID) -> list[PrototypeSearchSummary]:
        """The person's searches of the last 30 days that are not sent as a proposal yet."""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, result FROM reading WHERE person_id = %s AND kind = 'web_search' "
                "AND status = 'done' AND revision_id IS NULL "
                "AND created_at > now() - interval '30 days' ORDER BY created_at DESC LIMIT %s",
                (person, MOST_UNSENT),
            ).fetchall()
        found = []
        for row in rows:
            result: Mapping[str, Any] = row["result"]
            found.append(
                PrototypeSearchSummary(
                    id=row["id"],
                    litt=result["litt"],
                    operator=result.get("operator", ""),
                    searched_at=result["searched_at"],
                    fields=max(len(result.get("evidence", {})), 0),
                )
            )
        return found

    # --- A search ------------------------------------------------------------------------------

    def search(self, person: UUID, ask: PrototypeSearchAsk) -> PrototypeSearch:
        """Search the web for the marking's type data, for the person, who pays."""
        if self.meter is None:
            raise without_search()
        if not ask.consent and not self.given(person):
            raise Refused(
                422,
                ProblemCode.CONSENT_REQUIRED,
                "Säg först ja till att märkningen skickas till webbsökningen.",
            )
        try:
            # Checked as the meter will check it, before anything is reserved: a marking is a
            # litt and an operator, never a vehicle's number (contracts/tokens.py).
            marking(ask, ask.id)
        except ValidationError:
            raise Refused(
                422,
                ProblemCode.BAD_TYPE_DATA,
                "Sök på en littera och ett bolag, aldrig på ett fordonsnummer.",
            ) from None
        self.readings.give_up_old(person)
        stored = self._start(person, ask)
        if stored is not None:
            return self._live(stored)
        return self._live(self._run(person, ask))

    def get(self, person: UUID, search: UUID) -> PrototypeSearch:
        """One's own search again, as it is now: sent or not, and the tokens back or not."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT result FROM reading WHERE id = %s AND person_id = %s "
                "AND kind = 'web_search' AND status = 'done'",
                (search, person),
            ).fetchone()
        if row is None:
            raise no_search()
        return self._live(PrototypeSearch.model_validate(row["result"]))

    def _live(self, found: PrototypeSearch) -> PrototypeSearch:
        """The stored search with what has happened since: the proposal it was sent as, the
        tokens back, and a reviewed prototype that has the same litt and operator now."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT s.revision_id, s.refunded_at, r.prototype_id FROM reading s "
                "LEFT JOIN prototype_revision r ON r.id = s.revision_id WHERE s.id = %s",
                (found.id,),
            ).fetchone()
            existing = suggest(conn, found.litt, found.operator)
        if row is None:
            return found
        return found.model_copy(
            update={
                "revision": row["revision_id"],
                "prototype": row["prototype_id"],
                "refunded": row["refunded_at"] is not None,
                "existing": existing,
            }
        )

    def _start(self, person: UUID, ask: PrototypeSearchAsk) -> PrototypeSearch | None:
        """Under the person's lock: the stored search for the same id and marking, or a new
        pending one, or no (CAT-144, CAT-146)."""
        basis = _basis(person, ask)
        with self.db.owner_transaction(person) as conn:
            same = conn.execute(
                "SELECT person_id, basis, status, result, kind FROM reading WHERE id = %s",
                (ask.id,),
            ).fetchone()
            if same is not None:
                if (
                    same["person_id"] != person
                    or same["basis"] != basis
                    or same["kind"] != "web_search"
                ):
                    raise _changed(
                        "Sökningens id används redan för något annat. Starta en ny sökning."
                    )
                if same["status"] == ReadingStatus.DONE:
                    return PrototypeSearch.model_validate(same["result"])
                if same["status"] == ReadingStatus.PENDING:
                    raise _busy("Sökningen pågår redan. Vänta tills den är klar.")
                raise _changed("Sökningen är redan avslutad utan svar. Starta en ny.")
            running = conn.execute(
                "SELECT kind FROM reading WHERE person_id = %s AND status = 'pending'", (person,)
            ).fetchone()
            if running is not None:
                what = "sökning" if running["kind"] == "web_search" else "avläsning"
                raise _busy(f"En {what} pågår redan. Vänta tills den är klar.")
            hour = conn.execute(
                "SELECT count(*) AS started, ceil(extract(epoch FROM "
                "min(created_at) + interval '1 hour' - now())) AS wait "
                "FROM reading WHERE person_id = %s AND kind = 'web_search' "
                "AND created_at > now() - interval '1 hour'",
                (person,),
            ).fetchone()
            assert hour is not None
            if hour["started"] >= self.per_hour:
                wait = max(int(hour["wait"] or 60), 1)
                raise Refused(
                    429,
                    ProblemCode.TOO_MANY,
                    f"Högst {self.per_hour} webbsökningar i timmen. Försök igen om "
                    f"{(wait + 59) // 60} minuter.",
                    retry_after=wait,
                )
            if ask.consent:
                conn.execute(
                    "INSERT INTO privacy_event (person_id, kind, version) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (person, CONSENT_KIND, CONSENT_VERSION),
                )
            conn.execute(
                "INSERT INTO reading (id, owner_id, person_id, kind, basis, pictures, month, "
                "expires_at) VALUES (%s, %s, %s, 'web_search', %s, 0, "
                "to_char(now() AT TIME ZONE 'Europe/Stockholm', 'YYYY-MM'), now() + %s)",
                (ask.id, person, person, basis, self.readings.expires),
            )
        return None

    def _run(self, person: UUID, ask: PrototypeSearchAsk) -> PrototypeSearch:
        """Reserve, search with hold, check the answer, and draw."""
        meter = self.meter
        assert meter is not None
        payer = _payer(person)
        reservation: TokenReservation | None = None
        try:
            balance = meter.balance(person, payer)
            if balance.available < SEARCH_PRICE:
                raise no_tokens(SEARCH_PRICE, balance.available, what="webbsökningen", own=False)
            reservation = meter.reserve(
                TokenReserve(
                    person=person,
                    owner=payer,
                    amount=SEARCH_PRICE,
                    key=f"catalog-webbsokning-{ask.id}",
                    what=f"Webbsökning i Catalog: {ask.litt}",
                )
            )
            if reservation.state is not TokenReservationState.HELD:
                LOGGER.warning("Sökningens reservation var redan %s.", reservation.state.value)
                raise _failed("Webbsökningen kunde inte göras. Inget drogs. Försök igen.")
            self.readings.note(ask.id, reservation.id)
            answer = meter.search(marking(ask, reservation.id))
        except Exception:
            self.readings.end(ask.id, ReadingStatus.FAILED)
            if reservation is not None and reservation.state is TokenReservationState.HELD:
                self.readings.give_back(reservation.id)
            raise
        return self._finish(person, ask, reservation, answer)

    def _finish(
        self,
        person: UUID,
        ask: PrototypeSearchAsk,
        reservation: TokenReservation,
        answer: MeterSearchAnswer,
    ) -> PrototypeSearch:
        meter = self.meter
        assert meter is not None
        with self.db.owner_transaction(person) as conn:
            still = conn.execute(
                "SELECT status FROM reading WHERE id = %s FOR UPDATE", (ask.id,)
            ).fetchone()
        if still is None or still["status"] != ReadingStatus.PENDING:
            # Given up meanwhile, as after a restart: the answer is not used and costs nothing.
            self.readings.give_back(reservation.id)
            raise _changed("Sökningen avbröts, så svaret används inte. Inget drogs. Sök igen.")
        searched_at = datetime.now(UTC).replace(microsecond=0)
        try:
            if not 0 <= answer.cost <= reservation.amount:
                raise ValueError("cost")
            checked = evidence.check(
                ask.profile, wanted(ask.profile), answer.values, answer.results, searched_at
            )
            marked = {"litt": ask.litt} | ({"operator": ask.operator} if ask.operator else {})
            result = PrototypeSearch(
                id=ask.id,
                status=ReadingStatus.DONE,
                litt=ask.litt,
                operator=ask.operator,
                kind=ask.kind,
                profile=ask.profile,
                fields=marked | checked.fields,
                evidence=evidence.shown(checked.evidence, checked.fields),
                dropped=checked.dropped,
                sources=len(answer.results),
                cost=answer.cost,
                model=answer.model,
                searched_at=searched_at,
            )
        except ValueError:  # a contract's own limits (ValidationError is one)
            LOGGER.warning("Webbsökningens svar följde inte formen.")
            self.readings.end(ask.id, ReadingStatus.FAILED)
            self.readings.give_back(reservation.id)
            raise _failed("Webbsökningens svar kunde inte läsas. Inget drogs.") from None
        try:
            meter.draw(reservation.id, answer.cost)
        except Refused:
            if self.readings.give_back(reservation.id):
                self.readings.end(ask.id, ReadingStatus.FAILED)
                raise
            # ID says it is drawn: the draw got through, only its answer was lost.
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE reading SET status = 'done', result = %s WHERE id = %s",
                (result.model_dump_json(), ask.id),
            )
        return result

    # --- The proposal a search is sent as (CAT-171), and the tokens back (CAT-172) -------------

    def evidence_for(self, conn: Connection[DictRow], person: UUID, search: UUID) -> SentSearch:
        """In the proposer's transaction: the person's own search, done and not sent before,
        locked until the proposal is written. Its evidence is Catalog's own stored one, never
        what a browser sends."""
        row = conn.execute(
            "SELECT result, revision_id FROM reading WHERE id = %s AND person_id = %s "
            "AND kind = 'web_search' AND status = 'done' FOR UPDATE",
            (search, person),
        ).fetchone()
        if row is None:
            raise no_search()
        if row["revision_id"] is not None:
            raise _changed("Sökningen är redan skickad som ett förslag.")
        result: Mapping[str, Any] = row["result"]
        stored = {
            key: [
                {k: v for k, v in item.items() if k not in ("publisher", "agrees")}
                for item in items
            ]
            for key, items in result.get("evidence", {}).items()
        }
        return SentSearch(stored, source_text(datetime.fromisoformat(result["searched_at"])))

    @staticmethod
    def sent(conn: Connection[DictRow], search: UUID, revision: UUID) -> None:
        """In the proposer's transaction: the search is sent as this proposal, once."""
        conn.execute("UPDATE reading SET revision_id = %s WHERE id = %s", (revision, search))

    def settle(self) -> int:
        """Give back the tokens of every search whose proposal is approved (CAT-172): asked of
        TrainMeet ID once each, and again later when ID did not answer. How many came back."""
        if self.meter is None:
            return 0
        with self.db.transaction() as conn:
            due = conn.execute(
                "SELECT s.id, s.reservation FROM reading s JOIN prototype_revision r "
                "ON r.id = s.revision_id WHERE s.kind = 'web_search' AND s.status = 'done' "
                "AND s.refunded_at IS NULL AND s.reservation IS NOT NULL "
                "AND r.review = 'reviewed' ORDER BY r.reviewed_at LIMIT 50"
            ).fetchall()
        back = 0
        for row in due:
            try:
                done = self.meter.refund(row["reservation"])
            except Refused:
                LOGGER.warning("En sökning kunde inte lämnas tillbaka nu. Det görs senare.")
                continue
            with self.db.transaction() as conn:
                if done:
                    conn.execute(
                        "UPDATE reading SET refunded_at = now() WHERE id = %s", (row["id"],)
                    )
                    back += 1
                else:
                    # ID says the reservation is not one to refund: not asked again.
                    LOGGER.warning("ID lämnar inte tillbaka sökningen %s.", row["id"])
                    conn.execute(
                        "UPDATE reading SET reservation = NULL WHERE id = %s", (row["id"],)
                    )
        return back


class SentSearch:
    """What a proposal takes from the search it is sent from: the evidence as it is stored, and
    the text that stands as its source."""

    def __init__(self, evidence: dict[str, Any], source: str) -> None:
        self.evidence = evidence
        self.source = source


def without_search() -> Refused:
    refused = without_id()
    return Refused(refused.status, refused.code, "Webbsökningen kräver TrainMeet ID.")


def _payer(person: UUID) -> TokenOwner:
    """The person's own balance pays: a search fills the shared catalog, not a fleet."""
    return TokenOwner(kind=TokenOwnerKind.PERSON, id=person)
