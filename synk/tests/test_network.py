"""Pi:ns eget nät (SYNK-26, H45): ported with the old Server's tests (trainmeet-server #202,
tests/test_pi_network.py). No real network here: a pretend NetworkManager, and D-Bus mocked."""

from __future__ import annotations

import io
import json
import socket
import struct
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from synk.network import (
    NetworkController,
    NetworkError,
    fail,
    host_request,
    validate_profile,
)
from synk.network_host import HostHandler, NetworkManager

HOME = "11111111-1111-4111-8111-111111111111"
MEET = "22222222-2222-4222-8222-222222222222"


class FakeNetwork:
    """NetworkManager as the tests see it: two profiles, one checkpoint at a time."""

    def __init__(self) -> None:
        self.profiles: list[dict[str, Any]] = [
            dict(uuid=HOME, ssid="Hemma", security="wpa2", hidden=False, priority=10,
                 autoconnect=True, active=True, editable=True),
            dict(uuid=MEET, ssid="Träffens nät", security="wpa3", hidden=False, priority=0,
                 autoconnect=True, active=False, editable=True),
        ]  # fmt: skip
        self.secrets = {HOME: "private-home", MEET: "private-meet"}
        self.calls: list[tuple[Any, ...]] = []
        self.checkpoints: dict[str, list[dict[str, Any]]] = {}
        self.fail_activation = False
        self.ready = True

    def status(self) -> dict[str, Any]:
        active = next((p["uuid"] for p in self.profiles if p["active"]), "")
        device = dict(
            interface="wlan0",
            uuid=active,
            state=100 if self.ready else 40,
            addresses=["192.168.1.20"] if self.ready else [],
        )
        nearby = [dict(ssid="Klubblokalen", security=["wpa2"], signal=80, interface="wlan0")]
        return deepcopy(
            dict(profiles=self.profiles, radio_enabled=True, devices=[device], nearby=nearby)
        )

    def device(self, interface: str) -> str:
        if interface != "wlan0":
            fail("no_wifi", "Inget hanterat Wi-Fi-kort finns med det namnet.")
        return "/wifi/0"

    def scan(self, interface: str) -> None:
        self.calls.append(("scan", interface))

    def save(self, ident: str | None, data: dict[str, Any]) -> None:
        ident = ident or str(uuid4())
        old = next((p for p in self.profiles if p["uuid"] == ident), None)
        if data["password"]:
            self.secrets[ident] = data["password"]
        values = {k: v for k, v in data.items() if k != "password"}
        if old:
            old.update(values)
        else:
            self.profiles.append(
                dict(
                    uuid=ident, priority=-1, active=False, editable=True, autoconnect=True, **values
                )
            )

    def delete(self, ident: str) -> None:
        self.profiles = [p for p in self.profiles if p["uuid"] != ident]
        self.secrets.pop(ident, None)

    def order(self, ids: list[str]) -> None:
        for index, ident in enumerate(ids):
            next(p for p in self.profiles if p["uuid"] == ident)["priority"] = 900 - index
        self.profiles.sort(key=lambda p: -p["priority"])

    def checkpoint(self, device: str, seconds: int) -> str:
        self.calls.append(("checkpoint", device, seconds))
        self.checkpoints["/checkpoint/1"] = deepcopy(self.profiles)
        return "/checkpoint/1"

    def checkpoint_exists(self, path: str) -> bool:
        return path in self.checkpoints

    def has_checkpoints(self) -> bool:
        return bool(self.checkpoints)

    def activate(self, ident: str, device: str) -> None:
        if self.fail_activation:
            raise RuntimeError("secret-error-not-for-browser")
        self.calls.append(("activate", ident, device))
        for profile in self.profiles:
            profile["active"] = profile["uuid"] == ident

    def connected(self, interface: str, ident: str) -> bool:
        return self.ready and any(p["uuid"] == ident and p["active"] for p in self.profiles)

    def commit_checkpoint(self, path: str) -> None:
        self.calls.append(("commit", path))
        self.checkpoints.pop(path)

    def rollback(self, path: str) -> None:
        self.calls.append(("rollback", path))
        self.profiles = self.checkpoints.pop(path)


