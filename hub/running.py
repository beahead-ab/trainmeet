"""The meet the hub runs: Provbanan or a published version from Planering (steg 4a).

Each running meet and version has a file of its own (spec 7: Drift has its own file per
running meet), so an import can never lock Drift. Byt träff starts a run in the new file and
makes it the hub's meet; boxes and clients of the meet before must join the new one with its
code (B14). Which meet runs is kept in a small file, so a restart keeps it.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Final

from contracts.common import Weekday
from contracts.meet import MeetPackage
from drift.store import PreviewStore
from planering.store import Planning, PlanningError

PROVBANAN: Final = "provbanan"
LIFETIME: Final = timedelta(days=3650)
MAX_RUNS: Final = 64
MAX_ACTIONS: Final = 1_000_000
_SAFE = re.compile(r"^[a-z0-9-]{1,80}$")


class UnknownMeet(LookupError):
    """No such meet or version to run."""


class Running:
    def __init__(self, data_dir: Path, provbanan: MeetPackage, planning: Planning) -> None:
        self.data_dir = data_dir
        self.provbanan = provbanan
        self.planning = planning
        self.state_path = data_dir / "drift" / "running.json"
        self._stores: dict[tuple[str, int], PreviewStore] = {}
        self._lock = Lock()
        self.meet, self.version = PROVBANAN, 1
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.meet, self.version = str(saved["meet"]), int(saved["version"])
            self._package(self.meet, self.version)
        except (OSError, ValueError, KeyError, TypeError, UnknownMeet):
            self.meet, self.version = PROVBANAN, 1

    @property
    def store(self) -> PreviewStore:
        """The running meet's store."""
        with self._lock:
            return self._store(self.meet, self.version)

    def start(
        self, meet: str, version: int, traffic_day: Weekday | None, game_day: int
    ) -> tuple[PreviewStore, str]:
        """Start the meet and version as the hub's meet, in place of the one before."""
        with self._lock:
            store = self._store(meet, version)
            run_id = store.start(traffic_day, game_day, replace=True)
            self.meet, self.version = meet, version
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"meet": meet, "version": version}), encoding="utf-8"
            )
            return store, run_id

    def _package(self, meet: str, version: int) -> MeetPackage:
        if meet == PROVBANAN:
            if version != 1:
                raise UnknownMeet()
            return self.provbanan
        try:
            return self.planning.package(meet, version)
        except PlanningError as error:
            raise UnknownMeet() from error

    def _store(self, meet: str, version: int) -> PreviewStore:
        key = (meet, version)
        if key not in self._stores:
            package = self._package(meet, version)
            if meet == PROVBANAN:
                # The file the hub's meet has had since step 3.
                path = self.data_dir / "traff.sqlite3"
            else:
                if not _SAFE.match(meet):
                    raise UnknownMeet()
                path = self.data_dir / "drift" / f"{meet}-v{version}.sqlite3"
            self._stores[key] = PreviewStore(
                path,
                package,
                lifetime=LIFETIME,
                max_runs=MAX_RUNS,
                max_actions=MAX_ACTIONS,
                version=version,
            )
        return self._stores[key]
