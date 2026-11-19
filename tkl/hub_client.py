"""TKL towards the hub: the station protocol (contracts/station.py), and finding the hub.

On the meet's network the hub announces itself with DNS-SD, as it does for the boxes:
`_tmbox._tcp` with its web port in the TXT record `http` (KLAR-13, old Server). Only a hub with
a started meet is shown (H36). Over the internet TKL is given the address and a code from the
dispatcher (S2). Outside the meet's network the same calls can go through the cloud's relay,
whose address the hub gives when TKL connects (SYNK-11).

The key goes in the Authorization header and nowhere else (H31). Nothing here logs it.
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from typing import Any, Final

import httpx

from contracts import station
from contracts.tkl import FoundHub

SERVICE: Final = "_tmbox._tcp.local."
TIMEOUT: Final = httpx.Timeout(8.0, connect=3.0)
STATION: Final = "/api/station/1"


class HubError(Exception):
    """The hub said no, with its reason."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Unreachable(Exception):
    """No answer from the hub, nor through the relay."""


def _detail(response: httpx.Response) -> str:
    try:
        found = response.json().get("detail")
    except ValueError:
        found = None
    return found if isinstance(found, str) else f"Hubben svarade {response.status_code}."


class HubClient:
    """The station protocol at one hub, with the relay as the way round when the hub's own
    address cannot be reached."""

    def __init__(
        self, http: httpx.Client, address: str, relay: str | None = None, key: str | None = None
    ) -> None:
        self.http = http
        self.bases = [address.rstrip("/"), *([relay.rstrip("/")] if relay else [])]
        self.key = key

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        for base in self.bases:
            try:
                response = self.http.request(method, base + path, json=body, headers=headers)
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                raise HubError(response.status_code, _detail(response))
            return response.json()
        raise Unreachable()

    def connect(self, request: station.ConnectRequest) -> station.ConnectReply:
        answer = self._call("POST", STATION + "/connect", request.model_dump(mode="json"))
        return station.ConnectReply.model_validate(answer)

    def connection(self, client_id: str) -> station.ConnectReply:
        return station.ConnectReply.model_validate(
            self._call("GET", f"{STATION}/connect/{client_id}")
        )

    def snapshot(self, place: str) -> station.Snapshot:
        return station.Snapshot.model_validate(self._call("GET", f"{STATION}/places/{place}"))

    def command(self, command: station.Command) -> station.Reply:
        answer = self._call("POST", STATION + "/commands", command.model_dump(mode="json"))
        return station.Reply.model_validate(answer)

    def overview(self, places: list[str] | None = None) -> station.Overview:
        """Fjärrbildens data (#36): the places asked for; none gives every place the client
        runs, controls, is offered or is approved for, and their neighbours."""
        query = f"?places={','.join(places)}" if places else ""
        return station.Overview.model_validate(self._call("GET", f"{STATION}/overview{query}"))

    def exit(self, place: str, answer: station.ExitAnswer) -> station.Snapshot:
        given = self._call(
            "POST", f"{STATION}/places/{place}/exits", answer.model_dump(mode="json")
        )
        return station.Snapshot.model_validate(given)

    def describe(self, nearby: bool) -> FoundHub | None:
        """The hub's name and its meet; None if it cannot be reached."""
        try:
            info = self._call("GET", "/api/hub")
        except (HubError, Unreachable):
            return None
        try:
            meet = self._call("GET", "/api/drift/1/now").get("name")
        except (HubError, Unreachable):
            meet = None
        name = str(info.get("name") or "Hubben")
        return FoundHub(address=self.bases[0], name=name, meet=meet, nearby=nearby)


def browse(seconds: float = 1.5) -> list[str]:
    """The hubs on the meet's network, as http addresses, found with DNS-SD."""
    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    except ImportError:  # pragma: no cover - TKL's image always has it
        return []
    found: list[str] = []
    names: list[str] = []

    def changed(
        zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        if state_change == ServiceStateChange.Added:
            names.append(name)

    try:
        zeroconf = Zeroconf()
    except OSError:
        return []
    try:
        ServiceBrowser(zeroconf, SERVICE, handlers=[changed])
        time.sleep(seconds)
        for name in names:
            info = zeroconf.get_service_info(SERVICE, name, timeout=1000)
            if info is None:
                continue
            port = (info.properties or {}).get(b"http")
            for address in info.parsed_addresses():
                ip = ipaddress.ip_address(address)
                host = f"[{address}]" if ip.version == 6 else address
                web = int(port) if port and port.isdigit() else 80
                found.append(f"http://{host}" + ("" if web == 80 else f":{web}"))
                break
    finally:
        zeroconf.close()
    return list(dict.fromkeys(found))


def find_hubs(
    http: httpx.Client, browse: Callable[[], list[str]], over_internet: list[str]
) -> list[FoundHub]:
    """Hubs with a started meet on the meet's network, then those TKL may reach over the
    internet."""
    hubs = []
    for address in browse():
        found = HubClient(http, address).describe(nearby=True)
        if found is not None and found.meet:
            hubs.append(found)
    for address in over_internet:
        found = HubClient(http, address).describe(nearby=False)
        hubs.append(found or FoundHub(address=address, name=address, nearby=False))
    return hubs