class Rig:
    def __init__(self) -> None:
        self.backend = FakeNetwork()
        self.now = 100.0
        self.controller = NetworkController(self.backend, lambda: self.now)

    def call(self, action: str, payload: dict[str, Any] | None = None, actor: str = "owner") -> Any:
        return self.controller.handle(action, payload or {}, actor)

    def denied(self, code: str, action: str, payload: dict[str, Any]) -> None:
        with pytest.raises(NetworkError) as error:
            self.call(action, payload)
        assert error.value.code == code

    def connect(self) -> Any:
        return self.call("connect", dict(uuid=MEET, interface="wlan0"))


@pytest.fixture
def rig() -> Rig:
    return Rig()


def test_status_never_contains_secrets(rig: Rig) -> None:
    result = json.dumps(rig.call("status"))
    assert "password" not in result and "private-" not in result


def test_save_does_not_activate_and_blank_keeps_the_password(rig: Rig) -> None:
    rig.call(
        "save", dict(uuid=MEET, ssid="Träffens nät", security="wpa3", password="", hidden=True)
    )
    assert rig.backend.secrets[MEET] == "private-meet"
    assert rig.backend.profiles[0]["active"]
    assert rig.backend.calls == []


def test_a_new_ssid_or_security_needs_a_new_password(rig: Rig) -> None:
    for values in (dict(ssid="Annat", security="wpa3"), dict(ssid="Träffens nät", security="wpa2")):
        rig.denied("invalid_password", "save", dict(uuid=MEET, **values))


def test_the_active_profile_cannot_be_changed_or_deleted(rig: Rig) -> None:
    rig.denied("active_profile", "delete", dict(uuid=HOME))
    rig.denied("active_profile", "save", dict(uuid=HOME, ssid="Hemma", security="wpa2"))


@pytest.mark.parametrize(
    "data",
    [
        dict(ssid="å" * 17, security="open"),
        dict(ssid="x\ny", security="open"),
        dict(ssid="", security="open"),
        dict(ssid="ok", security="wep"),
        dict(ssid="ok", security="open", hidden="false"),
        dict(ssid="ok", security="wpa2", password="short"),
        dict(ssid="ok", security="wpa2", password="x" * 64),
        dict(ssid="ok", security="wpa2", password="\n" * 10),
        dict(ssid="ok", security="open", command="reboot"),
        dict(ssid="ok", security="open", password="unexpected"),
    ],
)
def test_validation_byte_limits_controls_and_unknown_fields(data: dict[str, Any]) -> None:
    with pytest.raises(NetworkError):
        validate_profile(data)


def test_validation_counts_bytes() -> None:
    assert (
        validate_profile(dict(ssid="å" * 16, security="wpa2", password="x" * 63))["ssid"]
        == "å" * 16
    )


def test_duplicate_and_profile_limit(rig: Rig) -> None:
    rig.denied("duplicate_ssid", "save", dict(ssid="Hemma", security="open"))
    rig.backend.profiles *= 16
    rig.denied("profile_limit", "save", dict(ssid="Nytt", security="open"))


@pytest.mark.parametrize("action", ["save", "delete", "connect"])
def test_profiles_that_cannot_be_edited_are_left_alone(rig: Rig, action: str) -> None:
    rig.backend.profiles[1]["editable"] = False
    payload = dict(uuid=MEET, interface="wlan0") if action == "connect" else dict(uuid=MEET)
    rig.denied("invalid_profile", action, payload)


def test_order_takes_exactly_the_ids_and_never_activates(rig: Rig) -> None:
    for ids in ([MEET], [HOME, HOME], [MEET, "foreign"], [None, HOME]):
        rig.denied("stale_profiles", "order", dict(uuids=ids))
    rig.call("order", dict(uuids=[MEET, HOME]))
    assert [p["uuid"] for p in rig.backend.profiles] == [MEET, HOME]
    assert rig.backend.connected("wlan0", HOME)


def test_scan_is_rate_limited_and_the_card_is_checked(rig: Rig) -> None:
    rig.call("scan", dict(interface="wlan0"))
    rig.call("scan", dict(interface="wlan0"))
    assert len(rig.backend.calls) == 1
    rig.now += 11
    rig.call("scan", dict(interface="wlan0"))
    assert len(rig.backend.calls) == 2
    rig.denied("no_wifi", "scan", dict(interface="eth0"))


