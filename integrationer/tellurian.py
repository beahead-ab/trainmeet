"""Tellurian Dispatch i skugga (H79, IMPORT-34, T10): read Tellurian's clearances beside Drift's.

Ported from the old Server's integrations/tellurian.py, read path only. The hub talks HTTP to
Tellurian's server under /api/v1 (HATEOAS) and never links its GPL library. Nothing is ever
written to Tellurian: the transport only knows GET, and actions in Tellurian's answers are not
read at all.

Only a local address (private IPv4, link-local or a `.local` name) is accepted, unless the
administrator chose a test instance; trainmeet.app never. No redirects, no proxy, a timeout and
a size limit on every read. Tellurian's own answers never end up in an error or a log: an error
carries only a short code.

    GET /api/v1/dispatchers         the dispatchers, one per station
    GET /api/v1/dispatchers/{id}    a dispatcher's arrivals and departures (or its own href)
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol
from urllib.parse import urlsplit

from contracts.drift import (
    Now,
    NowPlace,
    TellurianContact,
    TellurianSection,
    TellurianShadow,
    TellurianState,
)
from contracts.meet import MeetPackage
from contracts.station import Clearance, ClearanceStatus

API_PREFIX: Final = "/api/v1/"
SIMULATOR_HEADER: Final = "X-Tellurian-Simulator"
TRAIN_STATES: Final = ("Planned", "Manned", "Running", "Canceled", "Aborted", "Completed")

TIMEOUT: Final = 3.0
MAX_RESPONSE_BYTES: Final = 1_048_576
MAX_DISPATCHERS: Final = 200
MAX_SECTIONS: Final = 500
#: No answer for this long is "ingen kontakt".
CONTACT_TIMEOUT: Final = timedelta(seconds=15)

_PRIVATE_V4: Final = tuple(
    ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_LINK_LOCAL_V4: Final = ipaddress.IPv4Network("169.254.0.0/16")
_SAFE_PATH: Final = re.compile(r"/api/v1/[A-Za-z0-9_\-/]+")
_ID: Final = re.compile(r"[A-Za-z0-9_\-]{1,64}")
_HEADERS: Final = {
    "Accept": "application/json",
    "Connection": "close",
    "User-Agent": "TrainMeet-Hub",
}

Kind = Literal["private", "link_local", "mdns", "loopback", "public"]
Resolver = Callable[[str, int, int, int], Sequence[tuple[Any, ...]]]


# --- Errors and the address -----------------------------------------------------------------


class TellurianError(Exception):
    """A read failed. `code` is all there is: never Tellurian's text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AddressRejected(ValueError):
    """The administrator's address is not accepted. `code` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Endpoint:
    """Tellurian's origin: scheme, host and port, never a path."""

    scheme: Literal["http", "https"]
    host: str
    port: int
    kind: Kind
    test_instance: bool

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"

    @property
    def local(self) -> bool:
        return self.kind in ("private", "link_local", "mdns")


def _is_local_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and (
        address in _LINK_LOCAL_V4 or any(address in network for network in _PRIVATE_V4)
    )


def classify_host(host: str) -> Kind:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host.endswith(".localhost"):
            return "loopback"
        return "mdns" if host.endswith(".local") and len(host) > len(".local") else "public"
    if isinstance(address, ipaddress.IPv4Address):
        if address.is_loopback:
            return "loopback"
        if address in _LINK_LOCAL_V4:
            return "link_local"
        if any(address in network for network in _PRIVATE_V4):
            return "private"
    return "public"


