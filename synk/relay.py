"""Reläet (SYNK-05, SYNK-11, SYNK-22): phones and the cloud's TKL reach the meet's hub through
the cloud.

Outside the meet's network a client calls the cloud hub; nothing calls the Pi (SYNK-13). The
cloud keeps the call in a queue for the hub it names, the hub fetches its calls on its own
connection (long-poll) and sends each answer back, and the cloud gives the answer to the
client as it came. Nothing of the traffic is kept: a call lives only until it is answered or
times out.

The queue is in memory and waits with short sleeps rather than futures, so that it works the
same whichever event loop or thread a request is served on.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Final

from contracts.sync import RelayAnswer, RelayCall

ANSWER: Final = 30.0  # seconds a client waits for the hub's answer
GONE: Final = 60.0  # seconds without a fetch before the hub counts as not connected
QUEUE: Final = 200  # calls waiting for one hub
TAKE: Final = 50  # calls handed over at a time
STEP: Final = 0.05  # seconds between looks


class RelayError(Exception):
    """The message is for the client."""

    status = 503


class NotConnected(RelayError):
    def __init__(self) -> None:
        super().__init__("Träffens hubb är inte ansluten till molnet just nu.")


class NoAnswer(RelayError):
    status = 504

    def __init__(self) -> None:
        super().__init__("Träffens hubb svarade inte i tid.")


class Busy(RelayError):
    status = 429

    def __init__(self) -> None:
        super().__init__("Reläet har för många anrop till träffens hubb just nu.")


@dataclass
class _Hub:
    heard: float = 0.0
    waiting: list[RelayCall] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)
    answers: dict[str, RelayAnswer] = field(default_factory=dict)


class Relay:
    def __init__(self) -> None:
        self._hubs: dict[str, _Hub] = {}
        self._lock = Lock()

    def _hub(self, hub_id: str) -> _Hub:
        return self._hubs.setdefault(hub_id, _Hub())

    def connected(self, hub_id: str) -> bool:
        """Has the hub fetched its calls lately?"""
        with self._lock:
            hub = self._hubs.get(hub_id)
            return hub is not None and time.monotonic() - hub.heard < GONE

    async def ask(self, hub_id: str, call: RelayCall, timeout: float = ANSWER) -> RelayAnswer:
        """A client's call, answered by the hub. Raises RelayError."""
        with self._lock:
            hub = self._hubs.get(hub_id)
            if hub is None or time.monotonic() - hub.heard >= GONE:
                raise NotConnected()
            if len(hub.waiting) + len(hub.taken) >= QUEUE:
                raise Busy()
            hub.waiting.append(call)
        deadline = time.monotonic() + timeout + call.wait
        try:
            while time.monotonic() < deadline:
                with self._lock:
                    answer = hub.answers.pop(call.id, None)
                if answer is not None:
                    return answer
                await asyncio.sleep(STEP)
            raise NoAnswer()
        finally:
            with self._lock:
                hub.answers.pop(call.id, None)
                hub.taken.discard(call.id)
                if call in hub.waiting:
                    hub.waiting.remove(call)

    async def take(self, hub_id: str, wait: float) -> list[RelayCall]:
        """The hub fetches its calls: at once if there are any, otherwise when one comes or
        the wait is over."""
        deadline = time.monotonic() + wait
        while True:
            with self._lock:
                hub = self._hub(hub_id)
                hub.heard = time.monotonic()
                calls, hub.waiting = hub.waiting[:TAKE], hub.waiting[TAKE:]
                hub.taken.update(call.id for call in calls)
            if calls or time.monotonic() >= deadline:
                return calls
            await asyncio.sleep(STEP)

    def answer(self, hub_id: str, answer: RelayAnswer) -> bool:
        """The hub's answer to a call it fetched. False if no client waits for it any more."""
        with self._lock:
            hub = self._hubs.get(hub_id)
            if hub is None or answer.id not in hub.taken:
                return False
            hub.taken.discard(answer.id)
            hub.answers[answer.id] = answer
            hub.heard = time.monotonic()
            return True