def test_a_trial_uses_networkmanagers_checkpoint_and_keeping_needs_an_address(rig: Rig) -> None:
    result = rig.connect()
    assert rig.backend.calls[0] == ("checkpoint", "/wifi/0", 90)
    rig.backend.ready = False
    rig.denied("not_connected", "confirm", dict(token=result["trial"]["token"]))
    rig.backend.ready = True
    assert rig.call("confirm", dict(token=result["trial"]["token"]))["trial"] is None
    assert not rig.backend.has_checkpoints()
    assert rig.backend.connected("wlan0", MEET)


def test_the_trial_belongs_to_one_administrator_and_locks_other_changes(rig: Rig) -> None:
    result = rig.connect()
    assert rig.connect()["trial"] == result["trial"]
    assert rig.call("status", actor="other")["trial"]["token"] is None
    with pytest.raises(NetworkError):
        rig.call("confirm", dict(token=result["trial"]["token"]), actor="other")
    rig.denied("trial_pending", "delete", dict(uuid=HOME))
    rig.denied("invalid_trial", "rollback", dict(token="incorrect"))
    rig.call("rollback", dict(token=result["trial"]["token"]))
    assert rig.backend.connected("wlan0", HOME)


def test_a_timeout_or_a_restart_never_cancels_networkmanagers_timer(rig: Rig) -> None:
    result = rig.connect()
    rig.now += 91
    status = rig.call("status")
    assert status["trial"] is None and status["recovering"]
    rig.denied("invalid_trial", "confirm", dict(token=result["trial"]["token"]))
    rig.controller = NetworkController(rig.backend)
    rig.denied("network_recovering", "order", dict(uuids=[HOME, MEET]))
    rig.backend.rollback("/checkpoint/1")  # NetworkManager's own timer ran out
    assert not rig.call("status")["recovering"]


def test_a_failed_activation_goes_back_and_says_nothing_secret(rig: Rig) -> None:
    rig.backend.fail_activation = True
    with pytest.raises(NetworkError) as error:
        rig.connect()
    assert error.value.code == "activation_failed"
    assert "secret-error" not in str(error.value)
    assert rig.backend.connected("wlan0", HOME)
    assert rig.controller.pending is None


def test_a_hub_without_the_helper_is_safe() -> None:
    with patch("synk.network.socket.socket", side_effect=OSError("not installed")):
        assert host_request()["supported"] is False
        with pytest.raises(NetworkError):
            host_request("save", {})


# --- The helper's NetworkManager, with D-Bus mocked -----------------------------------------


@pytest.fixture
def nm() -> tuple[NetworkManager, Mock, dict[str, Any]]:
    manager = NetworkManager.__new__(NetworkManager)
    manager.dbus = SimpleNamespace(
        Dictionary=lambda x, **kw: dict(x),
        Array=lambda x, **kw: list(x),
        Int32=int,
        UInt32=int,
        Boolean=bool,
        ByteArray=bytes,
    )
    config: dict[str, Any] = {
        "connection": {"uuid": HOME, "type": "802-11-wireless", "id": "original",
                       "autoconnect-priority": 2},
        "802-11-wireless": {"ssid": b"Hemma", "mode": "infrastructure"},
        "802-11-wireless-security": {"key-mgmt": "wpa-psk", "psk-flags": 0},
        "ipv4": {"method": "manual", "address-data": [{"address": "192.168.1.9", "prefix": 24}]},
    }  # fmt: skip
    api = Mock()
    api.GetSecrets.return_value = {"802-11-wireless-security": {"psk": "must-stay-private"}}
    manager.iface = Mock(return_value=api)  # type: ignore[method-assign]
    manager.connection = Mock(side_effect=lambda _: ("/profile/1", deepcopy(config)))  # type: ignore[method-assign]
    manager.connections = Mock(return_value=[("/profile/1", deepcopy(config))])  # type: ignore[method-assign]
    manager.settings = Mock()
    manager.status = Mock(return_value={"profiles": [{"uuid": HOME, "active": True}]})  # type: ignore[method-assign]
    return manager, api, config


def test_the_profile_shows_only_what_may_be_shown(
    nm: tuple[NetworkManager, Mock, dict[str, Any]],
) -> None:
    manager, _, config = nm
    config = deepcopy(config)
    config["802-11-wireless-security"]["psk"] = "do-not-return"
    public = manager.profile("/profile/1", config, {"/profile/1"})
    assert public["editable"] and "do-not-return" not in json.dumps(public)
    for key, value in (("key-mgmt", "wpa-eap"), ("psk-flags", 1)):
        changed = deepcopy(config)
        changed["802-11-wireless-security"][key] = value
        assert not manager.profile("x", changed, set())["editable"]
    config["802-11-wireless"]["mode"] = "ap"
    assert not manager.profile("x", config, set())["editable"]


