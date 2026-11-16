"""Belastningsprovet (DRIFT-20, steg 5): many boxes and station clients against one hub at
once, as at a big meet, and how fast Drift answers them.

    uv run python -m deploy.belastning --hub http://localhost:8080 --pin 123456 --start

With --start it starts the hub's meet with Provbanan first. Never run it against a meet that is
on: the clients it makes are approved under Klienter like real ones. Each station client
fetches its snapshot every other second and looks up a train now and then; each box fetches
its frame every second. With --import FILE --meet MEET the file is imported into the meet
over and over at the same time, to see that an import never holds Drift up (DRIFT-20). At the
end: the answers per kind, the median, p95, p99 and the slowest, and the errors.

Only the standard library, so that it runs on a Pi as it is. No key is ever written out.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from typing import Any
from urllib.parse import quote


@dataclass
class Tally:
    seconds: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: Counter[str] = field(default_factory=Counter)
    lock: Lock = field(default_factory=Lock)

    def took(self, kind: str, spent: float, status: int) -> None:
        with self.lock:
            if 200 <= status < 300:
                self.seconds[kind].append(spent)
            else:
                self.errors[f"{kind} {status}"] += 1


class Hub:
    def __init__(self, base: str, tally: Tally) -> None:
        self.base = base.rstrip("/")
        self.tally = tally

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        key: str | None = None,
        kind: str | None = None,
        raw: bytes | None = None,
    ) -> tuple[int, Any]:
        headers = {
            "Content-Type": "application/json" if raw is None else "application/octet-stream"
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        began = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, answer = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, answer = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            status, answer = 599, b""
        if kind is not None:
            self.tally.took(kind, time.monotonic() - began, status)
        try:
            return status, json.loads(answer) if answer else None
        except ValueError:
            return status, None


def _must(answer: tuple[int, Any], what: str) -> Any:
    status, body = answer
    if not 200 <= status < 300:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise SystemExit(f"{what} gick inte ({status}): {detail or 'inget svar'}")
    return body


@dataclass
class Client:
    client_id: str
    place: str
    key: str


def station_clients(hub: Hub, admin: str, code: str, places: list[str], count: int) -> list[Client]:
    made = []
    for n in range(count):
        place = places[n % len(places)]
        request = {
            "kind": "tkl",
            "name": f"Belastning {n + 1}",
            "software": "belastning 1",
            "wants": [place],
            "code": code,
        }
        client_id = _must(hub.call("POST", "/api/station/1/connect", request), "Ansluta")[
            "client_id"
        ]
        approval = {"client_id": client_id, "places": [place]}
        _must(hub.call("POST", "/api/drift/1/clients/approve", approval, admin), "Godkänna")
        key = _must(hub.call("GET", f"/api/station/1/connect/{client_id}"), "Nyckeln")["key"]
        made.append(Client(client_id, place, key))
    return made


def run_client(hub: Hub, client: Client, stop: Event) -> None:
    round_ = 0
    stop.wait(random.uniform(0, 2))
    while not stop.is_set():
        status, snapshot = hub.call(
            "GET", f"/api/station/1/places/{client.place}", key=client.key, kind="ögonblicksbild"
        )
        round_ += 1
        if status == 200 and round_ % 5 == 0:
            command = {
                "message_id": f"belastning-{client.client_id}-{round_}",
                "client_id": client.client_id,
                "place": client.place,
                "context": snapshot["context"],
                "action": "train.lookup",
                "payload": {"train_number": str(random.randint(1, 300))},
            }
            hub.call("POST", "/api/station/1/commands", command, client.key, kind="kommando")
        stop.wait(2.0)


def run_box(hub: Hub, key: str, stop: Event) -> None:
    stop.wait(random.uniform(0, 1))
    while not stop.is_set():
        hub.call("GET", "/api/terminal/frame", key=key, kind="boxens bild")
        stop.wait(1.0)


def run_import(hub: Hub, admin: str, meet: str, data: bytes, name: str, stop: Event) -> None:
    """The file over and over, each time a little different at the end, so that the hub reads
    it anew: the worst case, an import that never stops."""
    path = f"/api/planering/1/meets/{quote(meet, safe='')}/sources?name={quote(name)}"
    round_ = 0
    while not stop.is_set():
        round_ += 1
        hub.call("POST", path, key=admin, kind="import", raw=data + f"\n%{round_}\n".encode())
        stop.wait(0.5)


def report(tally: Tally, seconds: float) -> str:
    lines = [f"Belastningsprovet, {seconds:.0f} sekunder", ""]
    lines.append(f"{'Anrop':<16}{'antal':>8}{'median':>10}{'p95':>10}{'p99':>10}{'längst':>10}")
    for kind, spent in sorted(tally.seconds.items()):
        ordered = sorted(spent)

        def at(share: float, ordered: list[float] = ordered) -> float:
            return ordered[min(len(ordered) - 1, int(share * len(ordered)))] * 1000

        lines.append(
            f"{kind:<16}{len(ordered):>8}{at(0.5):>8.0f}ms{at(0.95):>8.0f}ms"
            f"{at(0.99):>8.0f}ms{ordered[-1] * 1000:>8.0f}ms"
        )
    lines.append("")
    if tally.errors:
        lines.append("Fel: " + ", ".join(f"{k} × {n}" for k, n in sorted(tally.errors.items())))
    else:
        lines.append("Inga fel.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Belastningsprovet mot en hubb (DRIFT-20).")
    parser.add_argument("--hub", default="http://localhost:8080")
    parser.add_argument("--pin", required=True, help="Hubbens PIN-kod. Skrivs aldrig ut.")
    parser.add_argument("--start", action="store_true", help="Starta träffen med Provbanan.")
    parser.add_argument("--boxes", type=int, default=40)
    parser.add_argument("--clients", type=int, default=30)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--import", dest="imported", help="En fil att importera under tiden.")
    parser.add_argument("--meet", help="Träffen i Planering som filen importeras till.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Avsluta med fel om Drift gav ett enda fel, eller om p99 är över en sekund.",
    )
    args = parser.parse_args(argv)
    tally = Tally()
    hub = Hub(args.hub, tally)
    admin = _must(hub.call("POST", "/api/hub/login", {"pin": args.pin}), "Logga in")["session_key"]
    if args.start:
        _must(hub.call("POST", "/api/drift/1/start", {"version": 1}, admin), "Starta träffen")
    code = _must(hub.call("GET", "/api/drift/1/connect", key=admin), "Koden")["code"]
    package = _must(hub.call("GET", "/api/drift/1/package"), "Träffpaketet")
    places = [p["id"] for p in package["places"] if p["kind"] != "halt"]
    clients = station_clients(hub, admin, code, places, args.clients)
    boxes = [
        _must(
            hub.call("POST", "/api/terminal/session", {"name": f"Box {n + 1}", "code": code}),
            "En box",
        )["session_key"]
        for n in range(args.boxes)
    ]
    print(f"{len(clients)} stationsklienter och {len(boxes)} boxar mot {hub.base}.", flush=True)
    stop = Event()
    threads = [Thread(target=run_client, args=(hub, c, stop), daemon=True) for c in clients]
    threads += [Thread(target=run_box, args=(hub, key, stop), daemon=True) for key in boxes]
    if args.imported:
        if not args.meet:
            raise SystemExit("Säg vilken träff filen importeras till, med --meet.")
        with open(args.imported, "rb") as file:
            data = file.read()
        name = args.imported.rsplit("/", 1)[-1]
        threads.append(
            Thread(target=run_import, args=(hub, admin, args.meet, data, name, stop), daemon=True)
        )
    began = time.monotonic()
    for thread in threads:
        thread.start()
    stop.wait(args.seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=35)
    print(report(tally, time.monotonic() - began))
    return 1 if args.strict and not acceptable(tally) else 0


def acceptable(tally: Tally) -> bool:
    """Drift answered every call, and 99 of 100 within a second. The import's own answers do
    not count: a file the meet cannot take yet is told so."""
    if any(not kind.startswith("import") for kind in tally.errors):
        return False
    for kind, spent in tally.seconds.items():
        ordered = sorted(spent)
        if kind != "import" and ordered and ordered[int(0.99 * (len(ordered) - 1))] > 1.0:
            return False
    return True


if __name__ == "__main__":
    sys.exit(main())
