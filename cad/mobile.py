"""CAD i mobilen (#90, CAD1, CADMOB-12): Fota med mobilen's QR code and the phone's session.

The computer asks for a hand-off and shows its QR code: CAD's address with a one-time code in
the fragment, /m#k=<code>. A fragment never leaves the browser, so the code is in no server's or
proxy's log; the phone's page reads it, takes it out of the address and gives it to CAD in a
JSON body. The code is random (192 bits), used once, and lives ten minutes. CAD keeps only its
SHA-256, bound to the person who asked and, from a module's page, to the module.

Given the code, the phone gets a session of its own: a random key in an HttpOnly cookie,
SameSite=Strict, whose SHA-256 alone is kept, for two hours. It is the person's, with the
person's rights as CAD checks them at every call, but it reaches only the mobile flow's
addresses (MOBILE_ADDRESSES): the session, the gable profiles, a module's measures and its
approval, and the photos. A bound session reaches only its module and its photo jobs; an
unbound one only the modules the person makes from the phone after the code was given. The
computer can end it at any time, and it never becomes a full session.

Too many QR codes from one person, or too many wrong codes from one address, in ten minutes
are refused with 429. The addresses are kept in memory only, and never logged.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import parse_qs
from uuid import UUID

import segno
from psycopg import Connection
from psycopg.rows import DictRow

from cad.db import Database
from cad.errors import Refused, forbidden, not_found
from cad.library import Modules, Who
from cad.login import initials
from contracts.cad import (
    MOBILE_CODE_MINUTES,
    MOBILE_SESSION_HOURS,
    CadAccount,
    MobileFlow,
    MobileHandoff,
    MobileHandoffState,
    MobileProgress,
    MobileStart,
    MobileStep,
    ProblemCode,
)

COOKIE: Final = "cad_mobil"
CODE_LIFETIME: Final = timedelta(minutes=MOBILE_CODE_MINUTES)
SESSION_LIFETIME: Final = timedelta(hours=MOBILE_SESSION_HOURS)
KEPT_AFTER: Final = timedelta(days=1)
"""A hand-off row goes this long after its session or its code ended."""

WINDOW_SECONDS: Final = 600.0
MAX_HANDOFFS: Final = 10
"""QR codes one person may ask for in ten minutes."""
MAX_FAILED: Final = 20
"""Wrong or spent codes one address may give in ten minutes before it must wait."""

PATH: Final = "/m"
"""The phone's first page; the code follows in the fragment."""

QR_STYLE: Final = {"scale": 6, "border": 2, "dark": "#0e1114", "light": "#ffffff"}

_API: Final = "/api/cad/1"
_ID: Final = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

MOBILE_ADDRESSES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (method, re.compile(f"^{_API}{pattern}$"))
    for method, pattern in (
        ("GET", "/session"),
        ("GET", "/profiles"),
        ("GET", "/storage"),
        ("POST", "/modules"),
        ("GET", f"/modules/(?P<module>{_ID})"),
        ("PUT", f"/modules/(?P<module>{_ID})"),
        ("POST", f"/modules/(?P<module>{_ID})/approve"),
        ("POST", f"/modules/(?P<module>{_ID})/drawing/approve"),
        ("GET", "/photos/consent"),
        ("POST", "/photos"),
        ("GET", f"/photos/(?P<job>{_ID})"),
        ("POST", f"/photos/(?P<job>{_ID})/(?:read|orientation|answers)"),
        ("POST", f"/photos/(?P<job>{_ID})/questions/[a-z0-9][a-z0-9_.:-]{{0,79}}/closeup"),
    )
)
"""What the phone's session reaches (CADMOB-05, CADMOB-07): the measures, the gables, the photos
and the approval, through the same addresses as the web. Nothing else."""

