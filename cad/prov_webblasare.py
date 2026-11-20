"""Startar CAD för webbläsarprovet, med en låtsad TrainMeet ID (#89 del a).

    python -m cad.prov_webblasare --databas <PostgreSQL> [--ny] [--port 8095]
        [--webb apps/cad/dist]

CAD körs på riktigt: sin riktiga databas, som migreras när den startar, och den byggda webbappen,
som CAD:s bild serverar den (CAD_WEB_DIR, cad/app.py). Inloggningen är provinloggningen med de
fasta provkontona.

TrainMeet ID är låtsat, inne i processen, som i cad/tests (httpx.MockTransport): CAD:s token,
klubbarna, appväxlaren och saldot. Provkonto A är administratör i Provklubben och Provkonto B
medlem, så att klubbens synlighet och rättigheter går att prova. Inget anropar ID på riktigt.

ID:s mätare för AI:n är också låtsad (PretendMeter, del c1): reservationer, mätaren med hold,
dragning och återlämning som i contracts/tokens.py, och en låtsad AI som svarar med fasta svar.
Utan --ai-svar svarar den som om fotot vore det syntetiska stationsfotot (cad/bildkedjan/
syntetisk.py, scenen station): spårens förbindelser som de är, och två växlar där koden ser en
korsning, så att provet får ett Osäkert parti att svara på. Andra moduler (del c2: kurvmodulen
och skissen) får raka förbindelser, A1–B1, A2–B2 och så vidare, och varje förstorat parti är en
korsning. Fotona sparas på disken i en egen mapp som tas bort efteråt.

Med --ny skapas en egen databas på servern i --databas, och den tas bort när programmet stannar,
så att provet alltid börjar från ett tomt bibliotek.

Körs av kontrollen "CAD:s bild", med apps/cad/e2e/bibliotek.mjs, och lokalt.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import secrets
import signal
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx
import psycopg
import uvicorn
from psycopg import conninfo

from cad.app import create_app
from cad.login import TRIAL_ACCOUNTS
from cad.settings import DEFAULT_WEB_DIR, IdSettings, Settings, package_version
from contracts.cad import CadVersion

LOGGER = logging.getLogger("cad.prov")

PERSON_A, PERSON_B = (account.id for account in TRIAL_ACCOUNTS[:2])
CLUB = UUID("5a1f0c3e-89a0-4d2b-9e1f-7a6b5c4d3e2f")
"""Provklubben: only in the browser test."""

STATION_ANSWER: Final = {
    "forbindelser": [
        ["A1", "B1"],
        ["A1", "B2"],
        ["A1", "E1"],
        ["A2", "B2"],
        ["A2", "E1"],
        ["A3", "B3"],
    ],
    "noder": {"X1": "tva-vaxlar"},
    "osakert": "Spåren som korsar varandra nära gavel B kan vara två växlar.",
}
"""The pretend AI's answer for the synthetic station (syntetisk.station_scene): its connections
as they are, and two switches where the code sees a crossing (Osäkert parti)."""

STATION_ENDS: Final = ["A1", "A2", "A3", "B1", "B2", "B3", "E1"]


def pretend_answer(prompt: str) -> str:
    """The pretend AI: the station's answer for the station's ends; for another module (part
    c2: the curve module and the sketch) each A track to the B track with its number, and every
    enlarged part a crossing."""
    ends_found = re.search(r"Märkta ändar: ([A-Z0-9, ]+)\.", prompt)
    ends = [e.strip() for e in ends_found.group(1).split(",")] if ends_found else []
    if sorted(ends) == STATION_ENDS:
        return json.dumps(STATION_ANSWER, ensure_ascii=False)
    nodes_found = re.search(r"förstorat parti \(([A-Z0-9, ]+)\)", prompt)
    nodes = [n.strip() for n in nodes_found.group(1).split(",")] if nodes_found else []
    pairs = [[e, "B" + e[1:]] for e in ends if e.startswith("A") and "B" + e[1:] in ends]
    return json.dumps(
        {"forbindelser": pairs, "noder": {n: "korsning" for n in nodes}, "osakert": ""},
        ensure_ascii=False,
    )


@dataclass
class PretendMeter:
    """ID's tokens and meter (contracts/tokens.py), pretended: the balance, reservations that
    hold the amount, the meter that reads with hold, and draw and give back."""

    balance: int = 86
    own_ai: str | None = None
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    reads: int = 0
    hard: list[bool] = field(default_factory=list)
    """Each read's hard flag: CAD's follow-up questions where code is not sure (CAD18)."""
    answer: Callable[[str], str] | None = None
    """What the AI says to a prompt; None: an empty answer, which CAD cannot read."""

    def meter_answer(self, request: httpx.Request, what: str) -> httpx.Response:
        now = datetime.now(UTC)

        def balance(owner: dict[str, str]) -> dict[str, Any]:
            return {
                "owner": owner,
                "title": "Provkonto",
                "free_left": 0,
                "free_monthly": 0,
                "bought": self.balance,
                "reserved": 0,
                "available": self.balance,
                "month": now.strftime("%Y-%m"),
                "own_ai": self.own_ai,
            }

        def made(found: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": found["id"],
                "owner": found["owner"],
                "amount": found["amount"],
                "drawn": found["drawn"],
                "state": found["state"],
                "what": found["what"],
                "at": now.isoformat(),
                "expires": (now + timedelta(minutes=30)).isoformat(),
                "balance": balance(found["owner"]),
            }

        if what == "tokens":
            kind, _, ident = request.url.params["owner"].partition(":")
            return httpx.Response(200, json=balance({"kind": kind, "id": ident}))
        body = json.loads(request.content) if request.content else {}
        if what == "tokens/reservations":
            existing = next(
                (r for r in self.reservations.values() if r["key"] == body["key"]), None
            )
            if existing is not None:
                return httpx.Response(200, json=made(existing))
            if int(body["amount"]) > self.balance:
                return httpx.Response(
                    402, json={"code": "no_tokens", "message": "Saldot räcker inte."}
                )
            self.balance -= int(body["amount"])
            found = {
                "id": str(uuid.uuid4()),
                "key": body["key"],
                "owner": body["owner"],
                "amount": int(body["amount"]),
                "drawn": 0,
                "state": "held",
                "what": body["what"],
            }
            self.reservations[found["id"]] = found
            return httpx.Response(201, json=made(found))
        if what == "meter":
            held = self.reservations.get(str(body["reservation"]))
            if held is None or held["state"] != "held":
                return httpx.Response(
                    409, json={"code": "conflict", "message": "Ingen reservation."}
                )
            cost = 0 if self.own_ai else 12 * len(body["images"])
            if held["amount"] < cost:
                # As ID's meter: no picture is read on less than its price (id/meter.py).
                return httpx.Response(
                    422, json={"code": "invalid", "message": "Reservationen räcker inte."}
                )
            self.reads += 1
            self.hard.append(bool(body.get("hard")))
            text = self.answer(body["prompt"]) if self.answer is not None else "{}"
            return httpx.Response(
                200,
                json={"text": text, "cost": cost, "model": "provmodell", "reservation": made(held)},
            )
        rid, _, action = what.removeprefix("tokens/reservations/").partition("/")
        kept = self.reservations.get(rid)
        if kept is None:
            return httpx.Response(404)
        if action == "draw":
            if kept["state"] == "held":
                amount = min(int(body.get("amount") or kept["amount"]), kept["amount"])
                self.balance += kept["amount"] - amount
                kept.update(state="drawn", drawn=amount)
            return httpx.Response(200, json=made(kept))
        if action == "return":
            if kept["state"] == "drawn":
                return httpx.Response(409)
            if kept["state"] == "held":
                self.balance += kept["amount"]
                kept["state"] = "returned"
            return httpx.Response(200, json=made(kept))
        return httpx.Response(404)


class PretendId:
    """Just enough of TrainMeet ID's API for CAD's pages, with its meter."""

    def __init__(self, tokens: int, answer: Callable[[str], str] | None) -> None:
        self.meter = PretendMeter(balance=tokens, answer=answer)
        self.clubs: dict[UUID, list[dict[str, str]]] = {
            PERSON_A: [{"id": str(CLUB), "name": "Provklubben", "role": "admin"}],
            PERSON_B: [{"id": str(CLUB), "name": "Provklubben", "role": "member"}],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "prov", "expires_in": 3600})
        what = path.removeprefix("/api/id/1/apps/")
        if what.startswith(("tokens/reservations", "meter")) or (
            what == "tokens" and request.url.params.get("owner")
        ):
            return self.meter.meter_answer(request, what)
        person = request.url.params.get("person", "")
        try:
            who = UUID(person)
        except ValueError:
            return httpx.Response(422)
        if what == "clubs":
            return httpx.Response(200, json=self.clubs.get(who, []))
        if what == "access":
            resource = request.url.params.get("resource", "")
            kind, _, ident = resource.partition(":")
            return httpx.Response(
                200, json={"person": person, "resource": {"kind": kind, "id": ident}, "roles": []}
            )
        if what == "switcher":
            return httpx.Response(200, json={"apps": ["hub", "tkl", "cad", "catalog", "id"]})
        if what == "tokens":
            return httpx.Response(200, json={"available": self.meter.balance})
        return httpx.Response(404)


def _wait_for(url: str, seconds: float = 60.0) -> None:
    """The database, as it starts beside the test: a fresh container takes a moment."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with psycopg.connect(url, connect_timeout=3):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


