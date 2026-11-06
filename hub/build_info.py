"""What is running: the version, and the change (pull request and commit) it was built from.

The deploy sets the TRAINMEET_* variables when the image is built. Without them the hub
says it is a local build.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

PRODUCT = "TrainMeet Hub"
REPO_URL = "https://github.com/beahead-ab/trainmeet"
DEFAULT_HUB_NAME = "Hubben"

_COMMIT = re.compile(r"[0-9a-f]{7,40}")


def package_version() -> str:
    try:
        return version("trainmeet")
    except PackageNotFoundError:
        return "0.0.0"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    hub_name: str = DEFAULT_HUB_NAME
    commit: str | None = None
    pr: int | None = None
    title: str | None = None
    built: datetime | None = None

    @property
    def is_local(self) -> bool:
        return self.commit is None and self.pr is None

    @property
    def short_commit(self) -> str | None:
        return self.commit[:7] if self.commit else None

    @property
    def pr_url(self) -> str | None:
        return f"{REPO_URL}/pull/{self.pr}" if self.pr else None

    @property
    def commit_url(self) -> str | None:
        return f"{REPO_URL}/commit/{self.commit}" if self.commit else None

    def as_dict(self) -> dict[str, object]:
        return {
            "product": PRODUCT,
            "version": self.version,
            "hub_name": self.hub_name,
            "commit": self.commit,
            "pr": self.pr,
            "title": self.title,
            "built": self.built.isoformat() if self.built else None,
        }


def from_env(env: Mapping[str, str] | None = None) -> BuildInfo:
    """Read the build information from the environment. Values that look wrong are left out."""
    source = os.environ if env is None else env

    def get(key: str) -> str | None:
        value = source.get(key, "").strip()
        return value or None

    commit = get("TRAINMEET_COMMIT")
    if commit is not None:
        commit = commit.lower()
        if not _COMMIT.fullmatch(commit):
            commit = None

    pr_raw = get("TRAINMEET_PR")
    pr = int(pr_raw) if pr_raw is not None and pr_raw.isdigit() else None

    built_raw = get("TRAINMEET_BUILT")
    built: datetime | None = None
    if built_raw is not None:
        try:
            built = datetime.fromisoformat(built_raw.replace("Z", "+00:00"))
        except ValueError:
            built = None

    return BuildInfo(
        version=package_version(),
        hub_name=get("TRAINMEET_HUB_NAME") or DEFAULT_HUB_NAME,
        commit=commit,
        pr=pr,
        title=get("TRAINMEET_TITLE"),
        built=built,
    )
