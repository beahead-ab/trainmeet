"""The meet the hub runs: Provbanan or a published version, kept by Synk (steg 4a, SYNK-08).

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
from drift.engine import Refused, now_utc
from drift.store import MissingRun, PreviewStore
from planering.store import Planning, PlanningError
from synk.follower import Leading
from synk.store import SyncError, Versions, newer

PROVBANAN: Final = "provbanan"
LIFETIME: Final = timedelta(days=3650)
MAX_RUNS: Final = 64
MAX_ACTIONS: Final = 1_000_000
# A run another hub leads and was heard from this recently is followed, never started anew
# (SYNK-14): two hubs never decide for the same meet.
FOLLOW_WINDOW: Final = timedelta(minutes=5)
_SAFE = re.compile(r"^[a-z0-9-]{1,80}$")


class UnknownMeet(LookupError):
    """No such meet or version to run."""


class WithdrawnVersion(UnknownMeet):
    """A version withdrawn in Planering: it can no longer be started (PLAN-18)."""


class NeedsNewerHub(UnknownMeet):
    """The version needs a newer hub than this one (GRUND-18)."""

    def __init__(self, needed: str, running: str) -> None:
        super().__init__(
            f"Versionen kräver Hubben {needed} eller nyare. Den här hubben är {running}."
        )


class Running:
    def __init__(
        self,
        data_dir: Path,
        provbanan: MeetPackage,
        provbanan_key: str,
        planning: Planning,
        versions: Versions,
        hub_version: str = "0.0.0",
    ) -> None:
        self.data_dir = data_dir
        self.provbanan = provbanan
        self.provbanan_key = provbanan_key
        self.planning = planning
        self.versions = versions
        self.hub_version = hub_version
        # Planering's answers from the cloud, for a meet this hub follows (4.4, SYNK-02), and
        # whether the meet's home is here (H35).
        self.followed_answers: Callable[[str], dict[str, ProposalStatus]] = lambda meet: {}
        self.home_here: Callable[[str], bool] = lambda meet: True
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
            run_id = self._led_elsewhere(store) or store.start(traffic_day, game_day, replace=True)
            self._select(meet, version)
            return store, run_id

    def follow(self, meet: str, version: int) -> None:
        """Molnhubben följer Pi:n live (SYNK-14): the run the Pi leads becomes this hub's meet,
        without a run of its own."""
        with self._lock:
            self._store(meet, version)
            if (self.meet, self.version) != (meet, version):
                self._select(meet, version)

    def mirror(self, meet: str, version: int) -> PreviewStore:
        """The store the runs of the meet and version are kept in, also those another hub
        leads."""
        with self._lock:
            return self._store(meet, version)

    def leading(self) -> Leading | None:
        """The run this hub leads, for Synk to send up: none in Provbanan or while following."""
        if self.meet == PROVBANAN:
            return None
        store = self.store
        try:
            run_id = store.current()
        except MissingRun:
            return None
        if store.leader(run_id) is not None:
            return None
        return Leading(self.meet, self.version, run_id, store.package_key)

    def answers(self, meet: str) -> dict[str, ProposalStatus]:
        """Planering's answer to each driftändring: from the meet's home (4.4, H35)."""
        here, there = self.planning.answers(meet), self.followed_answers(meet)
        return {**there, **here} if self.home_here(meet) else {**here, **there}

    def _led_elsewhere(self, store: PreviewStore) -> str | None:
        try:
            run_id = store.current()
        except MissingRun:
            return None
        led = store.leader(run_id)
        return run_id if led is not None and now_utc() - led[1] < FOLLOW_WINDOW else None

    def _select(self, meet: str, version: int) -> None:
        self.meet, self.version = meet, version
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"meet": meet, "version": version}), encoding="utf-8")

    def _package(self, meet: str, version: int) -> tuple[MeetPackage, str]:
        """The package and the key its runs carry: the checksum it was published with."""
        if meet == PROVBANAN:
            if version != 1:
                raise UnknownMeet()
            return self.provbanan, self.provbanan_key
        try:
            published, data = self.versions.stored(meet, version)
            package = MeetPackage.model_validate_json(data)
        except SyncError as error:
            raise UnknownMeet() from error
        if newer(package.requires_hub, self.hub_version):
            raise NeedsNewerHub(str(package.requires_hub), self.hub_version)
        return package, published.checksum

    def withdrawn(self, meet: str, version: int) -> bool:
        """Is the version withdrawn in Planering (PLAN-18)?"""
        if meet == PROVBANAN:
            return False
        return any(
            v.number == version and v.withdrawn is not None for v in self.versions.versions(meet)
        )

    def latest(self, meet: str) -> int | None:
        """The newest version of the meet that is not withdrawn."""
        if meet == PROVBANAN:
            return None
        numbers = [v.number for v in self.versions.versions(meet) if v.withdrawn is None]
        return max(numbers, default=None)

    def included(self, version: int) -> list[str]:
        """The driftändringar the planner took into the version: they fall away at the switch
        (H4). Taken before the version was published, that is."""
        if self.meet == PROVBANAN:
            return []
        try:
            published = next(
                (v.published for v in self.versions.versions(self.meet) if v.number == version),
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
        try:
            return store.take_small_correction(run_id, latest, self.included(latest))
        except Refused:
            return False  # not a version this hub can switch to (GRUND-18, PLAN-18)

    def _versions(self, meet: str) -> Callable[[int], MeetPackage]:
        """The meet's versions for a switch in the running meet (DRIFT-29). A version is frozen,
        so each is read once; one withdrawn, not there or for a newer hub is no version to
        switch to."""
        cache: dict[int, MeetPackage] = {}

        def read(number: int) -> MeetPackage:
            if number not in cache:
                try:
                    package = self.versions.package(meet, number)
                except SyncError as error:
                    raise LookupError(number) from error
                if newer(package.requires_hub, self.hub_version):
                    raise LookupError(number)
                cache[number] = package
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
