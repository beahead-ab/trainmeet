"""Pi:ns eget nät (SYNK-07, SYNK-23, SYNK-26, H45): the Pi's Wi-Fi profiles, never the meet's.

Ported from the old Server (trainmeet-server #202), with its tests. The meet's Wi-Fi, shown to
the participants and on the screens, is something else and lives in the meet. These profiles
and their passwords never leave the Pi: not to the cloud, the boxes, the participants or a
backup.

The hub is an unprivileged client of a fixed local socket. A small helper running as root
(synk.network_host) owns the few allowed operations, and NetworkManager owns every secret. A
change of the Pi's network is tried: NetworkManager takes a checkpoint first and goes back to it
by itself after 90 seconds, even if the hub or the helper dies, unless the change is kept. A
password is passed on in memory and never comes back.
"""

from __future__ import annotations

import json
import secrets
import socket
import time
from collections.abc import Callable
from typing import Any, Final, NoReturn, Protocol
from uuid import UUID

SOCKET_PATH: Final = "/run/trainmeet-network/control.sock"
MAX_BYTES: Final = 65536
TRIAL_SECONDS: Final = 90
SECURITY: Final = {"open", "wpa2", "wpa3"}
SCAN_SECONDS: Final = 10
MAX_PROFILES: Final = 32


