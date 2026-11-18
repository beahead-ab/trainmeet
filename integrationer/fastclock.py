"""FastClock som träffens klocka (F12, IMPORT-35): Hubben följer eller styr en extern klocka.

Ported from the old Server's external_clock.py, whose tests are the facit (H79). The hub alone
talks to FastClock; screens, boxes and browsers read the meet clock from Drift as before. Only a
public HTTPS address is allowed, with no path, credentials, private network or redirect, and
the password is sent to FastClock only on an explicit start or stop and never shown again.

Reading:   GET {url}/api/clocks/{name}/time
Steering:  PUT {url}/api/clocks/{name}/start?user=…&password=…
           PUT {url}/api/clocks/{name}/stop?user=…&password=…&reason=…

A read error never falls back to another clock: the last time received stays, with a warning,
and the hub tries again. A late answer from an earlier clock or meet is thrown away.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any, Final, Literal
from urllib.parse import quote, urlencode, urlsplit

PROVIDER_URL: Final = "https://fastclock.azurewebsites.net"
MAX_ANSWER: Final = 65536
TIMEOUT: Final = 4.0

Source = Literal["drift", "fastclock"]
Action = Literal["time", "start", "stop"]


class FastClockError(ValueError):
    """What went wrong, for the dispatcher. Never the address, the answer or a password."""


@dataclass(frozen=True)
class Settings:
    """The meet's clock source. The password is kept in the hub and never shown."""

    source: Source = "drift"
    clock_name: str = ""
    url: str = PROVIDER_URL
    user: str = ""
    password: str = field(default="", repr=False)
    poll_interval: int = 2


@dataclass(frozen=True)
class Sample:
    """One answer from FastClock, as read."""

    seconds: float
    speed: float
    running: bool
    stopped_reason: str | None
    message: str | None
    completed: bool
    minute_precision: bool
    explicit_zero_seconds: bool
    weekday: str


@dataclass(frozen=True)
class Status:
    """FastClock as the hub sees it now: the time interpolated from the last answer, or the
    last time received with a warning when FastClock does not answer."""

    name: str
    seconds: float | None
    speed: float
    running: bool
    available: bool
    can_control: bool
    last_sync: str | None
    message: str | None
    completed: bool
    stopped_reason: str | None
    weekday: str
    precision: Literal["minute", "second"]

    @property
    def time(self) -> str:
        if self.seconds is None:
            return "--:--:--"
        whole = int(self.seconds) % 86400
        return f"{whole // 3600:02}:{whole % 3600 // 60:02}:{whole % 60:02}"


# --- The address ----------------------------------------------------------------------------


