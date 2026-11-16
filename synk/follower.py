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
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import ValidationError

from contracts.sync import HEADER, PROTOCOL, Hello, Link, LinkRequest, VersionList
from synk.link import LinkError, Links, Reach, TooManyTries, WrongCode
from synk.store import SyncError, Versions

WAIT: Final = 25.0  # seconds the cloud holds a long-poll
RETRY: Final = (2.0, 5.0, 15.0, 30.0)  # seconds between tries when the cloud does not answer
LOGGER = logging.getLogger("synk.follower")

# method, url, headers, body, timeout -> status, body
Call = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]


class Unreachable(Exception):
    """The cloud did not answer."""


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
    ) -> None:
        self.links = links
        self.versions = versions
        self.hello = hello
        self.call = call
        self._marks: dict[str, str] = {}

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

    # --- In the background -------------------------------------------------------------------

    def run(self, stop: Event, wait: float = WAIT) -> None:
        """Follow every meet the Pi is linked to, one thread each, until stop."""
        threads: dict[str, Thread] = {}
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
