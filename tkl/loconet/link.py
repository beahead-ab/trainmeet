"""One LocoNet, one message at a time (ported from cda-tkl's serial-gateway.mjs and transport.mjs).

- A message is written when the one before it has come back. A LocoBuffer and a BTLocoBridge
  echo every message as it went out on the bus, and only that complete echo counts as sent:
  neither opening the port nor a write that succeeded does. Without the echo within two
  seconds the link fails, and nothing is sent again by itself: an order that may have gone out
  is never repeated.
- A switch request is a pulse: the output on, and off again after 200 ms, as JMRI sends it and
  as Benny's monitoring showed (B0 … 10, the report, B0 … 00). The sender asks for on only.
- The queue holds at most 200 messages; a fuller one means LocoNet does not keep up, and the
  link fails.

The echo is not passed on: the bus saw TKL's own message. Everything else that comes is, in
frames, whole and checked.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from tkl.loconet.messages import (
    FrameError,
    FrameReader,
    SwitchRequest,
    decode,
    switch_request,
)
from tkl.loconet.transports import Transport, TransportError

ECHO_SECONDS: Final = 2.0
PULSE_SECONDS: Final = 0.2
MOST_QUEUED: Final = 200


class LinkError(Exception):
    """The link to LocoNet failed: the reason in Swedish."""


@dataclass
class Link:
    transport: Transport
    clock: Callable[[], float] = time.monotonic
    echo_seconds: float = ECHO_SECONDS
    pulse_seconds: float = PULSE_SECONDS
    on_sent: Callable[[bytes], None] = lambda _data: None
    on_error: Callable[[FrameError], None] = lambda _error: None
    _queue: list[bytes] = field(default_factory=list)
    _pending: bytes | None = None
    _pending_at: float = 0.0
    _pulses: list[tuple[float, bytes]] = field(default_factory=list)
    _reader: FrameReader = field(init=False)
    closed: bool = False

    def __post_init__(self) -> None:
        self._reader = FrameReader(self.on_error)

    def send(self, data: bytes) -> None:
        """Queue a message; it goes out when the one before has come back."""
        if self.closed:
            raise LinkError("LocoNet är inte anslutet.")
        if len(self._queue) >= MOST_QUEUED:
            raise LinkError("LocoNet hinner inte med: för många meddelanden i kö.")
        self._queue.append(data)
        message = _decoded(data)
        if isinstance(message, SwitchRequest) and message.on:
            off = switch_request(message.address, message.output, on=False)
            self._pulses.append((self.clock() + self.pulse_seconds, off))
        self._flush()

    def _flush(self) -> None:
        if self._pending is not None or not self._queue or self.closed:
            return
        data = self._queue.pop(0)
        self._pending, self._pending_at = data, self.clock()
        try:
            self.transport.write(data)
        except TransportError as error:
            raise LinkError(str(error)) from error
        self.on_sent(data)

    def receive(self, timeout: float = 0.0) -> list[bytes]:
        """The frames that have come, without TKL's own echo. LinkError when the port fails."""
        try:
            chunk = self.transport.read(timeout)
        except TransportError as error:
            raise LinkError(str(error)) from error
        found = []
        for data in self._reader.push(chunk):
            if self._pending is not None and data == self._pending:
                self._pending = None
                self._flush()
                continue
            found.append(data)
        return found

    def tick(self) -> None:
        """The pulses that are due, and the echo's deadline."""
        now = self.clock()
        if self._pending is not None and now - self._pending_at > self.echo_seconds:
            raise LinkError(
                f"LocoNet skickade inte tillbaka meddelandet inom {self.echo_seconds:g} sekunder. "
                "Kontrollera LocoBuffern eller BTLocoBridgen och att banan har ström."
            )
        due = [data for at, data in self._pulses if at <= now]
        self._pulses = [(at, data) for at, data in self._pulses if at > now]
        for data in due:
            if len(self._queue) < MOST_QUEUED:
                self._queue.append(data)
        self._flush()

    @property
    def idle(self) -> bool:
        return self._pending is None and not self._queue and not self._pulses

    def close(self) -> None:
        self.closed = True
        self._queue.clear()
        self._pulses.clear()
        self._pending = None
        self.transport.close()


def _decoded(data: bytes) -> object:
    try:
        return decode(data)
    except FrameError:
        return None