def normalize_url(value: object) -> str:
    """A public HTTPS API origin, not any remote resource: local and internal targets and
    credentials in the address are refused, to keep the hub from being sent elsewhere."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(ord(c) < 33 for c in value)
    ):
        raise FastClockError("Ange en giltig HTTPS-adress till FastClock.")
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
    except ValueError:
        raise FastClockError("Ogiltig FastClock-adress.") from None
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
        or host == "localhost"
        or host.endswith((".localhost", ".local", ".internal"))
    ):
        raise FastClockError(
            "Ange en publik HTTPS-adress utan sökväg, inloggning eller parametrar."
        )
    try:
        port = parts.port
    except ValueError:
        raise FastClockError("Ogiltig port i FastClock-adressen.") from None
    if port is not None and not 1 <= port <= 65535:
        raise FastClockError("Ogiltig port i FastClock-adressen.")
    try:
        address = ip_address(host.strip("[]"))
    except ValueError:
        pass  # A public DNS name may be given by the administrator.
    else:
        if not address.is_global:
            raise FastClockError("FastClock-adressen får inte peka på ett lokalt eller privat nät.")
    return value.rstrip("/")


def changed(given: Mapping[str, Any], previous: Settings) -> Settings:
    """The settings as given, checked. An old clock's password never follows to another clock,
    user or address."""
    source = given.get("source")
    if source not in ("drift", "fastclock"):
        raise FastClockError("Välj Drifts klocka eller FastClock.")
    result = replace(previous, source=source)
    result = replace(result, url=normalize_url(given.get("url", result.url)))
    texts: dict[str, str] = {}
    for name, limit in (("clock_name", 100), ("user", 100), ("password", 256)):
        if name in given and given[name] is not None:
            value = given[name]
            if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
                raise FastClockError("Klocknamn eller inloggning har ogiltigt format.")
            texts[name] = value if name == "password" else value.strip()
    result = replace(
        result,
        clock_name=texts.get("clock_name", result.clock_name),
        user=texts.get("user", result.user),
        password=texts.get("password", result.password),
    )
    if given.get("password") is None and any(
        getattr(result, key) != getattr(previous, key) for key in ("clock_name", "user", "url")
    ):
        result = replace(result, password="")
    interval = given.get("poll_interval", result.poll_interval)
    if type(interval) is not int or not 2 <= interval <= 30:
        raise FastClockError("Hämtningsintervallet ska vara 2–30 sekunder.")
    result = replace(result, poll_interval=interval)
    if result.source == "fastclock" and not result.clock_name:
        raise FastClockError("Ange namnet på klockan i FastClock.")
    return result


# --- The answer -----------------------------------------------------------------------------

WEEKDAYS: Final = {
    "monday": "mon", "mon": "mon", "mån": "mon", "måndag": "mon",
    "tuesday": "tue", "tue": "tue", "tues": "tue", "tis": "tue", "tisdag": "tue",
    "wednesday": "wed", "wed": "wed", "ons": "wed", "onsdag": "wed",
    "thursday": "thu", "thu": "thu", "thur": "thu", "tors": "thu", "tor": "thu", "torsdag": "thu",
    "friday": "fri", "fri": "fri", "fre": "fri", "fredag": "fri",
    "saturday": "sat", "sat": "sat", "lör": "sat", "lördag": "sat",
    "sunday": "sun", "sun": "sun", "sön": "sun", "söndag": "sun",
}  # fmt: skip

# FastClock fills its reason fields also when there is nothing to say: a running clock reports
# pauseReason "None" and stoppingReason "NoReason" or "SelectStopReason".
PLACEHOLDERS: Final = frozenset(
    {"", "none", "noreason", "selectstopreason", "null", "undefined", "na", "unknown"}
)


def provider_text(value: object) -> str:
    """FastClock's text with the white space collapsed, or "" for a placeholder."""
    text = " ".join(str(value or "").split())[:160]
    return "" if re.sub(r"[\s_./-]", "", text).casefold() in PLACEHOLDERS else text


def parse(data: object) -> Sample:
    if not isinstance(data, dict) or data.get("isUnavailable") is True:
        raise FastClockError("FastClock är inte tillgänglig.")
    clock = data.get("time")
    speed = data.get("speed")
    if not isinstance(clock, str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", clock
    ):
        raise FastClockError("FastClock svarade med ett ogiltigt klockslag.")
    if (
        type(data.get("isRunning")) is not bool
        or not isinstance(speed, int | float)
        or isinstance(speed, bool)
        or not math.isfinite(speed)
        or not 0 < speed <= 600
    ):
        raise FastClockError("FastClock svarade med en ogiltig hastighet eller status.")
    for name in ("isPaused", "isCompleted", "isUnavailable"):
        if name in data and type(data[name]) is not bool:
            raise FastClockError("FastClock svarade med en ogiltig status.")
    parts = list(map(int, clock.split(":")))
    paused = bool(data.get("isPaused", False))
    completed = bool(data.get("isCompleted", False))
    running = bool(data["isRunning"]) and not paused and not completed
    # A reason belongs to the state it explains: pauseReason to a pause, stoppingReason to a
    # stop. A running or completed clock has none.
    reason = ""
    if paused:
        reason = provider_text(data.get("pauseReason"))
    elif not running and not completed:
        reason = provider_text(data.get("stoppingReason"))
    weekday = data.get("weekday")
    return Sample(
        seconds=parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0),
        speed=float(speed),
        running=running,
        stopped_reason=None if running else reason,
        message=provider_text(data.get("message")) or None,
        completed=completed,
        minute_precision=len(parts) == 2,
        explicit_zero_seconds=len(parts) == 3 and parts[2] == 0,
        weekday=WEEKDAYS.get(weekday.strip().casefold(), "") if isinstance(weekday, str) else "",
    )