def check_address(raw: str, *, test_instance: bool = False) -> Endpoint:
    """The administrator's address to Tellurian: an origin only, never a path.

    Local means private IPv4, link-local (169.254/16) or a `.local` name, and HTTP is fine
    there. Anything else, loopback and IPv6 too, needs the choice "testinstans". TrainMeet's
    own domain is never accepted: clearance traffic does not go there.
    """
    text = raw.strip()
    if not text:
        raise AddressRejected("address_required")
    if len(text) > 255 or any(ord(c) < 33 for c in text):
        raise AddressRejected("address_invalid")
    if "://" not in text:
        text = "http://" + text
    try:
        url = urlsplit(text)
        port = url.port
    except ValueError:
        raise AddressRejected("address_invalid") from None
    if url.scheme not in ("http", "https"):
        raise AddressRejected("address_scheme")
    if url.username is not None or url.password is not None:
        raise AddressRejected("address_credentials")
    if url.query or url.fragment or url.path not in ("", "/"):
        raise AddressRejected("address_path")
    if port == 0:
        raise AddressRejected("address_invalid")
    host = (url.hostname or "").rstrip(".").lower()
    if not host:
        raise AddressRejected("address_required")
    if host == "trainmeet.app" or host.endswith(".trainmeet.app"):
        raise AddressRejected("address_trainmeet_cloud")
    kind = classify_host(host)
    if kind not in ("private", "link_local", "mdns") and not test_instance:
        raise AddressRejected("address_not_local")
    scheme: Literal["http", "https"] = "https" if url.scheme == "https" else "http"
    return Endpoint(scheme, host, port or (443 if scheme == "https" else 80), kind, test_instance)


def safe_href(value: object, endpoint: Endpoint) -> str | None:
    """A server-given `href` as a path under /api/v1/ on the same origin, otherwise None."""
    if not isinstance(value, str) or not value or len(value) > 300:
        return None
    path = value
    if "://" in value or value.startswith("//"):
        try:
            url = urlsplit(value)
            port = url.port or (443 if url.scheme == "https" else 80)
        except ValueError:
            return None
        if (url.scheme, (url.hostname or "").lower(), port) != (
            endpoint.scheme,
            endpoint.host,
            endpoint.port,
        ):
            return None
        if url.query or url.fragment or url.username or url.password:
            return None
        path = url.path
    if not _SAFE_PATH.fullmatch(path) or "//" in path:
        return None
    return path


# --- Transport ------------------------------------------------------------------------------


class Transport(Protocol):
    """Reads a path under /api/v1/ and gives the parsed JSON. Injected in tests."""

    simulated: bool

    def get(self, path: str) -> object: ...


class _PinnedHTTP(http.client.HTTPConnection):
    """Connects to the address resolved and checked beforehand, not to the name again."""

    def __init__(self, host: str, port: int, address: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, timeout: float) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._tls)
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        try:
            self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class HttpTransport:
    """GET with http.client: no proxy, cookies or redirects, one connection per read."""

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float = TIMEOUT,
        max_bytes: int = MAX_RESPONSE_BYTES,
        resolver: Resolver = socket.getaddrinfo,
    ) -> None:
        if not 0 < timeout <= 30:
            raise ValueError("timeout")
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.simulated = False
        self._resolver = resolver

    def pinned_address(self) -> str:
        """Resolve the name, and for a local endpoint check that the address still is local.

        A `.local` name that points at a public address, or that changes between the check
        and the read, must not lead out of the meet's network.
        """
        family = socket.AF_INET if self.endpoint.local else socket.AF_UNSPEC
        try:
            infos = self._resolver(
                self.endpoint.host, self.endpoint.port, family, socket.SOCK_STREAM
            )
        except (OSError, UnicodeError):
            raise TellurianError("unreachable") from None
        addresses = [str(info[4][0]) for info in infos]
        if self.endpoint.local:
            addresses = [a for a in addresses if _is_local_ip(a)]
            if not addresses:
                raise TellurianError("address_not_local")
        if not addresses:
            raise TellurianError("unreachable")
        return addresses[0]

    def get(self, path: str) -> object:
        if not _SAFE_PATH.fullmatch(path) or "//" in path:
            raise ValueError("path")
        pinned = _PinnedHTTPS if self.endpoint.scheme == "https" else _PinnedHTTP
        connection = pinned(
            self.endpoint.host, self.endpoint.port, self.pinned_address(), self.timeout
        )
        response: http.client.HTTPResponse | None = None
        try:
            try:
                connection.connect()
            except OSError:
                raise TellurianError("unreachable") from None
            connection.request("GET", path, headers=_HEADERS)
            response = connection.getresponse()
            if response.getheader(SIMULATOR_HEADER):
                self.simulated = True
            status = response.status
            if 300 <= status < 400:
                raise TellurianError("redirect")
            body = response.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise TellurianError("too_large")
            if not 200 <= status < 300:
                raise TellurianError(f"http_{status}")
        except TellurianError:
            raise
        except TimeoutError:
            raise TellurianError("timeout") from None
        except (http.client.HTTPException, OSError):
            raise TellurianError("unreachable") from None
        finally:
            # With Connection: close the response owns the socket, also when left unread.
            if response is not None:
                response.close()
            connection.close()
        try:
            return json.loads(body)
        except (ValueError, RecursionError):
            raise TellurianError("bad_json") from None


