"""Push for the hub's meet (F20): once a second, the new drift events become notices to the
phones approved for their place. Only the hub that leads sends; a hub that follows is quiet,
and the leader's notices reach the phones the way they came."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from contracts import drift as events
from contracts.sync import Push
from drift.store import MissingRun
from hub.running import Running
from synk.push import FakePush, PushSender

KINDS: Final = {
    events.EventKind.CLEARANCE_REQUESTED,
    events.EventKind.CLEARANCE_REMINDED,
    events.EventKind.CLEARANCE_ANSWERED,
    events.EventKind.TRAIN_DEPARTED,
}


class Pusher:
    def __init__(self, running: Running, sender: PushSender) -> None:
        self.running = running
        self.sender = sender
        self._after: dict[str, int] = {}

    def round(self) -> int:
        """One round: how many pushes went out. A run seen for the first time starts from
        now, so nothing old is sent after a restart."""
        store = self.running.store
        try:
            run = store.current()
            fresh = store.events_after(run, self._after.get(run, 0))
        except MissingRun:
            return 0
        if not fresh:
            return 0
        after, last = self._after.get(run), fresh[-1].seq
        self._after[run] = last
        if after is None or store.leader(run) is not None:
            return 0
        if not any(event.kind in KINDS for event in fresh):
            return 0
        targets = store.push_targets(run)
        if not targets:
            return 0
        _, notices = store.notices(run, after)
        pushes = [
            Push(token=token, notice=notice)
            for notice in notices
            for token, places in targets
            if notice.place in places
        ]
        if pushes:
            self.sender.send(pushes)
        return len(pushes)


class Senders:
    """Which way the notices go: Apple's service when this hub has the key (the cloud),
    otherwise up to the cloud the meet is followed in (a Pi), otherwise the pretend service."""

    def __init__(
        self,
        apns: PushSender | None,
        cloud: PushSender,
        fake: FakePush,
        linked: Callable[[], bool],
    ) -> None:
        self.apns = apns
        self.cloud = cloud
        self.fake = fake
        self.linked = linked

    @property
    def own(self) -> PushSender:
        """The way out from this hub itself, for its own notices and a Pi's."""
        return self.apns if self.apns is not None else self.fake

    @property
    def name(self) -> str:
        return self.chosen().name

    def chosen(self) -> PushSender:
        if self.apns is None and self.linked():
            return self.cloud
        return self.own

    def send(self, pushes: list[Push]) -> None:
        self.chosen().send(pushes)
