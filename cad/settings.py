"""CAD's settings, read from the environment when it starts. Secrets never have defaults.

CAD_DATABASE_URL   PostgreSQL, for example postgresql://cad@cad-db/cad. Required. Never written
                   to the log.
CAD_MIGRATE        "check" (default): refuse to start if the database is behind.
                   "auto": bring the database up to date at start (local and CI). The test
                   environment migrates as a step of its own, after the backup.
CAD_TRIAL_LOGIN    "on" turns on the trial login with fixed accounts: the browser test, and the
                   test environment until CAD has its client in ID.
CAD_WEB_DIR        The built web app (apps/cad/dist). Default: next to the repo.
CAD_ID_ISSUER      TrainMeet ID's realm, for example https://id.trainmeet.app/realms/trainmeet.
                   Turns on the login with ID. The browser goes there.
CAD_ID_INTERNAL    Where CAD itself reaches the same realm, if not at the issuer's address, for
                   example http://id:8080/realms/trainmeet next to it.
CAD_ID_CLIENT      CAD's client in ID. Default "cad".
CAD_ID_SECRET      The client's secret. Required with the issuer. Never written to the log.
CAD_PUBLIC_URL     CAD's own address, for ID to send the browser back to.
CAD_ID_WEB         ID's web app, for Hjälp och fel and Tokens. Default: the issuer's address.
CAD_ID_API         ID's own API, which CAD asks about the clubs and the roles at every call
                   (#67, KONTO-34), e.g. http://id-api:8080. Without it CAD knows no clubs.
TRAINMEET_COMMIT, TRAINMEET_PR, TRAINMEET_TITLE, TRAINMEET_BUILT
                   Which change is running, set when the image is built.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from contracts.cad import CadVersion

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DIR = REPO / "apps" / "cad" / "dist"
_COMMIT = re.compile(r"[0-9a-f]{7,40}")


class SettingsError(ValueError):
    """A setting is missing or wrong. The message names the setting, never its value."""


def package_version() -> str:
    try:
        return version("trainmeet")
    except PackageNotFoundError:
        return "0.0.0"


@dataclass(frozen=True)
class IdSettings:
    """How CAD logs in with TrainMeet ID: OpenID Connect's code flow with PKCE, as Catalog."""

    issuer: str
    client: str
    secret: str = field(repr=False)
    public_url: str
    internal: str
    api: str | None = None
    web: str | None = None

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/api/cad/1/id/callback"

    @property
    def id_public(self) -> str:
        """ID's web app: as set, or the issuer's address without the realm."""
        return self.web or self.issuer.split("/realms/", 1)[0]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    migrate: Literal["check", "auto"] = "check"
    trial_login: bool = False
    web_dir: Path = DEFAULT_WEB_DIR
    id: IdSettings | None = None
    build: CadVersion = field(default_factory=lambda: CadVersion(version="0.0.0"))


def _switch(source: Mapping[str, str], name: str) -> bool:
    value = source.get(name, "").strip().lower()
    if value not in ("", "on", "off"):
        raise SettingsError(f'{name} ska vara "on" eller "off".')
    return value == "on"


def _address(source: Mapping[str, str], name: str, *, internal: bool = False) -> str | None:
    """An address without a trailing slash: https, or http to this machine or, for an internal
    address, to a service next to it."""
    value = source.get(name, "").strip().rstrip("/")
    if not value:
        return None
    if value.startswith("https://"):
        return value
    host = value.removeprefix("http://").split("/", 1)[0].split(":", 1)[0]
    if value.startswith("http://") and (internal or host in ("localhost", "127.0.0.1")):
        return value
    raise SettingsError(f"{name} ska vara en https-adress.")


def id_from_env(source: Mapping[str, str]) -> IdSettings | None:
    issuer = _address(source, "CAD_ID_ISSUER")
    if issuer is None:
        return None
    secret = source.get("CAD_ID_SECRET", "").strip()
    if not secret:
        raise SettingsError("CAD_ID_SECRET saknas.")
    public_url = _address(source, "CAD_PUBLIC_URL")
    if public_url is None:
        raise SettingsError("CAD_PUBLIC_URL saknas.")
    return IdSettings(
        issuer=issuer,
        client=source.get("CAD_ID_CLIENT", "").strip() or "cad",
        secret=secret,
        public_url=public_url,
        internal=_address(source, "CAD_ID_INTERNAL", internal=True) or issuer,
        api=_address(source, "CAD_ID_API", internal=True),
        web=_address(source, "CAD_ID_WEB"),
    )


def build_from_env(source: Mapping[str, str]) -> CadVersion:
    """Which change is running. Values that look wrong are left out."""

    def get(key: str) -> str | None:
        value = source.get(key, "").strip()
        return value or None

    commit = get("TRAINMEET_COMMIT")
    if commit is not None and not _COMMIT.fullmatch(commit.lower()):
        commit = None
    pr_raw = get("TRAINMEET_PR")
    built_raw = get("TRAINMEET_BUILT")
    built: datetime | None = None
    if built_raw is not None:
        try:
            built = datetime.fromisoformat(built_raw.replace("Z", "+00:00"))
        except ValueError:
            built = None
    return CadVersion(
        version=package_version(),
        commit=commit.lower() if commit else None,
        pr=int(pr_raw) if pr_raw is not None and pr_raw.isdigit() else None,
        title=get("TRAINMEET_TITLE"),
        built=built,
    )


def from_env(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    database_url = source.get("CAD_DATABASE_URL", "").strip()
    if not database_url:
        raise SettingsError("CAD_DATABASE_URL saknas.")
    migrate = source.get("CAD_MIGRATE", "check").strip() or "check"
    if migrate not in ("check", "auto"):
        raise SettingsError('CAD_MIGRATE ska vara "check" eller "auto".')
    web_dir = source.get("CAD_WEB_DIR", "").strip()
    return Settings(
        database_url=database_url,
        migrate="auto" if migrate == "auto" else "check",
        trial_login=_switch(source, "CAD_TRIAL_LOGIN"),
        web_dir=Path(web_dir) if web_dir else DEFAULT_WEB_DIR,
        id=id_from_env(source),
        build=build_from_env(source),
    )