# --- The transport --------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


Transport = Callable[[Settings, Action, str], object]


def provider_request(settings: Settings, action: Action = "time", reason: str = "") -> object:
    """One bounded HTTPS call. The errors hold neither the address, the answer nor a password."""
    url = (
        normalize_url(settings.url or PROVIDER_URL)
        + "/api/clocks/"
        + quote(settings.clock_name, safe="")
        + "/"
        + action
    )
    if action != "time":
        params = {"user": settings.user}
        if settings.password:
            params["password"] = settings.password
        if action == "stop":
            params["reason"] = reason
        url += "?" + urlencode(params)
    request = urllib.request.Request(
        url, method="GET" if action == "time" else "PUT", headers={"Accept": "application/json"}
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=TIMEOUT) as answer:
            raw = answer.read(MAX_ANSWER + 1)
            if len(raw) > MAX_ANSWER:
                raise ValueError("för stort")
            return json.loads(raw) if action == "time" else None
    except Exception:
        if action == "time":
            raise FastClockError(
                "FastClock kunde inte läsas. Kontrollera klockans namn och internet."
            ) from None
        raise FastClockError(
            "FastClock bekräftade inte kommandot. Kontrollera klockan och inloggningen innan du "
            "försöker igen."
        ) from None


# --- The clock ------------------------------------------------------------------------------

WAITING: Final = "Väntar på FastClock. Senast mottagna tid visas."