# --- Tellurian's answers --------------------------------------------------------------------


@dataclass(frozen=True)
class Dispatcher:
    id: str
    signature: str
    name: str
    href: str


@dataclass(frozen=True)
class Section:
    """One train on one section, as a dispatcher shows it."""

    id: str
    train: str
    train_id: str | None
    train_state: str
    state: TellurianState
    current: int
    total: int
    from_code: str | None
    to_code: str | None
    departure_time: str = ""
    arrival_time: str = ""


@dataclass(frozen=True)
class DispatcherView:
    dispatcher: Dispatcher
    arrivals: tuple[Section, ...]
    departures: tuple[Section, ...]

    def sections(self) -> tuple[Section, ...]:
        return self.arrivals + self.departures

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections() if s.id == section_id), None)


def _text(value: object, limit: int = 120) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    text = str(value).strip()
    if not text or any(ord(c) < 32 for c in text):
        return None
    return text[:limit]


def _ident(value: object) -> str | None:
    text = _text(value, 64)
    return text if text is not None and _ID.fullmatch(text) else None


def _int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 1000:
        return value
    return default


def _signature(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("signature") or value.get("station")
        text = _text(value, 20)
        if text:
            return text
    return None


def parse_dispatchers(data: object, endpoint: Endpoint) -> tuple[Dispatcher, ...]:
    """GET /api/v1/dispatchers: a list, or an object with `dispatchers` or `items`."""
    rows = data.get("dispatchers", data.get("items")) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise TellurianError("bad_shape")
    found: list[Dispatcher] = []
    seen: set[str] = set()
    for row in rows[:MAX_DISPATCHERS]:
        if not isinstance(row, dict):
            continue
        ident, signature = _ident(row.get("id")), _text(row.get("signature"), 20)
        if ident is None or signature is None or ident in seen:
            continue
        seen.add(ident)
        link = row.get("href")
        links = row.get("links")
        if link is None and isinstance(links, list):
            link = next(
                (
                    item.get("href")
                    for item in links
                    if isinstance(item, dict) and item.get("rel") in ("self", "dispatcher")
                ),
                None,
            )
        # The server's own link goes first; the documented path is the fallback.
        href = safe_href(link, endpoint) or f"{API_PREFIX}dispatchers/{ident}"
        name = _text(row.get("name") or row.get("stationName"), 80) or signature
        found.append(Dispatcher(ident, signature, name, href))
    return tuple(found)


def _parse_section(row: object, *, departure: bool, own: str) -> Section | None:
    if not isinstance(row, dict):
        return None
    ident, train = _ident(row.get("id")), _text(row.get("train"), 80)
    if ident is None or train is None:
        return None
    raw_state, raw_train_state = row.get("state"), row.get("trainState")
    states = {state.value for state in TellurianState}
    state = TellurianState(raw_state) if raw_state in states else TellurianState.UNKNOWN
    train_state = raw_train_state if isinstance(raw_train_state, str) else ""
    from_code = _signature(row, "from", "fromSignature", "departure")
    to_code = _signature(row, "to", "toSignature", "arrival")
    # A departure in a dispatcher's list leaves its station, an arrival comes to it.
    if departure:
        from_code = from_code or own
    else:
        to_code = to_code or own
    return Section(
        id=ident,
        train=train,
        train_id=_ident(row.get("trainId")),
        train_state=train_state if train_state in TRAIN_STATES else "Unknown",
        state=state,
        current=_int(row.get("currentTrackStretch"), 0),
        total=max(1, _int(row.get("totalTrackStretches"), 1)),
        from_code=from_code,
        to_code=to_code,
        departure_time=_text(row.get("departureTime"), 20) or "",
        arrival_time=_text(row.get("arrivalTime"), 20) or "",
    )


def _parse_list(rows: object, *, departure: bool, own: str) -> tuple[Section, ...]:
    if not isinstance(rows, list):
        return ()
    parsed = (_parse_section(row, departure=departure, own=own) for row in rows[:MAX_SECTIONS])
    return tuple(section for section in parsed if section is not None)


def parse_dispatcher_view(data: object, dispatcher: Dispatcher) -> DispatcherView:
    """GET of a dispatcher: its arrivals and departures. Another dispatcher's id is refused."""
    if not isinstance(data, dict):
        raise TellurianError("bad_shape")
    returned = _ident(data.get("id"))
    if returned is not None and returned != dispatcher.id:
        raise TellurianError("bad_shape")
    own = dispatcher.signature
    return DispatcherView(
        dispatcher,
        _parse_list(data.get("arrivals"), departure=False, own=own),
        _parse_list(data.get("departures"), departure=True, own=own),
    )


def _number_text(text: str) -> str | None:
    return str(int(text)) if text.isascii() and text.isdigit() else None


def parse_train_label(label: str) -> tuple[str, str, str | None]:
    """Company, prefix and number: "SJ IC 456" -> ("SJ", "IC", "456"). No number is None."""
    parts = label.split()
    number = _number_text(parts[-1]) if parts else None
    if number is None:
        return "", "", None
    if len(parts) >= 3:
        return parts[0], " ".join(parts[1:-1]), number
    if len(parts) == 2:
        return "", parts[0], number
    return "", "", number


def _number(value: str) -> str:
    """Drift's train number in the same form as a parsed label: "007" -> "7"."""
    text = value.strip()
    return _number_text(text) or text


def merged_sections(views: Iterable[DispatcherView]) -> list[Section]:
    """A section shows at both its dispatchers; merge what they know, once per section."""
    merged: dict[str, Section] = {}
    for view in views:
        for section in view.sections():
            known = merged.get(section.id)
            merged[section.id] = (
                section
                if known is None
                else replace(
                    section,
                    train_id=section.train_id or known.train_id,
                    from_code=known.from_code or section.from_code,
                    to_code=known.to_code or section.to_code,
                    departure_time=known.departure_time or section.departure_time,
                    arrival_time=known.arrival_time or section.arrival_time,
                )
            )
    return list(merged.values())


# --- The client -----------------------------------------------------------------------------


class TellurianClient:
    """Reads Tellurian. There is no write path."""

    def __init__(
        self, endpoint: Endpoint, *, timeout: float = TIMEOUT, transport: Transport | None = None
    ) -> None:
        self.endpoint = endpoint
        self.transport: Transport = transport or HttpTransport(endpoint, timeout=timeout)

    @property
    def simulated(self) -> bool:
        """An answer came from the simulator, not from Tellurian itself."""
        return self.transport.simulated

    def dispatchers(self) -> tuple[Dispatcher, ...]:
        return parse_dispatchers(self.transport.get(f"{API_PREFIX}dispatchers"), self.endpoint)

    def view(self, dispatcher: Dispatcher) -> DispatcherView:
        return parse_dispatcher_view(self.transport.get(dispatcher.href), dispatcher)

    def views(self) -> list[DispatcherView]:
        """Every dispatcher's view, read once."""
        return [self.view(dispatcher) for dispatcher in self.dispatchers()]


# --- Skuggan: Tellurian beside Drift --------------------------------------------------------

#: Tellurian's states that hold a clearance, in the words Drift's clearances are compared in.
_OPEN: Final = {
    TellurianState.REQUESTED: "requested",
    TellurianState.ACCEPTED: "accepted",
    TellurianState.DEPARTED: "departed",
}
_TELLURIAN_WORDS: Final = {
    TellurianState.NONE: "ingen klarering",
    TellurianState.REQUESTED: "begärd",
    TellurianState.ACCEPTED: "klar",
    TellurianState.REJECTED: "nekad",
    TellurianState.REVOKED: "återtagen",
    TellurianState.DEPARTED: "avgått",
    TellurianState.ARRIVED: "framme",
    TellurianState.CANCELED: "inställd",
    TellurianState.UNKNOWN: "okänt läge",
}
_DRIFT_WORDS: Final = {
    None: "ingen klarering",
    "requested": "begärd",
    "accepted": "klar",
    "departed": "avgått",
}
PROBLEMS: Final = {
    "unreachable": "Tellurian Dispatch svarar inte på adressen.",
    "timeout": "Tellurian Dispatch svarade inte i tid.",
    "redirect": "Tellurian Dispatch skickade vidare till en annan adress. Det följs inte.",
    "too_large": "Svaret från Tellurian Dispatch var för stort.",
    "bad_json": "Svaret från Tellurian Dispatch gick inte att läsa.",
    "bad_shape": "Svaret från Tellurian Dispatch hade oväntad form.",
    "address_not_local": "Namnet pekar inte på en lokal adress på träffens nät.",
}

Standing = Literal["matched", "ambiguous", "missing"]


def problem_text(code: str) -> str:
    """A TellurianError code in plain Swedish. Never Tellurian's own words."""
    if code in PROBLEMS:
        return PROBLEMS[code]
    status = code.removeprefix("http_")
    if status != code and status.isascii() and status.isdigit():
        return f"Tellurian Dispatch svarade med fel (HTTP {status})."
    return "Tellurian Dispatch gick inte att läsa."


def _open_in_drift(clearance: Clearance | None) -> str | None:
    if clearance is None:
        return None
    if clearance.status is ClearanceStatus.WAITING:
        return "requested"
    if clearance.status is ClearanceStatus.APPROVED:
        return "departed" if clearance.departed else "accepted"
    return None


def _match_places(
    places: Sequence[NowPlace], dispatchers: Iterable[Dispatcher]
) -> tuple[dict[str, str], list[str]]:
    """Drift's code -> place for exact, unique matches, and the codes left without a dispatcher.

    A duplicate on either side never matches, and a difference in case is no match.
    """
    codes = Counter(place.code for place in places)
    signatures = Counter(dispatcher.signature for dispatcher in dispatchers)
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for place in places:
        if codes[place.code] == 1 and signatures[place.code] == 1:
            matched[place.code] = place.place
        elif place.code not in unmatched:
            unmatched.append(place.code)
    return matched, unmatched


def _contact(heard: datetime | None, at: datetime | None) -> TellurianContact:
    if heard is None:
        return TellurianContact.WAITING
    if at is not None and at - heard > CONTACT_TIMEOUT:
        return TellurianContact.LOST
    return TellurianContact.OK


def shadow(
    package: MeetPackage,
    now: Now,
    views: Sequence[DispatcherView],
    *,
    simulated: bool,
    heard: datetime | None,
    problem: str | None,
    at: datetime | None = None,
) -> TellurianShadow:
    """Tellurian's sections beside Drift's clearances. Pure: nothing is read or written.

    Drift's places match dispatchers on code = signature, a Tellurian section matches Drift's
    section on the station pair, and a train matches on its number when that is unambiguous
    on both sides. A difference is a section where Tellurian holds a clearance (requested,
    accepted, departed) that Drift has in another state or not at all, or the reverse, and a
    Drift clearance Tellurian has no section for. `problem` is a TellurianError code; `at`,
    when given, turns an answer older than 15 seconds into lost contact.
    """
    dispatchers = {view.dispatcher.id: view.dispatcher for view in views}.values()
    place_of, unmatched = _match_places(now.places, dispatchers)
    pairs = Counter(frozenset((s.place_a, s.place_b)) for s in package.sections)
    section_of = {
        frozenset((s.place_a, s.place_b)): s.id
        for s in package.sections
        if pairs[frozenset((s.place_a, s.place_b))] == 1
    }
    found = sorted(
        merged_sections(views),
        key=lambda s: (s.departure_time, s.from_code or "", s.to_code or "", s.train, s.id),
    )
    tellurian_trains: defaultdict[str, set[str]] = defaultdict(set)
    for section in found:
        number = parse_train_label(section.train)[2]
        if number is not None:
            tellurian_trains[number].add(section.train_id or section.train)
    drift_trains = Counter(
        _number(train.number) for train in package.trains if now.traffic_day in train.days
    )

    def standing(number: str | None) -> Standing:
        if number is None or drift_trains[number] == 0:
            return "missing"
        if drift_trains[number] > 1 or len(tellurian_trains[number]) > 1:
            return "ambiguous"
        return "matched"

    clearances: dict[tuple[str, str, str], Clearance] = {}
    for clearance in now.clearances:
        key = (_number(clearance.train_number), clearance.from_place, clearance.to_place)
        clearances.setdefault(key, clearance)
    seen: set[str] = set()

    def compare(section: Section) -> TellurianSection:
        number = parse_train_label(section.train)[2]
        from_place = place_of.get(section.from_code or "")
        to_place = place_of.get(section.to_code or "")
        drift_section: str | None = None
        clearance: Clearance | None = None
        differs = False
        note: str | None = None
        train = standing(number)
        if from_place is None or to_place is None:
            # Not compared, as in the old Server: Drift does not know the place.
            note = "Driftplatsen finns inte i Drift."
        elif train == "ambiguous":
            # Never guessed: not compared either way.
            drift_section = section_of.get(frozenset((from_place, to_place)))
            note = "Tåget går inte att skilja från ett annat med samma nummer."
        else:
            drift_section = section_of.get(frozenset((from_place, to_place)))
            if train == "matched":
                clearance = clearances.get((number or "", from_place, to_place))
            if clearance is not None:
                seen.add(clearance.clearance_id)
            drift = _open_in_drift(clearance)
            differs = _OPEN.get(section.state) != drift
            drift_word = _DRIFT_WORDS[drift]
            if drift_section is None:
                drift_word = "sträckan finns inte"
            elif train == "missing":
                drift_word = "tåget finns inte"
            if differs:
                note = f"Tellurian: {_TELLURIAN_WORDS[section.state]}, Drift: {drift_word}."
        return TellurianSection(
            from_code=section.from_code,
            to_code=section.to_code,
            section=drift_section,
            train=section.train,
            train_number=number,
            state=section.state,
            drift=clearance.status if clearance is not None else None,
            differs=differs,
            note=note,
        )

    rows = [compare(section) for section in found]
    lacking = sum(
        1
        for clearance in now.clearances
        if clearance.clearance_id not in seen
        and _open_in_drift(clearance) is not None
        and standing(_number(clearance.train_number)) != "ambiguous"
    )
    return TellurianShadow(
        contact=_contact(heard, at),
        simulated=simulated,
        heard=heard,
        problem=problem_text(problem) if problem else None,
        sections=rows,
        differences=sum(row.differs for row in rows) + lacking,
        # Before the first answer nothing is known about Tellurian's dispatchers.
        unmatched=unmatched if heard is not None else [],
    )


def change_text(section: TellurianSection) -> str:
    """What Tellurian shows for one train on one section, for Logg (IMPORT-34)."""
    where = f"{section.from_code or '?'}–{section.to_code or '?'}"
    text = f"{section.train_number or section.train} {where}: {_TELLURIAN_WORDS[section.state]}"
    if section.differs and section.note:
        text += f" · {section.note}"
    return text
