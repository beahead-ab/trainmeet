"""The settings of ID's API, read from the environment when it starts. Secrets have no defaults.

ID_API_DATABASE_URL   PostgreSQL. Required. Never written to the log.
ID_API_MIGRATE        "auto" (default) brings the database up to date at start; "check" only checks.
ID_API_ISSUER         ID's realm as the browser sees it, e.g. https://id.trainmeet.app/realms/trainmeet.
ID_API_INTERNAL       Where the API itself reaches the realm, e.g. http://id:8080/realms/trainmeet.
ID_API_CLIENT         The web app's client in the realm. Default "id".
ID_API_SECRET         The client's secret. Required.
ID_API_PUBLIC_URL     ID's own address, for the web app's login and the links in the mails.
ID_API_APPS           The apps' clients that may ask about roles, comma separated.
                      Default "catalog".
ID_API_WEB_DIR        The built web app (apps/id/dist). Default: next to the repo.
ID_SMTP_HOST, ID_SMTP_PORT, ID_SMTP_SSL, ID_SMTP_STARTTLS, ID_SMTP_AUTH, ID_SMTP_USER,
ID_SMTP_FROM          The mail server, the same as Keycloak's (#66).
ID_SMTP_PASSWORD_FILE The mail server's password, a file in ID's vault. Read, never logged.
ID_SUPPORT_ADDRESS    Where Hjälp och fel goes (KONTO-06, ID9, ID12). A setting, never in the code;
                      without it the help form says it cannot send here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DIR = REPO / "apps" / "id" / "dist"


class SettingsError(ValueError):
    """A setting is missing or wrong. The message names the setting, never its value."""


@dataclass(frozen=True)
class Smtp:
    host: str
    port: int
    ssl: bool
    starttls: bool
    auth: bool
    user: str
    sender: str
    password_file: Path | None = field(default=None, repr=False)

    def password(self) -> str:
        if self.password_file is None or not self.password_file.is_file():
            return ""
        return self.password_file.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    issuer: str
    internal: str
    client: str
    secret: str = field(repr=False)
    public_url: str
    apps: tuple[str, ...] = ("catalog",)
    migrate: Literal["auto", "check"] = "auto"
    web_dir: Path = DEFAULT_WEB_DIR
    smtp: Smtp | None = None
    support: str | None = None

    @property
    def redirect_uri(self) -> str:
        return self.public_url + "/api/id/1/login/callback"


def _address(source: Mapping[str, str], name: str, *, internal: bool = False) -> str:
    value = source.get(name, "").strip().rstrip("/")
    if not value:
        raise SettingsError(f"{name} saknas.")
    if value.startswith("https://"):
        return value
    host = value.removeprefix("http://").split("/", 1)[0].split(":", 1)[0]
    if value.startswith("http://") and (internal or host in ("localhost", "127.0.0.1")):
        return value
    raise SettingsError(f"{name} ska vara en https-adress.")


def _on(source: Mapping[str, str], name: str, default: bool) -> bool:
    value = source.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("true", "on", "1", "yes")


def from_env(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    database_url = source.get("ID_API_DATABASE_URL", "").strip()
    if not database_url:
        raise SettingsError("ID_API_DATABASE_URL saknas.")
    secret = source.get("ID_API_SECRET", "").strip()
    if not secret:
        raise SettingsError("ID_API_SECRET saknas.")
    migrate = source.get("ID_API_MIGRATE", "").strip() or "auto"
    if migrate not in ("auto", "check"):
        raise SettingsError('ID_API_MIGRATE ska vara "auto" eller "check".')
    issuer = _address(source, "ID_API_ISSUER")
    internal = source.get("ID_API_INTERNAL", "").strip()
    smtp: Smtp | None = None
    if source.get("ID_SMTP_HOST", "").strip():
        password_file = source.get("ID_SMTP_PASSWORD_FILE", "").strip()
        try:
            port = int(source.get("ID_SMTP_PORT", "465"))
        except ValueError as error:
            raise SettingsError("ID_SMTP_PORT ska vara ett tal.") from error
        smtp = Smtp(
            host=source["ID_SMTP_HOST"].strip(),
            port=port,
            ssl=_on(source, "ID_SMTP_SSL", True),
            starttls=_on(source, "ID_SMTP_STARTTLS", False),
            auth=_on(source, "ID_SMTP_AUTH", True),
            user=source.get("ID_SMTP_USER", "").strip(),
            sender=source.get("ID_SMTP_FROM", "").strip() or "konto@trainmeet.se",
            password_file=Path(password_file) if password_file else None,
        )
    web_dir = source.get("ID_API_WEB_DIR", "").strip()
    apps = tuple(a.strip() for a in source.get("ID_API_APPS", "catalog").split(",") if a.strip())
    return Settings(
        database_url=database_url,
        issuer=issuer,
        internal=_address(source, "ID_API_INTERNAL", internal=True) if internal else issuer,
        client=source.get("ID_API_CLIENT", "").strip() or "id",
        secret=secret,
        public_url=_address(source, "ID_API_PUBLIC_URL"),
        apps=apps,
        migrate="check" if migrate == "check" else "auto",
        web_dir=Path(web_dir) if web_dir else DEFAULT_WEB_DIR,
        smtp=smtp,
        support=source.get("ID_SUPPORT_ADDRESS", "").strip() or None,
    )
