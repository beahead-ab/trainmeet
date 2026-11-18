"""Den här hubben: the hub's name, first start and the local login (H52, section 11).

Until TrainMeet ID (step 6), the local administrator is the one who chose the PIN at first
start. A session works as an HttpOnly cookie in the pages and as Authorization: Bearer for the
Drift API.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from contracts.common import Contract, Text
from contracts.id import MeetRole

PIN = Field(pattern=r"^[0-9]{6,12}$", description="6–12 siffror. Skrivs aldrig ut i loggen.")


class HubInfo(Contract):
    name: Text
    set_up: bool = Field(description="Har hubben fått namn och PIN vid första start?")
    logged_in: bool
    admin: bool = Field(
        default=False,
        description="Inloggad med hubbens PIN (H18): får göra allt, också hubbens inställningar.",
    )
    meet_role: MeetRole | None = Field(
        default=None,
        description="Insläppt med en engångskod (H56): rollen på träffen som kör, och bara där.",
    )


class SetUp(Contract):
    """First start: only possible while the hub has no PIN."""

    name: str = Field(min_length=1, max_length=40)
    pin: str = PIN


class LogIn(Contract):
    pin: str = PIN


class CodeLogIn(Contract):
    """Logga in med en engångskod från trafikledningen (H56, F18)."""

    code: str = Field(pattern=r"^[0-9]{6}$", description="Sex siffror. Skrivs aldrig ut i loggen.")


class OneTimeCodeRequest(Contract):
    """Släpp in en person (H56): trafikledningen ger koden under Klienter i Drift."""

    name: str | None = Field(
        default=None,
        max_length=40,
        description="Vem koden är till, om trafikledaren vill skriva det. Syns i listan.",
    )


class OneTimeCode(Contract):
    """Engångskoden (H56, KONTO-19): sex siffror, en gång, i 15 minuter, för träffen som kör.
    Den ger högst trafikledarens egen roll."""

    code: Text = Field(description="Visas en gång. Hubben sparar bara ett kontrollvärde.")
    role: MeetRole
    expires: datetime


class LetIn(Contract):
    """Insläppt med engångskod: vem och tills när, aldrig koden eller nyckeln. Rollen gäller
    tills träffen slutar eller trafikledningen tar bort den (H56)."""

    person: Text = Field(description="Ett kort id för inloggningen, för att kunna ta bort den.")
    name: Text | None = None
    role: MeetRole
    since: datetime
    until: datetime


class Rename(Contract):
    """På den här hubben (SYNK-07): hubbens namn, som det syns i sidhuvudet och för molnet."""

    name: str = Field(min_length=1, max_length=40)


class PinChange(Contract):
    """Byt PIN (SYNK-07): den nuvarande först. Alla andra inloggningar slutar gälla."""

    pin: str = PIN
    new_pin: str = PIN


class Session(Contract):
    session_key: Text = Field(
        description="Visas en gång. Gäller 12 timmar med PIN, med en engångskod tills träffen "
        "slutar eller rollen tas bort (H56), eller tills utloggning."
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
    """Uppdateringen på Pi:n: Ny version finns, på knapptryck och aldrig under en träff. Pi:n
    hämtar det senaste Pi-paketet, provar det och går tillbaka om hubben inte svarar."""

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
    latest: Text | None = Field(
        default=None, description="Ändringen i det senaste Pi-paketet, när Pi:n kunde se den."
    )
    newer: bool = Field(default=False, description="Ny version finns (SYNK-19).")
    checked: datetime | None = Field(default=None, description="När Pi:n senast såg efter.")


# --- Deltagarna (DELT-01–DELT-20): träffens Wi-Fi, och det deltagarsidan får visa (S8) --------


class MeetWifi(Contract):
    """Träffens Wi-Fi (H45, SYNK-26): det deltagarna och skärmarna visar, inte Pi:ns eget nät.
    Inget namn: träffens Wi-Fi delas inte."""

    name: str = Field(default="", max_length=32, description="Nätverkets namn. Tomt: delas inte.")
    open: bool = Field(default=False, description="Öppet nät, utan lösenord.")
    has_password: bool = Field(default=False, description="Ett lösenord är inlagt.")


class MeetWifiChange(Contract):
    """Ändra träffens Wi-Fi. Utan nytt lösenord står det som var kvar, så länge namnet finns."""

    name: str = Field(default="", max_length=32)
    open: bool = False
    password: Annotated[str, StringConstraints(strip_whitespace=False)] | None = Field(
        default=None,
        description="8–63 tecken. Skrivs aldrig ut i loggen och skickas aldrig tillbaka hit.",
    )


class SharedWifi(Contract):
    """Träffens Wi-Fi som deltagarna ser det, på träffens nät eller inloggade (S8)."""

    name: Text
    open: bool
    password: str | None = Field(
        default=None,
        description="Lösenordet, när ett är inlagt: det boxen och telefonen frågar efter.",
    )


class Participant(Contract):
    """Det deltagarsidan får visa den som tittar (S1, S8). Klockan, banan och nästa händelser
    läses i Driftens API, som skärmarna (H72); här står bara det som beror på var man är."""

    full: bool = Field(
        description="På träffens nät eller inloggad: namn, foton och träffens Wi-Fi visas (S8)."
    )
    logged_in: bool = False
    wifi: SharedWifi | None = Field(
        default=None, description="Träffens Wi-Fi, bara när full är sant och ett nät är inlagt."
    )
    link: Text | None = Field(
        default=None,
        description=(
            "Länken till träffen över internet: molnhubben som följer Pi:n. Tom när hubben inte "
            "är kopplad till molnet; då gäller hubbens egen adress, på träffens nät."
        ),
    )
