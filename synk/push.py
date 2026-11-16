"""Push (F20, SYNK-05): notices to the phones, the same way as the relay.

A hub with a key to Apple's push service (APNs) sends itself; that is the cloud. A Pi has no key:
it sends its notices to the cloud it is linked to, which sends them on. Without a key and without
a cloud the notices go to a pretend service that keeps the last ones, so that push can be tried
in the test environment before the key exists.

A phone's address (the token) is never written to a log; the pretend service shows only its
last characters.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from contracts import station
from contracts.sync import Push, PushBatch
from synk.link import LinkError

LOGGER = logging.getLogger("synk.push")
KEPT: Final = 50  # pushes the pretend service keeps
APNS: Final = "https://api.push.apple.com"
APNS_SANDBOX: Final = "https://api.sandbox.push.apple.com"
JWT_SECONDS: Final = 50 * 60  # Apple takes a token for an hour, and not a new one too often
ASKING: Final = {station.EventKind.CLEARANCE_REQUESTED, station.EventKind.CLEARANCE_REMINDER}


class PushSender(Protocol):
    @property
    def name(self) -> str: ...

    def send(self, pushes: list[Push]) -> None: ...


def payload(notice: station.Notice) -> dict[str, Any]:
    """The push as Apple takes it. A request has the category with Ge klart and Neka, which
    the app registers; the notice itself rides along for the answer."""
    aps: dict[str, Any] = {
        "alert": {"title": notice.title, "body": notice.body},
        "sound": "default",
        "thread-id": notice.place,
    }
    if notice.kind in ASKING:
        aps["category"] = "CLEARANCE_REQUEST"
        aps["interruption-level"] = "time-sensitive"
    return {"aps": aps, "trainmeet": notice.model_dump(mode="json")}


# --- The pretend service ------------------------------------------------------------------------


@dataclass(frozen=True)
class Sent:
    at: datetime
    place: str
    kind: str
    title: str
    body: str
    device: str  # the token's last characters, never the whole


class FakePush:
    """Låtsad push: keeps the last notices, to be looked at instead of a phone."""

    name = "fake"

    def __init__(self, kept: int = KEPT) -> None:
        self.sent: deque[Sent] = deque(maxlen=kept)

    def send(self, pushes: list[Push]) -> None:
        now = datetime.now(UTC)
        for push in pushes:
            notice = push.notice
            self.sent.append(
                Sent(
                    now,
                    notice.place,
                    notice.kind.value,
                    notice.title,
                    notice.body,
                    "…" + push.token.token[-6:],
                )
            )

    def recent(self) -> list[dict[str, str]]:
        return [
            {
                "at": sent.at.isoformat(),
                "place": sent.place,
                "kind": sent.kind,
                "title": sent.title,
                "body": sent.body,
                "device": sent.device,
            }
            for sent in reversed(self.sent)
        ]


# --- Through the cloud --------------------------------------------------------------------------


class CloudPush:
    """A Pi's notices, up to the cloud it is linked to for the meet (SYNK-11)."""

    name = "cloud"

    def __init__(
        self, send: Callable[[str, str, bytes], tuple[int, bytes]], meet: Callable[[], str | None]
    ) -> None:
        self._send = send
        self._meet = meet

    def send(self, pushes: list[Push]) -> None:
        meet = self._meet()
        if meet is None or not pushes:
            return
        body = PushBatch(pushes=pushes).model_dump_json().encode()
        try:
            status, _ = self._send(meet, f"/api/sync/1/meets/{meet}/push", body)
        except LinkError:
            LOGGER.warning("Molnet nås inte: %d notiser skickades inte", len(pushes))
            return
        if status != 204:
            LOGGER.warning("Molnet tog inte emot %d notiser (%d)", len(pushes), status)


# --- Apple's push service -----------------------------------------------------------------------


@dataclass(frozen=True)
class ApnsSettings:
    """The key from Apple's developer account: its id, the team's id, the app's bundle id
    (the topic) and the key itself (.p8). Read from the environment; never written out."""

    key_id: str
    team_id: str
    topic: str
    key: str = ""

    def __repr__(self) -> str:
        return (
            f"ApnsSettings(key_id={self.key_id!r}, team_id={self.team_id!r}, topic={self.topic!r})"
        )

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> ApnsSettings | None:
        source = os.environ if env is None else env
        values = [
            source.get(name, "").strip()
            for name in (
                "TRAINMEET_APNS_KEY_ID",
                "TRAINMEET_APNS_TEAM_ID",
                "TRAINMEET_APNS_TOPIC",
                "TRAINMEET_APNS_KEY",
            )
        ]
        if not all(values):
            return None
        key_id, team_id, topic, key = values
        return ApnsSettings(key_id, team_id, topic, key.replace("\\n", "\n"))


# A POST over HTTP/2: url, headers, body -> status, body
Post = Callable[[str, Mapping[str, str], bytes], tuple[int, bytes]]


class ApnsPush:
    """APNs with a token key: a signed token (ES256) an hour at a time, and HTTP/2, as Apple
    requires. A notice to a phone Apple no longer knows is let go; nothing is retried."""

    name = "apns"

    def __init__(self, settings: ApnsSettings, post: Post | None = None) -> None:
        self.settings = settings
        self._post = post
        self._token: tuple[float, str] | None = None

    def _bearer(self) -> str:
        now = time.time()
        if self._token is None or now - self._token[0] >= JWT_SECONDS:
            import jwt  # in the hub's image with the push group

            signed = jwt.encode(
                {"iss": self.settings.team_id, "iat": int(now)},
                self.settings.key,
                algorithm="ES256",
                headers={"kid": self.settings.key_id},
            )
            self._token = (now, signed)
        return self._token[1]

    def _http2(self) -> Post:
        if self._post is None:
            import httpx

            client = httpx.Client(http2=True, timeout=10.0)

            def post(url: str, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
                response = client.post(url, headers=dict(headers), content=body)
                return response.status_code, response.content

            self._post = post
        return self._post

    def send(self, pushes: list[Push]) -> None:
        post = self._http2()
        for push in pushes:
            notice = push.notice
            headers = {
                "authorization": f"bearer {self._bearer()}",
                "apns-topic": self.settings.topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-expiration": str(int(time.time()) + 300),
                "content-type": "application/json",
            }
            if notice.clearance_id:
                headers["apns-collapse-id"] = f"{notice.kind.value}:{notice.clearance_id}"[:64]
            host = APNS_SANDBOX if push.token.sandbox else APNS
            try:
                status, answer = post(
                    f"{host}/3/device/{push.token.token}",
                    headers,
                    json.dumps(payload(notice)).encode(),
                )
            except Exception as error:
                LOGGER.warning("APNs svarade inte: %s", type(error).__name__)
                continue
            if status != 200:
                LOGGER.warning("APNs tog inte emot en notis (%d, %s)", status, _reason(answer))


def _reason(answer: bytes) -> str:
    try:
        reason = json.loads(answer).get("reason")
    except (ValueError, AttributeError):
        return "okänt"
    return reason if isinstance(reason, str) else "okänt"