EXPIRED: Final = (
    "Koden gäller inte längre. Den gäller en gång och i tio minuter. Visa en ny QR-kod med "
    "Fota med mobilen på datorn, eller logga in här."
)
OUTSIDE: Final = (
    "Mobilen når bara fotoflödet för modulen. Öppna CAD på datorn för resten, eller logga in här."
)
NO_SESSION: Final = "Mobilens session har gått ut. Visa en ny QR-kod på datorn."


def key_hash(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def qr_data(url: str) -> str:
    """The address as a QR code: an SVG as a data address, which CAD's own pages may show."""
    svg = segno.make(url, error="m").svg_inline(**QR_STYLE)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def too_many(what: str) -> Refused:
    return Refused(429, ProblemCode.TOO_MANY, what)


@dataclass(frozen=True)
class MobileSession:
    """A phone's session, as the key in its cookie gives it."""

    handoff: UUID
    person: UUID
    name: str
    bound: UUID | None
    opened_at: datetime
    expires_at: datetime

    @property
    def account(self) -> CadAccount:
        return CadAccount(id=self.person, name=self.name, initials=initials(self.name))


class Attempts:
    """Wrong codes per address in the last ten minutes, in memory only."""

    def __init__(self, most: int = MAX_FAILED, window: float = WINDOW_SECONDS) -> None:
        self.most = most
        self.window = window
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, address: str, now: float) -> deque[float]:
        found = self._seen.setdefault(address, deque())
        while found and found[0] <= now - self.window:
            found.popleft()
        return found

    def blocked(self, address: str) -> bool:
        with self._lock:
            now = time.monotonic()
            recent = self._recent(address, now)
            if not recent:
                self._seen.pop(address, None)
            return len(recent) >= self.most

    def failed(self, address: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._recent(address, now).append(now)
            if len(self._seen) > 10_000:
                # Forget the quiet ones rather than grow without end.
                quiet = [a for a, d in self._seen.items() if not d or d[-1] <= now - self.window]
                for gone in quiet:
                    del self._seen[gone]


class Handoffs:
    """The QR codes and the phones' sessions (contracts/cad.py, CAD i mobilen)."""

    def __init__(self, db: Database, modules: Modules, attempts: Attempts | None = None) -> None:
        self.db = db
        self.modules = modules
        self.attempts = attempts if attempts is not None else Attempts()

    # --- The computer -------------------------------------------------------------------------

    def create(self, who: Who, start: MobileStart, origin: str) -> MobileHandoff:
        """A QR code for the person, bound to the module when one is given and the person may
        change it. The address with the code is in this answer only."""
        if start.module is not None:
            module = self.modules.read(who, start.module)
            if not module.may_edit:
                raise forbidden()
        code = secrets.token_urlsafe(24)
        handoff = uuid.uuid4()
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM mobile_handoff WHERE created_at < now() - %s AND "
                "(session_expires_at IS NULL OR session_expires_at < now() - %s)",
                (KEPT_AFTER, KEPT_AFTER),
            )
            recent = conn.execute(
                "SELECT count(*) AS n FROM mobile_handoff WHERE person_id = %s "
                "AND created_at > now() - %s",
                (who.person, timedelta(seconds=WINDOW_SECONDS)),
            ).fetchone()
            if recent is not None and int(recent["n"]) >= MAX_HANDOFFS:
                raise too_many("För många QR-koder på kort tid. Vänta några minuter.")
            row = conn.execute(
                "INSERT INTO mobile_handoff (id, code_hash, person_id, bound_id, module_id, "
                "code_expires_at, step) VALUES (%s, %s, %s, %s, %s, now() + %s, %s) "
                "RETURNING *",
                (
                    handoff,
                    key_hash(code),
                    who.person,
                    start.module,
                    start.module,
                    CODE_LIFETIME,
                    (MobileStep.PHOTO if start.module else MobileStep.START).value,
                ),
            ).fetchone()
        assert row is not None
        url = f"{origin.rstrip('/')}{PATH}#k={code}"
        return self._handoff(dict(row)).model_copy(update={"url": url, "qr": qr_data(url)})

    def status(self, who: Who, handoff: UUID) -> MobileHandoff:
        """The hand-off as the computer follows it: only the person's own."""
        with self.db.transaction() as conn:
            row = self._own(conn, who, handoff)
        return self._handoff(row)

    def cancel(self, who: Who, handoff: UUID) -> MobileHandoff:
        """The computer ends it: the code can no longer be given, and the phone's session ends."""
        with self.db.transaction() as conn:
            self._own(conn, who, handoff)
            row = conn.execute(
                "UPDATE mobile_handoff SET ended_at = coalesce(ended_at, now()), "
                "updated_at = now() WHERE id = %s RETURNING *",
                (handoff,),
            ).fetchone()
        assert row is not None
        return self._handoff(dict(row))

    @staticmethod
    def _own(conn: Connection[DictRow], who: Who, handoff: UUID) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM mobile_handoff WHERE id = %s AND person_id = %s", (handoff, who.person)
        ).fetchone()
        if row is None:
            raise Refused(404, ProblemCode.NOT_FOUND, "QR-koden finns inte.")
        return dict(row)

    @staticmethod
    def _state(row: dict[str, Any], now: datetime) -> MobileHandoffState:
        if row["ended_at"] is not None:
            return MobileHandoffState.ENDED
        if row["opened_at"] is not None:
            if row["session_expires_at"] <= now:
                return MobileHandoffState.ENDED
            return MobileHandoffState.OPENED
        if row["code_expires_at"] <= now:
            return MobileHandoffState.EXPIRED
        return MobileHandoffState.WAITING

    def _handoff(self, row: dict[str, Any]) -> MobileHandoff:
        return MobileHandoff(
            id=row["id"],
            state=self._state(row, datetime.now(UTC)),
            bound=row["bound_id"],
            module=row["module_id"],
            job=row["job_id"],
            step=MobileStep(row["step"]) if row["opened_at"] is not None else None,
            created_at=row["created_at"],
            expires_at=row["code_expires_at"],
            opened_at=row["opened_at"],
        )

    # --- The phone ----------------------------------------------------------------------------

    def exchange(self, code: str, address: str) -> tuple[str, MobileFlow]:
        """The code for the phone's own session: once, within ten minutes. A wrong, spent or
        old code gets the same answer, and counts against the address."""
        if self.attempts.blocked(address):
            raise too_many("För många försök med fel kod. Vänta tio minuter och försök igen.")
        key = secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            row = conn.execute(
                "UPDATE mobile_handoff SET opened_at = now(), session_hash = %s, "
                "session_expires_at = now() + %s, updated_at = now() "
                "WHERE code_hash = %s AND opened_at IS NULL AND ended_at IS NULL "
                "AND code_expires_at > now() RETURNING *",
                (key_hash(key), SESSION_LIFETIME, key_hash(code)),
            ).fetchone()
        if row is None:
            self.attempts.failed(address)
            raise Refused(401, ProblemCode.LOGIN, EXPIRED)
        return key, self._flow(dict(row))

    def session(self, key: str | None) -> MobileSession | None:
        """The phone's session for the key in its cookie, while it holds."""
        if not key or len(key) > 200:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT h.id, h.person_id, h.bound_id, h.opened_at, h.session_expires_at, "
                "p.name FROM mobile_handoff h JOIN person p ON p.id = h.person_id "
                "WHERE h.session_hash = %s AND h.ended_at IS NULL "
                "AND h.session_expires_at > now()",
                (key_hash(key),),
            ).fetchone()
        if row is None:
            return None
        return MobileSession(
            handoff=row["id"],
            person=row["person_id"],
            name=str(row["name"]),
            bound=row["bound_id"],
            opened_at=row["opened_at"],
            expires_at=row["session_expires_at"],
        )

    def reaches(self, phone: MobileSession, module: UUID | None) -> bool:
        """May the phone's session work on the module? None: a new module, unbound only."""
        if module is None:
            return phone.bound is None
        if phone.bound is not None:
            return module == phone.bound
        with self.db.transaction() as conn:
            found = conn.execute(
                "SELECT 1 FROM module WHERE id = %s AND created_by = %s AND created_at >= %s "
                "AND removed_at IS NULL",
                (module, phone.person, phone.opened_at),
            ).fetchone()
        return found is not None

    def _job_module(self, job: UUID) -> UUID | None:
        with self.db.transaction() as conn:
            found = conn.execute("SELECT module_id FROM photo_job WHERE id = %s", (job,)).fetchone()
        return found["module_id"] if found is not None else None

    def allows(self, phone: MobileSession, method: str, path: str, query: str = "") -> bool:
        """Is the call one of the mobile flow's, on a module within the phone's reach?"""
        for allowed, pattern in MOBILE_ADDRESSES:
            match = pattern.match(path)
            if allowed != method or match is None:
                continue
            found = match.groupdict()
            if found.get("module"):
                return self.reaches(phone, UUID(found["module"]))
            if found.get("job"):
                module = self._job_module(UUID(found["job"]))
                return module is not None and self.reaches(phone, module)
            if path == f"{_API}/modules":
                return phone.bound is None
            if path == f"{_API}/photos/consent":
                asked = parse_qs(query).get("module", [])
                try:
                    return all(self.reaches(phone, UUID(m)) for m in asked)
                except ValueError:
                    return False
            return True
        return False

    def flow(self, phone: MobileSession) -> MobileFlow:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM mobile_handoff WHERE id = %s", (phone.handoff,)
            ).fetchone()
        if row is None:
            raise Refused(401, ProblemCode.LOGIN, NO_SESSION)
        return self._flow(dict(row))

    def progress(self, phone: MobileSession, step: MobileProgress) -> MobileFlow:
        """Where the phone is now, for the computer to follow. The module and the job must be
        within the phone's reach, and the job the module's."""
        if step.module is not None and not self.reaches(phone, step.module):
            raise not_found()
        if step.job is not None and (
            step.module is None or self._job_module(step.job) != step.module
        ):
            raise Refused(404, ProblemCode.NOT_FOUND, "Fotot finns inte.")
        with self.db.transaction() as conn:
            before = conn.execute(
                "SELECT module_id, job_id FROM mobile_handoff WHERE id = %s AND ended_at IS NULL "
                "FOR UPDATE",
                (phone.handoff,),
            ).fetchone()
            if before is None:
                raise Refused(401, ProblemCode.LOGIN, NO_SESSION)
            module = step.module if step.module is not None else before["module_id"]
            # The same module keeps its job until a new one; another module starts without one.
            if step.job is not None:
                job = step.job
            elif module == before["module_id"]:
                job = before["job_id"]
            else:
                job = None
            row = conn.execute(
                "UPDATE mobile_handoff SET step = %s, module_id = %s, job_id = %s, "
                "updated_at = now() WHERE id = %s RETURNING *",
                (step.step.value, module, job, phone.handoff),
            ).fetchone()
        if row is None:
            raise Refused(401, ProblemCode.LOGIN, NO_SESSION)
        return self._flow(dict(row))

    def end(self, phone: MobileSession) -> MobileFlow:
        """The phone is done: its session ends, and the computer sees the last step."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "UPDATE mobile_handoff SET ended_at = coalesce(ended_at, now()), "
                "updated_at = now() WHERE id = %s RETURNING *",
                (phone.handoff,),
            ).fetchone()
        assert row is not None
        return self._flow(dict(row))

    @staticmethod
    def _flow(row: dict[str, Any]) -> MobileFlow:
        return MobileFlow(
            handoff=row["id"],
            bound=row["bound_id"],
            module=row["module_id"],
            job=row["job_id"],
            step=MobileStep(row["step"]),
            expires_at=row["session_expires_at"],
            ended=row["ended_at"] is not None,
        )