class NetworkError(ValueError):
    """The message is for the administrator; the code for the page."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> NoReturn:
    raise NetworkError(code, message)


def uuid_value(value: object) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        fail("invalid_profile", "Ogiltig nätverksprofil.")
    return value


def _controls(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def validate_profile(data: object, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """A profile to save: SSID, security, password and hidden, and nothing else. An empty
    password keeps the saved one, but only when SSID and security are the same."""
    if not isinstance(data, dict) or set(data) - {"uuid", "ssid", "security", "password", "hidden"}:
        fail("invalid_profile", "Ogiltig nätverksprofil.")
    ssid = data.get("ssid")
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32 or _controls(ssid):
        fail("invalid_ssid", "SSID ska vara 1–32 byte och får inte innehålla kontrolltecken.")
    security = data.get("security")
    if (
        not isinstance(security, str)
        or security not in SECURITY
        or type(data.get("hidden", False)) is not bool
    ):
        fail("invalid_security", "Välj WPA2, WPA3 eller öppet nätverk.")
    password = data.get("password", "")
    if not isinstance(password, str) or _controls(password):
        fail("invalid_password", "Ogiltigt Wi-Fi-lösenord.")
    keep = (
        not password
        and existing is not None
        and existing["security"] == security
        and existing["ssid"] == ssid
    )
    # Personal passphrases, not raw 64-digit keys. The same rule for WPA3.
    if security != "open" and not keep and not 8 <= len(password.encode("utf-8")) <= 63:
        fail("invalid_password", "Wi-Fi-lösenordet ska vara 8–63 byte.")
    if security == "open" and password:
        fail("invalid_password", "Öppet nätverk ska inte ha lösenord.")
    return {
        "ssid": ssid,
        "security": security,
        "hidden": data.get("hidden", False),
        "password": password,
    }


def host_request(
    action: str = "status",
    payload: dict[str, Any] | None = None,
    actor: str = "",
    path: str = SOCKET_PATH,
) -> dict[str, Any]:
    """Ask the helper on the Pi. No credentials in file names, arguments, logs or errors."""
    request = (
        json.dumps({"action": action, "payload": payload or {}, "actor": actor}).encode() + b"\n"
    )
    if len(request) > MAX_BYTES:
        fail("invalid_request", "Nätverksbegäran är för stor.")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(12)
            client.connect(path)
            client.sendall(request)
            with client.makefile("rb") as stream:
                raw = stream.readline(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or not raw.endswith(b"\n"):
            raise ValueError
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
    except (OSError, ValueError):
        if action == "status":
            return {
                "supported": False,
                "reason": "Pi:ns nät ställs in på en Raspberry Pi med TrainMeets nätverkstjänst.",
            }
        fail(
            "host_unavailable",
            "Pi:ns nätverkstjänst svarar inte. Se efter läget innan du försöker igen.",
        )
    if "error" in result:
        fail(str(result["error"]), str(result.get("message", "")))
    return result


class Backend(Protocol):
    """NetworkManager as the helper reaches it; a pretend one in the tests."""

    def status(self) -> dict[str, Any]: ...
    def device(self, interface: str) -> str: ...
    def scan(self, interface: str) -> None: ...
    def save(self, ident: str | None, data: dict[str, Any]) -> None: ...
    def delete(self, ident: str) -> None: ...
    def order(self, ids: list[str]) -> None: ...
    def checkpoint(self, device: str, seconds: int) -> str: ...
    def checkpoint_exists(self, path: str) -> bool: ...
    def has_checkpoints(self) -> bool: ...
    def activate(self, ident: str, device: str) -> None: ...
    def connected(self, interface: str, ident: str) -> bool: ...
    def commit_checkpoint(self, path: str) -> None: ...
    def rollback(self, path: str) -> None: ...


class NetworkController:
    """In the helper: one request at a time. The trial's token goes only to the one who
    started it."""

    def __init__(self, backend: Backend, clock: Callable[[], float] = time.monotonic) -> None:
        self.backend = backend
        self.clock = clock
        self.pending: dict[str, Any] | None = None
        self.last_scan: dict[str, float] = {}

    def _expire(self) -> None:
        pending = self.pending
        if pending and (
            self.clock() >= pending["deadline"]
            or not self.backend.checkpoint_exists(pending["checkpoint"])
        ):
            # NetworkManager's timer runs on its own. Never destroy an expired checkpoint:
            # that would cancel a rollback still on its way.
            self.pending = None

    def status(self, actor: str) -> dict[str, Any]:
        self._expire()
        result = self.backend.status()
        result["supported"] = True
        result["recovering"] = not self.pending and self.backend.has_checkpoints()
        pending = self.pending
        result["trial"] = None
        if pending:
            result["trial"] = {
                "uuid": pending["uuid"],
                "interface": pending["interface"],
                "remaining": max(0, int(pending["deadline"] - self.clock())),
                "token": pending["token"] if pending["actor"] == actor else None,
            }
        return result

    def handle(self, action: object, payload: object, actor: object) -> dict[str, Any]:
        if (
            not isinstance(action, str)
            or not isinstance(payload, dict)
            or not isinstance(actor, str)
            or not actor
            or len(actor) > 160
        ):
            fail("invalid_request", "Ogiltig nätverksbegäran.")
        self._expire()
        if action == "status":
            return self.status(actor)
        if action in {"confirm", "rollback"}:
            pending = self.pending
            if (
                set(payload) != {"token"}
                or not pending
                or pending["actor"] != actor
                or not secrets.compare_digest(str(payload["token"]), pending["token"])
            ):
                fail(
                    "invalid_trial",
                    "Provanslutningen är slut, eller tillhör en annan administratör.",
                )
            if action == "confirm":
                if not self.backend.connected(pending["interface"], pending["uuid"]):
                    fail("not_connected", "Det nya nätet är inte anslutet än.")
                self.backend.commit_checkpoint(pending["checkpoint"])
            else:
                self.backend.rollback(pending["checkpoint"])
            self.pending = None
            return self.status(actor)
        if self.pending:
            # Trying a connect again after a timeout must not start a second trial.
            if (
                action == "connect"
                and self.pending["actor"] == actor
                and payload
                == {"uuid": self.pending["uuid"], "interface": self.pending["interface"]}
            ):
                return self.status(actor)
            fail("trial_pending", "Behåll eller återställ den pågående provanslutningen först.")
        if self.backend.has_checkpoints():
            # After a restart of the helper NetworkManager still owns the timer: never cancel
            # or overwrite that checkpoint, or another administrator's.
            fail("network_recovering", "Nätet återställs just nu. Vänta tills det är klart.")
        profiles: list[dict[str, Any]] = self.backend.status()["profiles"]
        if action == "scan":
            if set(payload) != {"interface"}:
                fail("invalid_request", "Välj ett trådlöst nätverkskort.")
            interface = str(payload["interface"])
            self.backend.device(interface)
            if self.clock() - self.last_scan.get(interface, -100.0) >= SCAN_SECONDS:
                self.backend.scan(interface)
                self.last_scan[interface] = self.clock()
        elif action == "save":
            ident = payload.get("uuid")
            existing = self._profile(profiles, ident) if ident else None
            data = validate_profile(payload, existing)
            if any(p["ssid"] == data["ssid"] and p["uuid"] != ident for p in profiles):
                fail("duplicate_ssid", "Nätet finns redan. Ändra den sparade profilen.")
            if not existing and len(profiles) >= MAX_PROFILES:
                fail("profile_limit", "Högst 32 Wi-Fi-profiler kan hanteras här.")
            # Never change a live profile's password: a later trial could then no longer go
            # back to the one before.
            if existing and existing["active"]:
                fail("active_profile", "Byt till ett annat nät innan det aktiva ändras.")
            self.backend.save(str(ident) if ident else None, data)
        elif action == "delete":
            if set(payload) != {"uuid"}:
                fail("invalid_profile", "Ogiltig nätverksprofil.")
            profile = self._profile(profiles, payload["uuid"])
            if profile["active"]:
                fail("active_profile", "Det aktiva nätet kan inte tas bort.")
            self.backend.delete(profile["uuid"])
        elif action == "order":
            ids = payload.get("uuids")
            expected = {p["uuid"] for p in profiles if p["editable"]}
            if (
                set(payload) != {"uuids"}
                or not isinstance(ids, list)
                or not all(isinstance(i, str) for i in ids)
                or len(ids) != len(set(ids))
                or set(ids) != expected
            ):
                fail("stale_profiles", "Listan över nät har ändrats. Läs in den igen.")
            self.backend.order(ids)
        elif action == "connect":
            if set(payload) != {"uuid", "interface"}:
                fail("invalid_request", "Välj nät och nätverkskort.")
            profile = self._profile(profiles, payload["uuid"])
            interface = str(payload["interface"])
            device = self.backend.device(interface)
            if self.backend.connected(interface, profile["uuid"]):
                return self.status(actor)
            checkpoint = self.backend.checkpoint(device, TRIAL_SECONDS)
            self.pending = {
                "checkpoint": checkpoint,
                "uuid": profile["uuid"],
                "interface": interface,
                "token": secrets.token_urlsafe(24),
                "actor": actor,
                "deadline": self.clock() + TRIAL_SECONDS,
            }
            try:
                self.backend.activate(profile["uuid"], device)
            except Exception:
                self.backend.rollback(checkpoint)
                self.pending = None
                fail(
                    "activation_failed",
                    "Anslutningen kunde inte starta. Nätet före återställs.",
                )
        else:
            fail("invalid_action", "Okänd nätverksåtgärd.")
        return self.status(actor)

    @staticmethod
    def _profile(profiles: list[dict[str, Any]], ident: object) -> dict[str, Any]:
        wanted = uuid_value(ident)
        profile = next((p for p in profiles if p["uuid"] == wanted), None)
        if not profile or not profile["editable"]:
            fail("invalid_profile", "Den här profilen kan inte hanteras här.")
        return profile
