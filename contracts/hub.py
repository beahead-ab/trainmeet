"""Den här hubben: the hub's name, first start and the local login (H52, section 11).

Until TrainMeet ID (step 6), the local administrator is the one who chose the PIN at first
start. A session works as an HttpOnly cookie in the pages and as Authorization: Bearer for the
Drift API.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from contracts.common import Contract, Text

PIN = Field(pattern=r"^[0-9]{6,12}$", description="6–12 siffror. Skrivs aldrig ut i loggen.")


class HubInfo(Contract):
    name: Text
    set_up: bool = Field(description="Har hubben fått namn och PIN vid första start?")
    logged_in: bool


class SetUp(Contract):
    """First start: only possible while the hub has no PIN."""

    name: str = Field(min_length=1, max_length=40)
    pin: str = PIN


class LogIn(Contract):
    pin: str = PIN


class Rename(Contract):
    """På den här hubben (SYNK-07): hubbens namn, som det syns i sidhuvudet och för molnet."""

    name: str = Field(min_length=1, max_length=40)


class PinChange(Contract):
    """Byt PIN (SYNK-07): den nuvarande först. Alla andra inloggningar slutar gälla."""

    pin: str = PIN
    new_pin: str = PIN


class Session(Contract):
    session_key: Text = Field(
        description="Visas en gång. Gäller 12 timmar, eller tills utloggning."
    )


class AiFormat(StrEnum):
    """Which API the service talks (H59): the ordinary chat API, or Claude's own."""

    CHAT = "chat"
    CLAUDE = "claude"


class AiService(Contract):
    """Egen AI (H58): the service the hub transcribes scanned pages and pictures with. The key
    is never shown again: only that one is set."""

    format: AiFormat
    address: Text = Field(description="Tjänstens adress, till exempel https://api.anthropic.com.")
    model: Text
    key_set: bool
    checked: datetime | None = Field(
        default=None, description="När hubben senast provade att modellen läser bilder (H70)."
    )


class AiServiceChange(Contract):
    """Koppla in egen AI. The hub checks that the model reads an image before it is saved."""

    format: AiFormat
    address: str = Field(min_length=8, max_length=300)
    model: str = Field(min_length=1, max_length=120)
    key: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Skickas när den läggs in eller byts; annars står den kvar. Visas aldrig igen.",
    )


class Version(Contract):
    """What runs (GET /api/version): the version, the hub's name and the change it was built
    from. A local build has no commit and no pull request."""

    product: Text
    version: Text
    hub_name: Text
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    pr: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=500)
    built: datetime | None = None
    pr_url: str | None = Field(default=None, description="Ändringen på GitHub.")
    commit_url: str | None = Field(default=None, description="Committen på GitHub.")


# --- Pi:ns nät (SYNK-07, SYNK-26, H45) ----------------------------------------------------------

WifiSecurity = Literal["open", "wpa2", "wpa3"]


class WifiProfile(Contract):
    """Ett sparat Wi-Fi på Pi:n. Lösenordet finns bara hos NetworkManager och kommer aldrig hit."""

    uuid: Text
    ssid: str
    security: Literal["open", "wpa2", "wpa3", "unsupported"]
    hidden: bool
    priority: int
    autoconnect: bool
    active: bool
    editable: bool = Field(
        description="Kan hanteras här: inte företagsnät, hotspot eller liknande."
    )


class WifiDevice(Contract):
    interface: Text
    state: int
    uuid: str = Field(description="Profilen som är ansluten, eller tomt.")
    addresses: list[str]


class WifiNearby(Contract):
    ssid: str
    security: list[str]
    signal: int
    interface: Text


class WifiTrial(Contract):
    """Ett nytt nät provas: behåll det innan tiden är ute, annars går Pi:n tillbaka (H45)."""

    uuid: Text
    interface: Text
    remaining: int = Field(ge=0, description="Sekunder kvar av de 90.")
    token: str | None = Field(default=None, description="Bara till den som startade provet.")


class WifiStatus(Contract):
    """Pi:ns eget nät, inte träffens Wi-Fi som visas för deltagarna."""

    supported: bool
    reason: Text | None = None
    profiles: list[WifiProfile] = Field(default_factory=list)
    devices: list[WifiDevice] = Field(default_factory=list)
    nearby: list[WifiNearby] = Field(default_factory=list)
    radio_enabled: bool = False
    recovering: bool = Field(default=False, description="NetworkManager går tillbaka just nu.")
    trial: WifiTrial | None = None
    can_manage: bool = Field(
        default=False,
        description="Ändringar görs bara i webbläsaren på Pi:n eller över HTTPS, så att ett "
        "lösenord aldrig går okrypterat över träffens nät.",
    )


class WifiProfileChange(Contract):
    """Spara ett nät. Utan lösenord behålls det sparade, om SSID och säkerhet är desamma."""

    uuid: Text | None = None
    ssid: str = Field(min_length=1, max_length=32)
    security: WifiSecurity
    password: str = Field(default="", max_length=63, description="Skrivs aldrig ut.")
    hidden: bool = False


class WifiAction(Contract):
    """Det övriga: sök (interface), ta bort (uuid), ordning (uuids), anslut nu (uuid och
    interface), behåll eller återställ (token)."""

    uuid: Text | None = None
    uuids: list[str] | None = Field(default=None, max_length=32)
    interface: Text | None = None
    token: Text | None = None


# --- Uppdateringen (SYNK-23) ---------------------------------------------------------------------


class UpdateStatus(Contract):
    """Uppdateringen på Pi:n, på knapptryck och aldrig under en träff. Pi:n hämtar det senaste
    Pi-paketet, provar det och går tillbaka om hubben inte svarar."""

    available: bool = Field(description="Hubben kan uppdatera sig själv: en Pi med installationen.")
    reason: Text | None = None
    build: Text | None = Field(default=None, description="Ändringen som körs nu.")
    state: (
        Literal["checking", "downloading", "installing", "restarting", "done", "current", "failed"]
        | None
    ) = None
    message: Text | None = None
    at: datetime | None = None
    meet_running: bool = Field(default=False, description="En träff pågår: då uppdateras inget.")
