"""USB-kopian (DRIFT-21): every drift event the hub accepts is also written to a USB stick, if
one is in, as a line of JSON, before Drift answers.

The run's own file is the truth; the stick is the copy to take home if the Pi's card dies. A
stick that is not there, is full or was pulled out never stops Drift: the copy is skipped, and
the change is said once in the log. When a stick comes back the copy goes on from the next
event; what came while it was out is in the run's file.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from contracts.drift import DriftEvent

LOGGER = logging.getLogger("drift.copy")
FOLDER = "trainmeet-drift"


@dataclass(frozen=True)
class CopyState:
    """How the copy goes: where, whether the last write went to the stick, and when."""

    root: str
    writing: bool
    last: datetime | None
    problem: str | None


class EventCopy:
    def __init__(self, root: Path, name: str) -> None:
        """root: where the stick is mounted. name: the meet's part of the file name."""
        self.root = root
        self.name = name
        self._lock = Lock()
        self._writing: bool | None = None
        self._last: datetime | None = None
        self._problem: str | None = None

    def write(self, run: str, events: list[DriftEvent]) -> bool:
        """Append the events to the run's file on the stick, and make sure they are on it.
        False when there is no stick, or it could not be written."""
        if not events:
            return bool(self._writing)
        with self._lock:
            try:
                if not self.root.is_dir() or not os.access(self.root, os.W_OK):
                    raise FileNotFoundError("Inget USB-minne")
                folder = self.root / FOLDER
                folder.mkdir(exist_ok=True)
                lines = "".join(event.model_dump_json() + "\n" for event in events)
                with open(folder / f"{self.name}-{run}.jsonl", "a", encoding="utf-8") as file:
                    file.write(lines)
                    file.flush()
                    os.fsync(file.fileno())
            except OSError as error:
                self._said(
                    False,
                    "Inget USB-minne"
                    if isinstance(error, FileNotFoundError)
                    else "USB-minnet gick inte att skriva till",
                )
                return False
            self._last = datetime.now(UTC)
            self._said(True, None)
            return True

    def _said(self, writing: bool, problem: str | None) -> None:
        if writing != self._writing:
            if writing:
                LOGGER.info("Drifthändelserna kopieras till USB-minnet")
            else:
                LOGGER.warning("%s: drifthändelserna kopieras inte just nu", problem)
        self._writing, self._problem = writing, problem

    def state(self) -> CopyState:
        with self._lock:
            return CopyState(str(self.root), bool(self._writing), self._last, self._problem)
