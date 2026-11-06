"""Boxes and station clients find their run by its code or their key, in the hub's meet or in
a Provbanan run. Each store keeps its own file; this asks them in turn, the meet first. The
hub's meet is asked for each time, since Byt träff may change it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from contracts import station
from contracts.terminal import DisplaySize
from drift.engine import Drift
from drift.store import MissingRun, PreviewStore, UnknownBox, UnknownClient

T = TypeVar("T")


class AnyRun:
    def __init__(self, *stores: Callable[[], PreviewStore]) -> None:
        self.stores = stores

    def _first(self, missing: type[Exception], ask: Callable[[PreviewStore], T]) -> T:
        for store in self.stores[:-1]:
            try:
                return ask(store())
            except missing:
                continue
        return ask(self.stores[-1]())

    def login(self, name: str, code: str, display: DisplaySize | None = None) -> tuple[str, str]:
        return self._first(MissingRun, lambda store: store.login(name, code, display))

    def box_frame(self, key: str) -> dict[str, Any]:
        return self._first(UnknownBox, lambda store: store.box_frame(key))

    def box_press(self, key: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._first(UnknownBox, lambda store: store.box_press(key, body))

    def connect(self, request: station.ConnectRequest) -> station.ConnectReply:
        return self._first(MissingRun, lambda store: store.connect(request))

    def connection(self, client_id: str) -> station.ConnectReply:
        return self._first(UnknownClient, lambda store: store.connection(client_id))

    def place_snapshot(self, key: str, place: str) -> station.Snapshot:
        return self._first(UnknownClient, lambda store: store.place_snapshot(key, place))

    def place_revision(self, key: str, place: str) -> int:
        return self._first(UnknownClient, lambda store: store.place_revision(key, place))

    def station_command(self, key: str, command: station.Command) -> station.Reply:
        return self._first(UnknownClient, lambda store: store.station_command(key, command))

    def screen_login(self, name: str, code: str) -> tuple[str, str]:
        return self._first(MissingRun, lambda store: store.screen_login(name, code))

    def screen_picture(self, key: str) -> tuple[str, str | None, Drift]:
        return self._first(UnknownClient, lambda store: store.screen_picture(key))