@contextmanager
def database(url: str, fresh: bool) -> Iterator[str]:
    """The database CAD runs against: as given, or a fresh one on the same server, removed
    afterwards."""
    _wait_for(url)
    if not fresh:
        yield url
        return
    name = f"cad_prov_{secrets.token_hex(6)}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield conninfo.make_conninfo(url, dbname=name)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def settings_for(database_url: str, port: int, web: Path, photos: Path) -> Settings:
    """CAD with the trial login and TrainMeet ID's API, which is the pretend one: its addresses
    are never reached, the transport answers them."""
    return Settings(
        database_url=database_url,
        migrate="auto",
        trial_login=True,
        web_dir=web,
        id=IdSettings(
            issuer="https://id.prov.invalid/realms/trainmeet",
            client="cad",
            secret=secrets.token_urlsafe(24),
            public_url=f"http://127.0.0.1:{port}",
            internal="http://id.prov.invalid/realms/trainmeet",
            api="http://id-api.prov.invalid",
        ),
        build=CadVersion(version=package_version()),
        photos_dir=photos,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--databas", required=True, help="PostgreSQL, t.ex. postgresql://...")
    parser.add_argument("--ny", action="store_true", help="en egen databas, borttagen efteråt")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--webb", type=Path, default=DEFAULT_WEB_DIR, help="den byggda webbappen")
    parser.add_argument("--tokens", type=int, default=86, help="provkontonas saldo")
    parser.add_argument(
        "--ai-svar",
        type=Path,
        default=None,
        help="den låtsade AI:ns svar som JSON; utan: svaret för det syntetiska stationsfotot",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # every call to the pretend ID
    if not (args.webb / "index.html").is_file():
        parser.error(f"Webbappen är inte byggd i {args.webb}: kör npm run build -w apps/cad.")
    if args.ai_svar:
        said = json.loads(args.ai_svar.read_text())
        pretend = PretendId(args.tokens, lambda _prompt: json.dumps(said, ensure_ascii=False))
    else:
        pretend = PretendId(args.tokens, pretend_answer)
    # uvicorn stops on SIGTERM and then raises it again: as an exit, so that the fresh database
    # is removed below.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with (
        database(args.databas, args.ny) as url,
        tempfile.TemporaryDirectory(prefix="cad-foton-") as photos,
    ):
        app = create_app(
            settings_for(url, args.port, args.webb, Path(photos)),
            id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
        )
        LOGGER.info("CAD med låtsad ID på http://127.0.0.1:%d", args.port)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
