"""Följaren (SYNK-10, SYNK-13): the Pi calls out to the cloud and follows a meet's versions.

The Pi always calls; nothing calls the Pi. It asks for the meet's versions with long-poll and
gets an answer when one is published, or when the wait is over. A version it does not have is
fetched as the bytes it was published as and kept only if they match the checksum. Every call
says which protocol it speaks (F19).

The calls go through a Call, so that the tests run two hubs in one process; on the Pi it is
urllib, with nothing to install.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import ValidationError

from contracts.drift import DriftEvent
from contracts.sync import (
    HEADER,
    PROTOCOL,
    Hello,
    Link,
    LinkRequest,
    RunAck,
    RunEvents,
    SentVersion,
    VersionList,
)
from synk.home import Homes
from synk.link import LinkError, Links, Reach, TooManyTries, WrongCode
from synk.store import SyncError, Versions

WAIT: Final = 25.0  # seconds the cloud holds a long-poll
PUSH: Final = 1.0  # seconds between rounds of drift events up to the cloud
BATCH: Final = 500  # drift events in one call
RETRY: Final = (2.0, 5.0, 15.0, 30.0)  # seconds between tries when the cloud does not answer
LOGGER = logging.getLogger("synk.follower")

# method, url, headers, body, timeout -> status, body
Call = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]


class Unreachable(Exception):
    """The cloud did not answer."""


@dataclass(frozen=True)
class Leading:
    """The run this hub leads: the meet, the version, the run and the version's checksum."""

    meet: str
    version: int
    run: str
    package: str


def urllib_call(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise Unreachable() from error


def check_address(address: str) -> str:
    """The cloud's address, without a trailing slash. HTTPS, except to a machine on the same
    network (a name without dots, .local, or a private address), where the key never crosses
    the internet."""
    parts = urlsplit(address.strip())
    host = (parts.hostname or "").casefold()
    if parts.scheme not in ("https", "http") or not host or parts.query or parts.fragment:
        raise LinkError("Skriv molnhubbens adress, till exempel https://test.hub.trainmeet.app.")
    if parts.scheme == "http" and not _nearby(host):
        raise LinkError("Molnhubbens adress ska börja med https://.")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def _nearby(host: str) -> bool:
    if "." not in host or host.endswith(".local") or host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _detail(body: bytes) -> str | None:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) else None


