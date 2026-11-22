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
CATALOG_ID_WEB         ID's web app, where the owner shares the fleet. Default: the issuer's
                       address, where it lives in the test environment beside Keycloak.
CATALOG_ID_API         ID's own API, which Catalog asks about shared fleets at every call (#49,
                       KONTO-34), e.g. http://id-api:8080 next to it. Without it nothing is shared.
CATALOG_PICTURES_DIR   Where the pictures lie without Object Storage: files on disk, fetched
                       through Catalog with signed addresses. Default .catalog/pictures in the
                       repo, for running locally. The signing key is made anew at every start.
CATALOG_PICTURES_S3_ENDPOINT
                       Object Storage, S3 compatible, for example https://s3.fr-par.scw.cloud.
                       Turns on Object Storage instead of the disk (CAT-130). The browser
                       fetches the pictures there, so the Content-Security-Policy allows it.
CATALOG_PICTURES_S3_BUCKET
                       The bucket, private. Required with the endpoint.
CATALOG_PICTURES_S3_REGION
                       The bucket's region, for the signatures. Default fr-par.
CATALOG_PICTURES_S3_KEY_FILE
                       A file with the access key on the first line and its secret on the
                       second. Required with the endpoint. Never written to the log.
CATALOG_BACKGROUND_MODEL
                       The U2NetP model for the background removal (CAT-127), checked against
                       its SHA-256 when it is first needed. Default /app/models/u2netp.onnx,
                       where catalog/Dockerfile puts it. Without it only the original background
                       can be chosen, and the uploads work as before.
CATALOG_FLYTT_PEPPER   The pepper for the hash of the old TrainCatalog owners' verified e-mail
                       addresses (#57, CAT-204, catalog/waiting.py): at least 32 characters,
                       the same for the move and for Catalog. A secret: never written to the
                       log. Without it, no waiting fleet is taken over at the login.
CATALOG_SOURCE_PAGES   "off" turns off the reading of the cited pages (catalog/source_pages.py,
                       CAT-169): a value is then held only to the search's own short excerpt.
                       Default on. Off in the browser trial, whose pages are made up.
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
from urllib.parse import urlsplit

from contracts.catalog import CatalogVersion

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DIR = REPO / "apps" / "catalog" / "dist"
DEFAULT_PICTURES_DIR = REPO / ".catalog" / "pictures"
DEFAULT_BACKGROUND_MODEL = Path("/app/models/u2netp.onnx")
PEPPER_ENV = "CATALOG_FLYTT_PEPPER"
PEPPER_LENGTH = 32
"""The shortest pepper, in characters: long enough that it cannot be guessed."""
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
_REGION = re.compile(r"[a-z]{2}(-[a-z0-9]+)+")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")


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
    api: str | None = None
    web: str | None = None

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/api/catalog/1/id/callback"

    @property
    def id_public(self) -> str:
        """ID's web app: as set, or the issuer's address without the realm."""
        return self.web or self.issuer.split("/realms/", 1)[0]


@dataclass(frozen=True)
class S3Settings:
    """Object Storage for the pictures (CAT-130): S3 compatible, such as Scaleway's."""

    endpoint: str
    bucket: str
    region: str = "fr-par"
    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)

    @property
    def origin(self) -> str:
        """Where the browser fetches the pictures: the endpoint's scheme, host and port."""
        parts = urlsplit(self.endpoint)
        return f"{parts.scheme}://{parts.netloc}"


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
    pictures_dir: Path = DEFAULT_PICTURES_DIR
    pictures_s3: S3Settings | None = None
    background_model: Path = DEFAULT_BACKGROUND_MODEL
    flytt_pepper: bytes | None = field(default=None, repr=False)
    source_pages: bool = True
    """The pepper for the waiting fleets' hash (catalog/waiting.py). A secret."""

    def __repr__(self) -> str:  # the database address may hold a password
        return (
            f"Settings(migrate={self.migrate!r}, trial_login={self.trial_login}, "
            f"id={self.id is not None}, pictures={'s3' if self.pictures_s3 else 'disk'!r})"
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
        api=_address(source, "CATALOG_ID_API", internal=True),
        web=_address(source, "CATALOG_ID_WEB"),
    )


def s3_from_env(source: Mapping[str, str]) -> S3Settings | None:
    """Object Storage, when its endpoint is set. The keys are read from their file here, and
    an error names the setting, never the file's content."""
    endpoint = _address(source, "CATALOG_PICTURES_S3_ENDPOINT")
    if endpoint is None:
        return None
    if urlsplit(endpoint).path not in ("", "/"):
        raise SettingsError("CATALOG_PICTURES_S3_ENDPOINT ska vara bara en adress, utan sökväg.")
    bucket = source.get("CATALOG_PICTURES_S3_BUCKET", "").strip()
    if not _BUCKET.fullmatch(bucket):
        raise SettingsError("CATALOG_PICTURES_S3_BUCKET saknas eller är inte ett hinknamn.")
    region = source.get("CATALOG_PICTURES_S3_REGION", "").strip() or "fr-par"
    if not _REGION.fullmatch(region):
        raise SettingsError("CATALOG_PICTURES_S3_REGION är inte en region, till exempel fr-par.")
    key_file = source.get("CATALOG_PICTURES_S3_KEY_FILE", "").strip()
    if not key_file:
        raise SettingsError("CATALOG_PICTURES_S3_KEY_FILE saknas.")
    try:
        lines = Path(key_file).read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError) as error:
        raise SettingsError("CATALOG_PICTURES_S3_KEY_FILE går inte att läsa.") from error
    if len(lines) < 2:
        raise SettingsError(
            "CATALOG_PICTURES_S3_KEY_FILE ska ha nyckeln på första raden och hemligheten på andra."
        )
    return S3Settings(
        endpoint=endpoint, bucket=bucket, region=region, access_key=lines[0], secret_key=lines[1]
    )


def pepper_from_env(source: Mapping[str, str]) -> bytes | None:
    """The pepper for the waiting fleets' hash, or None when it is not set. The error names
    the setting, never its value."""
    value = source.get(PEPPER_ENV, "").strip()
    if not value:
        return None
    if len(value) < PEPPER_LENGTH:
        raise SettingsError(f"{PEPPER_ENV} ska vara minst {PEPPER_LENGTH} tecken.")
    return value.encode("utf-8")


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
    pictures_dir = source.get("CATALOG_PICTURES_DIR", "").strip()
    background_model = source.get("CATALOG_BACKGROUND_MODEL", "").strip()
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
        pictures_dir=Path(pictures_dir) if pictures_dir else DEFAULT_PICTURES_DIR,
        pictures_s3=s3_from_env(source),
        background_model=Path(background_model) if background_model else DEFAULT_BACKGROUND_MODEL,
        flytt_pepper=pepper_from_env(source),
        source_pages=source.get("CATALOG_SOURCE_PAGES", "").strip().lower() != "off",
    )