class ExternalClock:
    """FastClock for one meet: read at most once per interval however many ask, and the time
    in between interpolated from the last answer."""

    def __init__(
        self,
        transport: Transport = provider_request,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport = transport
        self.now = monotonic
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        self.scope = ""
        self.settings = Settings()
        self.version = 0
        self.sample: Sample | None = None
        self.received = 0.0
        self.last_seen = 0.0
        self.last_sync: str | None = None
        self.error = ""
        self.next_poll = 0.0

    def configure(self, scope: str, settings: Settings, sample: Sample | None = None) -> None:
        """Another meet or other settings: what was read before is forgotten."""
        with self.lock:
            if scope == self.scope and settings == self.settings and sample is None:
                return
            self.scope, self.settings = scope, settings
            self.version += 1
            self.sample, self.error, self.last_sync = None, "", None
            self.received, self.last_seen = 0.0, 0.0
            self.next_poll = 0.0
            if sample is not None:
                self._accept(sample)

    def _accept(self, sample: Sample) -> None:
        now = self.now()
        previous = self.sample
        same_pace = (
            previous is not None
            and sample.running
            and previous.running
            and sample.speed == previous.speed
        )
        same_minute = previous is not None and int(sample.seconds // 60) == int(
            previous.seconds // 60
        )
        # HH:MM:00 on every answer is also a clock with only minutes; an exact :00 from a clock
        # with seconds must not be mistaken for one.
        if sample.explicit_zero_seconds and previous is not None and same_pace:
            if same_minute and (previous.explicit_zero_seconds or previous.minute_precision):
                sample = replace(sample, minute_precision=True)
                previous = replace(previous, minute_precision=True)
            elif previous.minute_precision:
                sample = replace(sample, minute_precision=True)
        # A clock that answers HH:MM only must not set the hands back to :00 at every answer:
        # the anchor stays until the minute changes.
        if (
            previous is not None
            and same_pace
            and (
                (sample.minute_precision and previous.minute_precision and same_minute)
                or (
                    not sample.minute_precision
                    and not previous.minute_precision
                    and sample.seconds == previous.seconds
                )
            )
        ):
            self.error = ""
            self.last_seen = now
            # The anchor stays; the text and the weekday follow the newest answer.
            self.sample = replace(
                previous,
                message=sample.message,
                completed=sample.completed,
                stopped_reason=sample.stopped_reason,
                weekday=sample.weekday,
            )
        else:
            if (
                previous is not None
                and sample.minute_precision
                and previous.minute_precision
                and same_pace
                and not same_minute
                and self.last_seen
            ):
                # The minute changed between two answers: put its start halfway between them,
                # which takes away a steady minute's lag without pretending to know seconds.
                after = min(59.0, max(0.0, (now - self.last_seen) * sample.speed / 2.0))
                sample = replace(sample, seconds=sample.seconds + after)
            self.sample, self.received, self.error = sample, now, ""
            self.last_seen = now
        self.last_sync = datetime.now(UTC).isoformat()
        self.next_poll = now + self.settings.poll_interval

    def probe(self, settings: Settings) -> Sample:
        return parse(self.transport(settings, "time", ""))

    def poll(self, force: bool = False) -> bool:
        """Read FastClock once if it is time to. A late answer for another meet is dropped."""
        if not self.io_lock.acquire(blocking=False):
            return False
        try:
            with self.lock:
                if self.settings.source != "fastclock" or (
                    not force and self.now() < self.next_poll
                ):
                    return False
                settings, version = self.settings, self.version
                self.next_poll = self.now() + settings.poll_interval
            sample: Sample | None = None
            error = ""
            try:
                sample = self.probe(settings)
            except FastClockError as failure:
                error = str(failure)
            with self.lock:
                if version != self.version:
                    return False
                if sample is None:
                    self.error = error
                else:
                    self._accept(sample)
                return True
        finally:
            self.io_lock.release()

    def status(self) -> Status | None:
        with self.lock:
            if self.settings.source != "fastclock":
                return None
            sample = self.sample
            stale = self.now() - self.last_seen > max(6, self.settings.poll_interval * 3)
            available = sample is not None and not self.error and not stale
            seconds: float | None = None
            if sample is not None:
                seconds = sample.seconds
                if available and sample.running:
                    seconds += max(0.0, self.now() - self.received) * sample.speed
            return Status(
                name=self.settings.clock_name,
                seconds=seconds,
                speed=sample.speed if sample is not None else 1.0,
                running=bool(available and sample is not None and sample.running),
                available=available,
                can_control=bool(self.settings.user),
                last_sync=self.last_sync,
                message=sample.message if available and sample is not None else None,
                completed=bool(available and sample is not None and sample.completed),
                stopped_reason=(
                    (sample.stopped_reason if sample is not None else None)
                    if available
                    else self.error or WAITING
                ),
                weekday=sample.weekday if sample is not None else "",
                precision="minute" if sample is not None and sample.minute_precision else "second",
            )

    def control(self, action: str, reason: str = "") -> None:
        """Start or stop in FastClock. Nothing is shown as started or stopped until FastClock
        itself says so."""
        if action not in ("start", "stop"):
            raise FastClockError("Tiden och hastigheten ändras i FastClock när den är klockan.")
        with self.io_lock:
            with self.lock:
                settings = self.settings
                if settings.source != "fastclock" or not settings.user:
                    raise FastClockError(
                        "Ange en användare i FastClock under klockans inställning för att "
                        "starta eller stoppa härifrån."
                    )
            try:
                self.transport(settings, "start" if action == "start" else "stop", reason[:160])
            except FastClockError:
                with self.lock:
                    self.error = "FastClock bekräftade inte kommandot. Kontrollera klockan."
                raise
            try:
                sample = self.probe(settings)
            except FastClockError:
                with self.lock:
                    self.error = "Kommandot skickades, men klockans läge kunde inte bekräftas."
                    raise FastClockError(self.error) from None
            with self.lock:
                self._accept(sample)