class Follower:
    def __init__(
        self,
        links: Links,
        versions: Versions,
        hello: Callable[[], Hello],
        call: Call = urllib_call,
        leading: Callable[[], Leading | None] = lambda: None,
        events_after: Callable[[str, int], list[DriftEvent]] = lambda run, seq: [],
        homes: Homes | None = None,
    ) -> None:
        self.links = links
        self.versions = versions
        self.hello = hello
        self.call = call
        self.leading = leading
        self.events_after = events_after
        self.homes = homes
        self._marks: dict[str, str] = {}
        self._acks: dict[str, int] = {}

    def _headers(self, key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json", HEADER: PROTOCOL}
        if key is not None:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def link(self, address: str, code: str) -> str:
        """Koppla Pi:n med koden från molnet. The meet it now follows. Raises LinkError."""
        base = check_address(address)
        body = LinkRequest(code=code, hello=self.hello()).model_dump_json().encode()
        try:
            status, answer = self.call(
                "POST", f"{base}/api/sync/1/link", self._headers(), body, 15.0
            )
        except Unreachable as error:
            raise LinkError("Molnhubben svarar inte på den adressen.") from error
        if status == 426:
            raise LinkError(
                "Molnhubben talar en annan version av synken. Uppdatera den som är äldst."
            )
        if status != 200:
            refused = {403: WrongCode, 429: TooManyTries}.get(status, LinkError)
            raise refused(_detail(answer) or "Molnhubben sa nej till kopplingen.")
        try:
            link = Link.model_validate_json(answer)
        except ValidationError as error:
            raise LinkError("Molnhubbens svar gick inte att läsa.") from error
        self.links.lead(base, link.key, link.meet, link.meet_name, link.hello)
        self._marks.pop(link.meet, None)
        self.follow(Reach(link.meet, base, link.key), wait=0)
        return link.meet

    def follow(self, reach: Reach, wait: float = WAIT) -> bool:
        """One round: the meet's versions, waiting up to wait seconds for a change, and the
        versions the Pi does not have. True if anything changed here."""
        now = datetime.now(UTC)
        meet = quote(reach.meet, safe="")
        url = (
            f"{reach.address}/api/sync/1/meets/{meet}/versions"
            f"?known={quote(self._marks.get(reach.meet, ''), safe='')}&wait={wait:g}"
        )
        try:
            status, answer = self.call("GET", url, self._headers(reach.key), None, wait + 15)
        except Unreachable:
            self.links.heard(reach.meet, now, "Molnhubben svarar inte.")
            raise
        if status in (401, 403, 404):
            self.links.heard(
                reach.meet,
                now,
                "Molnhubben känner inte längre den här Pi:n. Koppla om med en ny kod.",
            )
            return False
        if status == 426:
            self.links.heard(reach.meet, now, "Molnhubben talar en annan version av synken.")
            return False
        if status != 200:
            self.links.heard(reach.meet, now, f"Molnhubben svarade med fel {status}.")
            return False
        listed = VersionList.model_validate_json(answer)
        if self._home_here(reach, listed):
            return self._send_versions(reach, listed, now)
        changed = False
        for version in listed.versions:
            try:
                data = self._bytes(reach, version.number)
                changed |= self.versions.receive(version, data)
            except SyncError as error:
                self.links.heard(reach.meet, now, str(error))
                return changed
        self._marks[reach.meet] = listed.mark
        self.links.heard(reach.meet, now)
        return changed

    def _home_here(self, reach: Reach, listed: VersionList) -> bool:
        """Is this hub the meet's home (H35)? The cloud's word counts when it has moved the home
        since (Ta tillbaka hem)."""
        if self.homes is None:
            return False
        hello = self.hello()
        mine = self.homes.home(reach.meet, hello.hub_id, hello.hub_name)
        told = listed.home
        if told is not None and told.generation > mine.generation:
            self.homes.move(reach.meet, told.hub_id, told.hub_name, told.generation)
            return told.hub_id == hello.hub_id
        return mine.here and mine.generation > 0

    def _send_versions(self, reach: Reach, listed: VersionList, now: datetime) -> bool:
        """This hub is the home: the versions it published that the cloud lacks go up, and so
        does a withdrawal (SYNK-10)."""
        assert self.homes is not None
        hello = self.hello()
        generation = self.homes.home(reach.meet, hello.hub_id, hello.hub_name).generation
        there = {v.number: v for v in listed.versions}
        sent = False
        for version in self.versions.versions(reach.meet):
            known = there.get(version.number)
            if known is not None and (known.withdrawn is not None or version.withdrawn is None):
                continue
            _, data = self.versions.stored(reach.meet, version.number)
            body = SentVersion(generation=generation, version=version, package=data.decode())
            status, answer = self.call(
                "POST",
                f"{reach.address}/api/sync/1/meets/{quote(reach.meet, safe='')}/versions",
                self._headers(reach.key),
                body.model_dump_json().encode(),
                60.0,
            )
            if status != 200:
                problem = _detail(answer) or f"Molnhubben tog inte emot versionen ({status})."
                self.links.heard(reach.meet, now, problem)
                return sent
            sent = True
        self._marks.pop(reach.meet, None)  # the cloud's list changed: ask again at once
        self.links.heard(reach.meet, now)
        return sent

    def nudge(self, meet: str) -> None:
        """A version was published or withdrawn here: one round at once, in the background, so
        that the cloud has it within a second rather than after the long-poll."""
        reach = next((r for r in self.links.reaches() if r.meet == meet), None)
        if reach is not None:
            Thread(target=self._quietly, args=(reach,), name="synk-nu", daemon=True).start()

    def _quietly(self, reach: Reach) -> None:
        try:
            self.follow(reach, wait=0)
        except Exception:
            LOGGER.exception("Versionen kunde inte skickas till molnet")

    def send(self, meet: str, path: str, body: bytes) -> tuple[int, bytes]:
        """A call to the cloud about a meet the Pi follows, with its key. Raises LinkError."""
        reach = next((r for r in self.links.reaches() if r.meet == meet), None)
        if reach is None:
            raise LinkError("Pi:n följer inte den träffen.")
        try:
            return self.call(
                "POST", f"{reach.address}{path}", self._headers(reach.key), body, 120.0
            )
        except Unreachable as error:
            raise LinkError("Molnhubben svarar inte.") from error

    def _bytes(self, reach: Reach, number: int) -> bytes:
        """The version's bytes: kept here already, or fetched from the cloud."""
        try:
            return self.versions.stored(reach.meet, number)[1]
        except SyncError:
            pass
        meet = quote(reach.meet, safe="")
        status, data = self.call(
            "GET",
            f"{reach.address}/api/sync/1/meets/{meet}/versions/{number}",
            self._headers(reach.key),
            None,
            60.0,
        )
        if status != 200:
            raise SyncError(f"Version {number} gick inte att hämta ({status}).")
        return data

    # --- Under träffen: Pi:n leder och molnet följer (SYNK-04, DRIFT-12) ---------------------

    def push(self) -> int | None:
        """The run this hub leads, if its meet is followed from the cloud: the drift events the
        cloud does not have, in order, from its acknowledgement. The cloud's last seq, or None
        when there is no such run."""
        led = self.leading()
        reach = next((r for r in self.links.reaches() if led and r.meet == led.meet), None)
        if led is None or reach is None:
            return None
        ack = self._acks.get(led.run)
        while True:
            sent = [] if ack is None else self.events_after(led.run, ack)[:BATCH]
            body = RunEvents(version=led.version, package=led.package, run=led.run, events=sent)
            now = datetime.now(UTC)
            status, answer = self.call(
                "POST",
                f"{reach.address}/api/sync/1/meets/{quote(led.meet, safe='')}/runs",
                self._headers(reach.key),
                body.model_dump_json().encode(),
                30.0,
            )
            if status != 200:
                self.links.heard(
                    led.meet, now, _detail(answer) or f"Molnhubben tog inte emot läget ({status})."
                )
                return ack
            got = RunAck.model_validate_json(answer)
            self.links.keep_answers(led.meet, got.answers)
            self.links.heard(led.meet, now)
            caught_up = ack is not None and len(sent) < BATCH
            ack = self._acks[led.run] = got.ack
            if caught_up:
                return ack

    # --- In the background -------------------------------------------------------------------

    def run(self, stop: Event, wait: float = WAIT) -> None:
        """Follow every meet the Pi is linked to, one thread each, and send the run it leads,
        until stop."""
        threads: dict[str, Thread] = {}
        pushing = Thread(target=self._push_loop, args=(stop,), name="synk-upp", daemon=True)
        pushing.start()
        while not stop.is_set():
            for reach in self.links.reaches():
                if reach.meet not in threads or not threads[reach.meet].is_alive():
                    thread = Thread(
                        target=self._follow_meet,
                        args=(reach.meet, stop, wait),
                        name=f"synk-{reach.meet}",
                        daemon=True,
                    )
                    threads[reach.meet] = thread
                    thread.start()
            stop.wait(2.0)

    def _push_loop(self, stop: Event) -> None:
        tries = 0
        while not stop.wait(PUSH if tries == 0 else RETRY[min(tries, len(RETRY)) - 1]):
            try:
                self.push()
                tries = 0
            except Unreachable:
                tries += 1
            except Exception:
                LOGGER.exception("Läget kunde inte skickas till molnet")
                tries = len(RETRY)

    def _follow_meet(self, meet: str, stop: Event, wait: float) -> None:
        tries = 0
        while not stop.is_set():
            reach = next((r for r in self.links.reaches() if r.meet == meet), None)
            if reach is None:
                return  # Koppla bort
            try:
                self.follow(reach, wait)
                tries = 0
            except Unreachable:
                stop.wait(RETRY[min(tries, len(RETRY) - 1)])
                tries += 1
            except Exception:
                LOGGER.exception("Synken av träffen kunde inte ta sitt steg")
                stop.wait(RETRY[-1])
