"""Catalog's settings, read from the environment when it starts. Secrets never have defaults.

CATALOG_DATABASE_URL   PostgreSQL, for example postgresql://catalog@catalog-db/catalog.
                       Required. Never written to the log.
CATALOG_MIGRATE        "check" (default): refuse to start if the database is behind.
                       "auto": bring the database up to date at start (local and CI).
                       The test environment migrates as a step of its own, after the
                       backup (CAT-39).
CATALOG_TRIAL_LOGIN    "on" turns on the trial login, only in the test environment (CAT-214).
CATALOG_WEB_DIR        The built web app (apps/catalog/dist). Default: next to the repo.
CATALOG_TAG_BASE       The tags' address up to the uid. Default https://trainmeet.app/t/ (C9);
                       the test environment uses its own, so its tags can be tapped there.
CATALOG_SIMULATED_TAGS "on" allows simulated tags, only in the test environment (CAT-96).
CATALOG_ID_ISSUER      TrainMeet ID's realm, for example https://id.trainmeet.app/realms/trainmeet.
                       Turns on the login with ID (#66, KONTO-27). The browser goes there.
CATALOG_ID_INTERNAL    Where Catalog itself reaches the same realm, if not at the issuer's
                       address, for example http://id:8080/realms/trainmeet next to it.
CATALOG_ID_CLIENT      Catalog's client in ID. Default "catalog".
CATALOG_ID_SECRET      The client's secret. Required with the issuer. Never written to the log.
CATALOG_PUBLIC_URL     Catalog's own address, for ID to send the browser back to.
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

from contracts.catalog import CatalogVersion

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DIR = REPO / "apps" / "catalog" / "dist"
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
    """How Catalog logs in with TrainMeet ID: OpenID Connect's code flow with PKCE."""

    issuer: str
    client: str
    secret: str = field(repr=False)
    public_url: str
    internal: str

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/api/catalog/1/id/callback"


@dataclass(frozen=True)
class Settings:
    database_url: str
    migrate: Literal["check", "auto"] = "check"
    trial_login: bool = False
    web_dir: Path = DEFAULT_WEB_DIR
    tag_base: str = "https://trainmeet.app/t/"
    simulated_tags: bool = False
    id: IdSettings | None = None
    build: CatalogVersion = field(default_factory=lambda: CatalogVersion(version="0.0.0"))

    def __repr__(self) -> str:  # the database address may hold a password
        return (
            f"Settings(migrate={self.migrate!r}, trial_login={self.trial_login}, "
            f"id={self.id is not None})"
        )


def _switch(source: Mapping[str, str], name: str) -> bool:
    value = source.get(name, "").strip().lower()
    if value not in ("", "on", "off"):
        raise SettingsError(f'{name} ska vara "on" eller "off".')
    return value == "on"


def _address(source: Mapping[str, str], name: str, *, internal: bool = False) -> str | None:
    """An address without a trailing slash: https, or http to this machine or, for an
    internal address, to a service next to it."""
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
    issuer = _address(source, "CATALOG_ID_ISSUER")
    if issuer is None:
        return None
    secret = source.get("CATALOG_ID_SECRET", "").strip()
    if not secret:
        raise SettingsError("CATALOG_ID_SECRET saknas.")
    public_url = _address(source, "CATALOG_PUBLIC_URL")
    if public_url is None:
        raise SettingsError("CATALOG_PUBLIC_URL saknas.")
    return IdSettings(
        issuer=issuer,
        client=source.get("CATALOG_ID_CLIENT", "").strip() or "catalog",
        secret=secret,
        public_url=public_url,
        internal=_address(source, "CATALOG_ID_INTERNAL", internal=True) or issuer,
    )


def build_from_env(source: Mapping[str, str]) -> CatalogVersion:
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
    return CatalogVersion(
        version=package_version(),
        commit=commit.lower() if commit else None,
        pr=int(pr_raw) if pr_raw is not None and pr_raw.isdigit() else None,
        title=get("TRAINMEET_TITLE"),
        built=built,
    )


def from_env(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    database_url = source.get("CATALOG_DATABASE_URL", "").strip()
    if not database_url:
        raise SettingsError("CATALOG_DATABASE_URL saknas.")
    migrate = source.get("CATALOG_MIGRATE", "check").strip() or "check"
    if migrate not in ("check", "auto"):
        raise SettingsError('CATALOG_MIGRATE ska vara "check" eller "auto".')
    web_dir = source.get("CATALOG_WEB_DIR", "").strip()
    tag_base = source.get("CATALOG_TAG_BASE", "").strip() or "https://trainmeet.app/t/"
    if not tag_base.startswith("https://") or not tag_base.rstrip("/").endswith("/t"):
        raise SettingsError("CATALOG_TAG_BASE ska vara en https-adress som slutar på /t/.")
    return Settings(
        database_url=database_url,
        migrate="auto" if migrate == "auto" else "check",
        trial_login=_switch(source, "CATALOG_TRIAL_LOGIN"),
        web_dir=Path(web_dir) if web_dir else DEFAULT_WEB_DIR,
        tag_base=tag_base.rstrip("/") + "/",
        simulated_tags=_switch(source, "CATALOG_SIMULATED_TAGS"),
        id=id_from_env(source),
        build=build_from_env(source),
    )
