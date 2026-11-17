"""Deltagarna (DELT-01–DELT-20): the page everyone sees without logging in, and träffens Wi-Fi
that it and the screens share (H45, SYNK-26).

The clock, the line and the next happenings come from Drift's open API, as for the screens
(H72): /api/drift/1/now and /api/drift/1/package hold no names of people, codes or phone
numbers (B13). What this module adds is what depends on where the one who looks is (S8): over
the internet, without logging in, only the traffic; on the meet's network, or logged in, also
träffens Wi-Fi, so that a box or a phone can join it.

On the meet's network means: the request comes straight from a private, link-local or loopback
address, with no proxy in between. The Pi on the meet's network is reached that way. The cloud
hub is reached through Caddy, which says so in X-Forwarded-For, so every visitor there counts as
over the internet. This is the old Server's test for public clients (http_server.py,
_client_address_is_private and _public_clients_allowed).
"""

from __future__ import annotations

import io
import ipaddress
from collections.abc import Callable
from typing import Any, Final

import segno
from fastapi import APIRouter, HTTPException, Query, Request, Response

from contracts import hub
from hub.hubben import Authorization, SessionCookie, require_admin, session_of
from hub.local import LocalLogin, MeetWifi
from hub.network_api import _same_site

PROXY_HEADERS: Final = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip")
# The addresses a phone or a box on the meet's own network has.
NEAR: Final = tuple(
    ipaddress.ip_network(net)
    for net in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "127.0.0.0/8",
        "fc00::/7",
        "fe80::/10",
        "::1/128",
    )
)
QR_STYLE: Final = {"scale": 6, "border": 2, "dark": "#0e1114", "light": "#ffffff"}


def on_meet_network(request: Request) -> bool:
    """Straight from the meet's own network: a private (RFC 1918 or IPv6 unique local),
    link-local or loopback address, and nothing that says a proxy passed it on."""
    if any(name in request.headers for name in PROXY_HEADERS):
        return False
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in NEAR)


def wifi_qr(wifi: MeetWifi) -> str:
    """The Wi-Fi QR a phone camera joins with: WIFI:T:WPA;S:<name>;P:<password>;; as the old
    Server wrote it, with \\ ; , " and : escaped."""

    def escape(text: str) -> str:
        for char in '\\;,":':
            text = text.replace(char, "\\" + char)
        return text

    if wifi.open:
        return f"WIFI:T:nopass;S:{escape(wifi.name)};;"
    if wifi.password:
        return f"WIFI:T:WPA;S:{escape(wifi.name)};P:{escape(wifi.password)};;"
    return f"WIFI:T:WPA;S:{escape(wifi.name)};;"


def svg(text: str) -> Response:
    picture = io.BytesIO()
    segno.make(text, error="m").save(picture, kind="svg", **QR_STYLE)
    return Response(
        picture.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"}
    )


def router(login: LocalLogin, link: Callable[[], str | None]) -> APIRouter:
    """`link` is the meet's address over the internet: the cloud hub this Pi is linked to."""
    routes = APIRouter()

    def admin_view() -> dict[str, Any]:
        found = login.meet_wifi()
        if found is None:
            return hub.MeetWifi().model_dump(mode="json")
        return hub.MeetWifi(
            name=found.name, open=found.open, has_password=bool(found.password)
        ).model_dump(mode="json")

    @routes.get("/api/hub/meet-wifi")
    def meet_wifi(
        response: Response, session: SessionCookie = None, authorization: Authorization = None
    ) -> dict[str, Any]:
        """Träffens Wi-Fi under the gear: the name and whether a password is set, never the
        password itself."""
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        return admin_view()

    @routes.post("/api/hub/meet-wifi")
    def set_meet_wifi(
        change: hub.MeetWifiChange,
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """No name: träffens Wi-Fi is not shared. Without a new password the one set before
        stays. A password is 8–63 characters, as WPA has it."""
        response.headers["Cache-Control"] = "no-store"
        require_admin(login, session, authorization)
        if not _same_site(request):
            raise HTTPException(403, "Ändra träffens Wi-Fi från hubbens egen sida.")
        name = change.name.strip()
        if not name:
            login.set_meet_wifi(None)
            return admin_view()
        before = login.meet_wifi()
        password: str | None = None
        if not change.open:
            password = change.password if change.password else None
            if password is None and before is not None and before.name and not before.open:
                password = before.password
            if password is None:
                raise HTTPException(
                    422, "Skriv lösenordet till träffens Wi-Fi, eller välj öppet nät."
                )
            if not 8 <= len(password) <= 63:
                raise HTTPException(422, "Ett lösenord till Wi-Fi har 8–63 tecken.")
        login.set_meet_wifi(MeetWifi(name=name, open=change.open, password=password))
        return admin_view()

    def full(request: Request, session: str | None, authorization: str | None) -> bool:
        return on_meet_network(request) or login.valid(session_of(session, authorization))

    @routes.get("/api/deltagare")
    def participant(
        request: Request,
        response: Response,
        session: SessionCookie = None,
        authorization: Authorization = None,
    ) -> dict[str, Any]:
        """What the participant page may show the one who looks (S8)."""
        response.headers["Cache-Control"] = "no-store"
        logged_in = login.valid(session_of(session, authorization))
        shown = logged_in or on_meet_network(request)
        found = login.meet_wifi() if shown else None
        wifi = (
            hub.SharedWifi(name=found.name, open=found.open, password=found.password)
            if found is not None and found.name
            else None
        )
        return hub.Participant(full=shown, logged_in=logged_in, wifi=wifi, link=link()).model_dump(
            mode="json"
        )

    @routes.get("/api/deltagare/wifi.svg")
    def wifi_picture(
        request: Request, session: SessionCookie = None, authorization: Authorization = None
    ) -> Response:
        """QR-koden 1 · Wi-Fi: only on the meet's network or logged in (S8)."""
        if not full(request, session, authorization):
            raise HTTPException(403, "Träffens Wi-Fi visas på träffens nät eller inloggad.")
        found = login.meet_wifi()
        if found is None or not found.name:
            raise HTTPException(404, "Träffens Wi-Fi är inte inlagt.")
        return svg(wifi_qr(found))

    @routes.get("/api/deltagare/traffen.svg")
    def meet_picture(address: str = Query(min_length=8, max_length=300)) -> Response:
        """QR-koden 2 · Träffen: the link to the meet. Only an http(s) address is drawn."""
        if not address.startswith(("http://", "https://")):
            raise HTTPException(422, "Bara en webbadress blir en QR-kod.")
        return svg(address)

    return routes