def test_save_keeps_ip_and_the_secret_and_never_starts(
    nm: tuple[NetworkManager, Mock, dict[str, Any]],
) -> None:
    manager, api, config = nm
    manager.save(HOME, dict(ssid="Hemma", security="wpa2", password="", hidden=True))
    saved, flags, _ = api.Update2.call_args.args
    assert flags == 0x21
    assert saved["ipv4"] == config["ipv4"]
    assert saved["802-11-wireless-security"]["psk"] == "must-stay-private"
    assert saved["802-11-wireless"]["hidden"]


def test_a_new_profile_is_kept_last_in_priority(
    nm: tuple[NetworkManager, Mock, dict[str, Any]],
) -> None:
    manager, _, _ = nm
    manager.save(None, dict(ssid="Klubb", security="wpa3", password="long-secret", hidden=False))
    saved, flags, _ = manager.settings.AddConnection2.call_args.args
    assert flags == 0x21
    assert saved["connection"]["autoconnect-priority"] == 1
    assert saved["802-11-wireless-security"]["key-mgmt"] == "sae"
    assert saved["ipv4"]["method"] == "auto"


def test_order_keeps_secrets_and_lets_the_active_one_reconnect(
    nm: tuple[NetworkManager, Mock, dict[str, Any]],
) -> None:
    manager, api, _ = nm
    manager.order([HOME])
    saved, flags, _ = api.Update2.call_args.args
    assert flags == 0x41
    assert saved["802-11-wireless-security"]["psk"] == "must-stay-private"
    assert saved["connection"]["autoconnect-priority"] == 900
    manager.status.return_value = {"profiles": []}  # type: ignore[attr-defined]
    manager.order([HOME])
    assert api.Update2.call_args.args[1] == 0x61


def test_a_failed_reorder_puts_things_back(nm: tuple[NetworkManager, Mock, dict[str, Any]]) -> None:
    manager, api, _ = nm
    api.Update2.side_effect = [RuntimeError("network lost"), None]
    with pytest.raises(RuntimeError):
        manager.order([HOME])
    assert api.Update2.call_count == 2
    assert api.Update2.call_args.args[0]["connection"]["autoconnect-priority"] == 2


# --- The helper's socket: only the hub's own user, and nothing raw back -------------------


def handler(uid: int, raw: bytes, controller: Any = None) -> HostHandler:
    made = HostHandler.__new__(HostHandler)
    made.request = Mock()
    made.request.getsockopt.return_value = struct.pack("3i", 1, uid, 100)
    made.rfile = io.BytesIO(raw)
    made.wfile = io.BytesIO()
    made.server = SimpleNamespace(allowed_uid=100, controller=controller or Mock())  # type: ignore[assignment]
    with patch.object(socket, "SO_PEERCRED", 17, create=True):
        made.handle()
    return made


def test_only_the_hubs_user_reaches_the_controller() -> None:
    made = handler(501, b"{}\n")
    made.server.controller.handle.assert_not_called()  # type: ignore[attr-defined]
    assert made.wfile.getvalue() == b""  # type: ignore[attr-defined]


def test_the_helper_never_returns_raw_dbus_errors() -> None:
    controller = Mock()
    controller.handle.side_effect = RuntimeError("psk=really-private-password")
    body = json.dumps(dict(action="save", actor="owner", payload={})).encode() + b"\n"
    response = handler(100, body, controller).wfile.getvalue()  # type: ignore[attr-defined]
    assert b"really-private" not in response
    assert json.loads(response)["error"] == "network_failed"


@pytest.mark.parametrize("raw", [b"{}", b"x" * 65537 + b"\n", b'{"command":"reboot"}\n'])
def test_incomplete_oversize_and_unknown_envelopes_are_refused(raw: bytes) -> None:
    made = handler(100, raw)
    made.server.controller.handle.assert_not_called()  # type: ignore[attr-defined]
    assert json.loads(made.wfile.getvalue())["error"] == "network_failed"  # type: ignore[attr-defined]
