"""Provar inloggningen i TrainMeet ID från början till slut, som en webbläsare och Catalog gör.

    python -m id.prov_inloggning <ID-adress> <mejlfil> <klienthemlighet> <Catalogs adress>

Skapa konto med namn och e-post, koden ur mejlet, sedan Catalogs utbyte av koden mot en token
med verifierad e-post (KONTO-10, KONTO-27). Sedan en ny inloggning med samma e-post utan namn, och
en första inloggning utan namn, som frågar efter namnet efter koden. Mejlen läses ur en fil som en
låtsad mejlserver skriver; inget skickas på riktigt.

Körs av kontrollen "ID:s bild" och lokalt mot en Keycloak med realmen i id/realm.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

REALM = "trainmeet"
CLIENT = "catalog"


class ProvFel(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ProvFel(message)


def form_action(page: str) -> str:
    found = re.search(r'<form[^>]*action="([^"]+)"', page)
    check(found is not None, "Sidan har inget formulär.")
    assert found is not None
    return html.unescape(found.group(1))


def code_from(mails: Path, address: str, seen: int) -> tuple[str, int]:
    """The newest code mailed to the address, after the mails already seen."""
    for _ in range(50):
        text = mails.read_text(encoding="utf-8") if mails.exists() else ""
        parts = [p for p in text.split("----\n") if p.strip()]
        for part in reversed(parts[seen:]):
            if address in part.splitlines()[0]:
                found = re.search(r"\b(\d{3}) (\d{3})\b", part)
                check(found is not None, "Mejlet har ingen kod.")
                assert found is not None
                check("TrainMeet" in part, "Mejlet säger inte TrainMeet.")
                return found.group(1) + found.group(2), len(parts)
        time.sleep(0.2)
    raise ProvFel(f"Inget mejl till {address}.")


def mail_count(mails: Path) -> int:
    text = mails.read_text(encoding="utf-8") if mails.exists() else ""
    return len([p for p in text.split("----\n") if p.strip()])


class Login:
    def __init__(self, base: str, catalog: str) -> None:
        self.base = base.rstrip("/")
        self.redirect = catalog.rstrip("/") + "/api/catalog/1/id/callback"
        self.verifier = secrets.token_urlsafe(48)
        self.state = secrets.token_urlsafe(16)
        self.client = httpx.Client(follow_redirects=False, timeout=20)

    def start(self) -> str:
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urlencode(
            {
                "client_id": CLIENT,
                "redirect_uri": self.redirect,
                "response_type": "code",
                "scope": "openid email profile",
                "state": self.state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "ui_locales": "sv",
            }
        )
        page = self.keep(
            self.client.get(f"{self.base}/realms/{REALM}/protocol/openid-connect/auth?{query}")
        )
        check(page.status_code == 200, f"Inloggningssidan svarade {page.status_code}.")
        check("Skicka en kod" in page.text, "Inloggningssidan saknar Skicka en kod.")
        return page.text

    def keep(self, answer: httpx.Response) -> httpx.Response:
        # Keycloak marks its cookies Secure. A browser sends them to http://localhost anyway; this
        # client is told to, so the same test runs locally over http and over https.
        for name, value in answer.cookies.items():
            self.client.cookies.set(name, value)
        return answer

    def post(self, page: str, data: dict[str, str]) -> httpx.Response:
        return self.keep(self.client.post(form_action(page), data=data))

    def finish(self, answer: httpx.Response, secret: str) -> dict[str, object]:
        check(answer.status_code == 302, f"Inloggningen slutade med {answer.status_code}.")
        target = urlparse(answer.headers["location"])
        query = parse_qs(target.query)
        check(
            target.path.endswith("/api/catalog/1/id/callback"), "Fel adress tillbaka till Catalog."
        )
        check(query.get("state") == [self.state], "Fel state tillbaka.")
        tokens = self.client.post(
            f"{self.base}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "redirect_uri": self.redirect,
                "client_id": CLIENT,
                "client_secret": secret,
                "code_verifier": self.verifier,
            },
        )
        check(tokens.status_code == 200, f"Token svarade {tokens.status_code}: {tokens.text[:200]}")
        payload = tokens.json()["id_token"].split(".")[1]
        claims: dict[str, object] = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return claims


def run(base: str, mails: Path, secret: str, catalog: str) -> None:
    address = f"prov-{secrets.token_hex(4)}@example.com"

    # Skapa konto: namn och e-post, koden, och tillbaka till Catalog.
    login = Login(base, catalog)
    page = login.start()
    create = login.post(page, {"create": "1"}).text
    check("Namn" in create, "Skapa konto frågar inte efter namnet.")
    seen = mail_count(mails)
    sent = login.post(
        create, {"creating": "1", "name": "Provare Ett", "email": address, "send": "1"}
    )
    check("Skriv koden" in sent.text, "Kodsidan kom inte.")
    code, seen = code_from(mails, address, seen)
    wrong = login.post(sent.text, {"code": "000000" if code != "000000" else "111111"})
    check("Koden stämmer inte" in wrong.text, "Fel kod sa inte ifrån.")
    claims = login.finish(login.post(wrong.text, {"code": code[:3] + " " + code[3:]}), secret)
    check(claims.get("email") == address, "Fel e-post i token.")
    check(claims.get("email_verified") is True, "E-posten är inte verifierad i token.")
    check(claims.get("name") == "Provare Ett", f"Fel namn i token: {claims.get('name')}")
    first = claims.get("sub")
    print(f"Skapa konto: ok ({address})")

    # Logga in igen med samma e-post: samma konto.
    again = Login(base, catalog)
    page = again.start()
    seen = mail_count(mails)
    sent = again.post(page, {"email": address.upper(), "send": "1"})
    code, seen = code_from(mails, address, seen)
    claims = again.finish(again.post(sent.text, {"code": code}), secret)
    check(claims.get("sub") == first, "Samma e-post gav ett annat konto.")
    print("Logga in igen: ok, samma konto")

    # Första gången utan namn: namnet efter koden.
    other = f"prov-{secrets.token_hex(4)}@example.com"
    fresh = Login(base, catalog)
    page = fresh.start()
    seen = mail_count(mails)
    sent = fresh.post(page, {"email": other, "send": "1"})
    code, seen = code_from(mails, other, seen)
    named = fresh.post(sent.text, {"code": code})
    check("Vad heter du?" in named.text, "Namnet efterfrågades inte.")
    claims = fresh.finish(fresh.post(named.text, {"name": "Provare Två"}), secret)
    check(claims.get("name") == "Provare Två", "Namnet kom inte med.")
    print("Första inloggningen utan namn: ok")

    # En felaktig adress säger ifrån.
    bad = Login(base, catalog)
    page = bad.start()
    check(
        "Skriv en e-postadress" in bad.post(page, {"email": "kim", "send": "1"}).text,
        "Fel adress sa inte ifrån.",
    )
    print("Fel adress: ok")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    try:
        run(argv[1], Path(argv[2]), argv[3], argv[4])
    except ProvFel as fel:
        print(f"FEL: {fel}", file=sys.stderr)
        return 1
    print("Inloggningen med kod till e-posten fungerar.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
