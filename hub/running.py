"""The meet the hub runs: Provbanan or a published version from Planering (steg 4a).

Each running meet and version has a file of its own (spec 7: Drift has its own file per
running meet), so an import can never lock Drift. Byt träff starts a run in the new file and
makes it the hub's meet; boxes and clients of the meet before must join the new one with its
code (B14). Which meet runs is kept in a small file, so a restart keeps it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Final

from contracts.common import Weekday
from contracts.drift import ProposalStatus
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


class WithdrawnVersion(UnknownMeet):
    """A version withdrawn in Planering: it can no longer be started (PLAN-18)."""


class Running:
    def __init__(
        self, data_dir: Path, provbanan: MeetPackage, provbanan_key: str, planning: Planning
    ) -> None:
        self.data_dir = data_dir
        self.provbanan = provbanan
        self.provbanan_key = provbanan_key
        self.planning = planning
        self.state_path = data_dir / "drift" / "running.json"
        self._stores: dict[tuple[str, int], PreviewStore] = {}
        self._lock = Lock()
        self._looked_at: set[tuple[str, str, int]] = set()
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
        if meet != PROVBANAN and self.withdrawn(meet, version):
            raise WithdrawnVersion()
        with self._lock:
            store = self._store(meet, version)
            run_id = store.start(traffic_day, game_day, replace=True)
            self.meet, self.version = meet, version
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps({"meet": meet, "version": version}), encoding="utf-8"
            )
            return store, run_id

    def _package(self, meet: str, version: int) -> tuple[MeetPackage, str]:
        """The package and the key its runs carry: the checksum it was published with."""
        if meet == PROVBANAN:
            if version != 1:
                raise UnknownMeet()
            return self.provbanan, self.provbanan_key
        try:
            published = next(v for v in self.planning.versions(meet) if v.number == version)
            return self.planning.package(meet, version), published.checksum
        except (PlanningError, StopIteration) as error:
            raise UnknownMeet() from error

    def withdrawn(self, meet: str, version: int) -> bool:
        """Is the version withdrawn in Planering (PLAN-18)?"""
        if meet == PROVBANAN:
            return False
        try:
            return any(
                v.number == version and v.withdrawn is not None
                for v in self.planning.versions(meet)
            )
        except PlanningError:
            return False

    def latest(self, meet: str) -> int | None:
        """The newest version of the meet that is not withdrawn."""
        if meet == PROVBANAN:
            return None
        try:
            numbers = [v.number for v in self.planning.versions(meet) if v.withdrawn is None]
        except PlanningError:
            return None
        return max(numbers, default=None)

    def included(self, version: int) -> list[str]:
        """The driftändringar the planner took into the version: they fall away at the switch
        (H4). Taken before the version was published, that is."""
        if self.meet == PROVBANAN:
            return []
        try:
            published = next(
                (v.published for v in self.planning.versions(self.meet) if v.number == version),
                None,
            )
            if published is None:
                return []
            return [
                p.id
                for p in self.planning.proposals(self.meet)
                if p.status == ProposalStatus.TAKEN
                and p.answered is not None
                and p.answered <= published
            ]
        except PlanningError:
            return []

    def take_small_corrections(self) -> bool:
        """Små rättelser (F5, DRIFT-31): the newest version of the running meet is looked at
        once, and taken at once if it only corrects times and tracks of trains that have not
        run. True if it was taken."""
        meet = self.meet
        latest = self.latest(meet)
        if latest is None:
            return False
        store = self.store
        run_id = store.current()
        seen = (meet, run_id, latest)
        if seen in self._looked_at:
            return False
        self._looked_at.add(seen)
        return store.take_small_correction(run_id, latest, self.included(latest))

    def _versions(self, meet: str) -> Callable[[int], MeetPackage]:
        """The meet's versions for a switch in the running meet (DRIFT-29). A version is frozen,
        so each is read once; one withdrawn or not there is no version to switch to."""
        cache: dict[int, MeetPackage] = {}

        def read(number: int) -> MeetPackage:
            if number not in cache:
                try:
                    cache[number] = self.planning.package(meet, number)
                except PlanningError as error:
                    raise LookupError(number) from error
            return cache[number]

        return read

    def _store(self, meet: str, version: int) -> PreviewStore:
        key = (meet, version)
        if key not in self._stores:
            package, package_key = self._package(meet, version)
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
                packages=None if meet == PROVBANAN else self._versions(meet),
                lifetime=LIFETIME,
                max_runs=MAX_RUNS,
                max_actions=MAX_ACTIONS,
                version=version,
                package_key=package_key,
            )
        return self._stores[key]
