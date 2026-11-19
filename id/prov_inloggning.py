"""Provar inloggningen i TrainMeet ID från början till slut, som en webbläsare och Catalog gör.

    python -m id.prov_inloggning <ID> <mejlfil> <klienthemlighet> <Catalog> [--catalog]
        [--id-app=<ID:s webbapp>] [--hub=<Hubben>] [--tkl=<TKL>] [--tkl-moln=<TKL i molnet>]

Skapa konto med namn och e-post, koden ur mejlet, sedan Catalogs utbyte av koden mot en token
med verifierad e-post (KONTO-10, KONTO-27). Sedan en ny inloggning med samma e-post utan namn, och
en första inloggning utan namn, som frågar efter namnet efter koden. Mejlen läses ur en fil som en
låtsad mejlserver skriver; inget skickas på riktigt.

Passkey (KONTO-33) provas med en passkey i programmet, som en telefon: den läggs till när ID
frågar efter den första inloggningen, och sedan loggar man in med den utan kod.

Med --catalog körs Catalog på sin adress, och provet loggar in där som en webbläsare: genom ID med
en kod till e-posten och tillbaka in i Catalog med samma konto (KONTO-27), sedan in i Catalog utan
ny kod när man redan är inloggad i ID (KONTO-01), och ut ur både Catalog och ID.

Med --id-app körs ID:s API och webbapp på den adressen (#67): en klubb skapas, en medlem
bjuds in med mejl och svarar ja, och klubben får en träff där medlemmen blir trafikledare
(ID10). Med båda delas en vagnpark i ID och syns i Catalog (#49), och klubbens vagnpark provas:
administratören gör ägarens saker, medlemmen tittar (CAT-51, C39). Sist hämtas uppgifterna som en
fil och kontot tas bort i Catalog, Keycloak och ID (KONTO-31, CAT-193).

Med --hub körs Hubben på den adressen med klienten hub (#78), och provet loggar in där som en
webbläsare: genom ID med en kod till e-posten och tillbaka in i Hubben, som visar namnet men inte
adressen och inte gör personen till hubbens administratör, och sedan ut ur både Hubben och ID.

Med --tkl körs TKL på den adressen med den publika klienten tkl (TKL18), och sparar stationen i
Hubben (SYNK-30) efter inloggningen med en kod till e-posten.

Med --tkl-moln körs TKL i molnet på den adressen (#88, TKL5): TKL börjar med inloggningen, utan
första start och PIN. Provet loggar in med en kod till e-posten, skapar en station som sparas i
Hubbens Synk, ändrar den och sparar i molnet, och öppnar den sedan ur Dina stationer i en ny
webbläsare, inloggad i ID sedan förut.

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
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

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


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def cbor(value: object) -> bytes:
    """Just enough CBOR for a passkey: integers, byte and text strings, and maps."""

    def head(major: int, length: int) -> bytes:
        if length < 24:
            return bytes([major << 5 | length])
        if length < 256:
            return bytes([major << 5 | 24, length])
        return bytes([major << 5 | 25]) + length.to_bytes(2, "big")

    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    if isinstance(value, dict):
        items = b"".join(cbor(k) + cbor(v) for k, v in value.items())
        return head(5, len(value)) + items
    raise TypeError(type(value))


def script_value(page: str, name: str) -> str:
    """A value the page gives Keycloak's passkey script, such as challenge or rpId."""
    found = re.search(rf'\b{name}\s*:\s*"([^"]*)"', page)
    check(found is not None, f"Sidan saknar {name} för passkey.")
    assert found is not None
    return found.group(1)


class Passkey:
    """A passkey like the one in a phone: an ES256 key that is found without an address."""

    UP, UV, AT = 0x01, 0x04, 0x40

    def __init__(self, origin: str) -> None:
        self.origin = origin.rstrip("/")
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(16)
        self.user = b""
        self.count = 0

    def client_data(self, kind: str, challenge: str) -> bytes:
        data = {"type": kind, "challenge": b64url(unb64url(challenge)), "origin": self.origin}
        return json.dumps(data, separators=(",", ":")).encode()

    def register(self, page: str) -> dict[str, str]:
        """The answer to ID's page for adding a passkey."""
        rp = script_value(page, "rpId")
        self.user = unb64url(script_value(page, "userid"))
        numbers = self.key.public_key().public_numbers()
        cose = {
            1: 2,
            3: -7,
            -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }
        credential = bytes(16) + len(self.id).to_bytes(2, "big") + self.id + cbor(cose)
        flags = bytes([self.UP | self.UV | self.AT])
        auth = hashlib.sha256(rp.encode()).digest() + flags + self.count.to_bytes(4, "big")
        attestation = cbor({"fmt": "none", "attStmt": {}, "authData": auth + credential})
        return {
            "clientDataJSON": b64url(
                self.client_data("webauthn.create", script_value(page, "challenge"))
            ),
            "attestationObject": b64url(attestation),
            "publicKeyCredentialId": b64url(self.id),
            "authenticatorLabel": "Prov",
            "transports": "internal",
            "authenticatorAttachment": "platform",
        }

    def sign_in(self, page: str) -> dict[str, str]:
        """The answer to Logga in med passkey on ID's email page."""
        self.count += 1
        rp = script_value(page, "rpId")
        client = self.client_data("webauthn.get", script_value(page, "challenge"))
        auth = hashlib.sha256(rp.encode()).digest() + bytes([self.UP | self.UV])
        auth += self.count.to_bytes(4, "big")
        signed = auth + hashlib.sha256(client).digest()
        return {
            "clientDataJSON": b64url(client),
            "authenticatorData": b64url(auth),
            "signature": b64url(self.key.sign(signed, ec.ECDSA(hashes.SHA256()))),
            "credentialId": b64url(self.id),
            "userHandle": b64url(self.user),
            "error": "",
        }


OFFER = "Logga in snabbare nästa gång?"


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
        return self.within_id(self.keep(self.client.post(form_action(page), data=data)))

    def within_id(self, answer: httpx.Response) -> httpx.Response:
        """Follows ID's own redirects, such as to the page for adding a passkey."""
        for _ in range(5):
            target = answer.headers.get("location", "")
            if answer.status_code not in (302, 303) or not target.startswith(self.base):
                break
            answer = self.keep(self.client.get(target))
        return answer

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
    offer = login.post(wrong.text, {"code": code[:3] + " " + code[3:]})
    check(OFFER in offer.text, "ID frågade inte om en passkey efter första inloggningen.")
    adding = login.post(offer.text, {"passkey": "yes"})
    check("Lägg till en passkey" in adding.text, "Sidan för att lägga till passkey kom inte.")
    passkey = Passkey(base)
    claims = login.finish(login.post(adding.text, passkey.register(adding.text)), secret)
    check(claims.get("email") == address, "Fel e-post i token.")
    check(claims.get("email_verified") is True, "E-posten är inte verifierad i token.")
    check(claims.get("name") == "Provare Ett", f"Fel namn i token: {claims.get('name')}")
    first = claims.get("sub")
    print(f"Skapa konto och lägg till passkey: ok ({address})")

    # Logga in igen med samma e-post: samma konto.
    again = Login(base, catalog)
    page = again.start()
    seen = mail_count(mails)
    sent = again.post(page, {"email": address.upper(), "send": "1"})
    code, seen = code_from(mails, address, seen)
    claims = again.finish(again.post(sent.text, {"code": code}), secret)
    check(claims.get("sub") == first, "Samma e-post gav ett annat konto.")
    print("Logga in igen med kod: ok, samma konto, ingen fråga om passkey")

    # Logga in med passkey, utan e-post och utan kod (KONTO-33).
    seen = mail_count(mails)
    quick = Login(base, catalog)
    page = quick.start()
    check("Logga in med passkey" in page, "Inloggningen erbjuder inte passkey.")
    claims = quick.finish(quick.post(page, passkey.sign_in(page)), secret)
    check(claims.get("sub") == first, "Passkey gav ett annat konto.")
    check(mail_count(mails) == seen, "En kod skickades fast man loggade in med passkey.")
    print("Logga in med passkey: ok, samma konto")

    # En passkey som ID inte känner till släpper inte in någon.
    stranger = Passkey(base)
    stranger.user = passkey.user
    odd = Login(base, catalog)
    page = odd.start()
    refused = odd.post(page, stranger.sign_in(page))
    check(
        refused.status_code == 200
        and 'role="alert"' in refused.text
        and "Skicka en kod" in refused.text,
        "En okänd passkey släpptes in eller sa inte ifrån.",
    )
    print("Okänd passkey: ok, inte inne")

    # Första gången utan namn: namnet efter koden.
    other = f"prov-{secrets.token_hex(4)}@example.com"
    fresh = Login(base, catalog)
    page = fresh.start()
    seen = mail_count(mails)
    sent = fresh.post(page, {"email": other, "send": "1"})
    code, seen = code_from(mails, other, seen)
    named = fresh.post(sent.text, {"code": code})
    check("Vad heter du?" in named.text, "Namnet efterfrågades inte.")
    offer = fresh.post(named.text, {"name": "Provare Två"})
    check(OFFER in offer.text, "ID frågade inte om en passkey.")
    claims = fresh.finish(fresh.post(offer.text, {"passkey": "no"}), secret)
    check(claims.get("name") == "Provare Två", "Namnet kom inte med.")
    print("Första inloggningen utan namn, och Inte nu: ok")

    # Inte nu: ingen fråga nästa gång.
    later = Login(base, catalog)
    page = later.start()
    seen = mail_count(mails)
    sent = later.post(page, {"email": other, "send": "1"})
    code, seen = code_from(mails, other, seen)
    later.finish(later.post(sent.text, {"code": code}), secret)
    print("Ingen ny fråga efter Inte nu: ok")

    # En felaktig adress säger ifrån.
    bad = Login(base, catalog)
    page = bad.start()
    check(
        "Skriv en e-postadress" in bad.post(page, {"email": "kim", "send": "1"}).text,
        "Fel adress sa inte ifrån.",
    )
    print("Fel adress: ok")


class Browser:
    """One browser: ID's cookies (Secure, see Login.keep) and the app's in their own jars."""

    def __init__(self, base: str, catalog: str, session: str = "/api/catalog/1/session") -> None:
        self.id = Login(base, catalog)
        self.session_path = session
        self.app = httpx.Client(base_url=catalog.rstrip("/"), follow_redirects=False, timeout=20)

    def open(self, address: str) -> httpx.Response:
        """Opens an address and follows the redirects between Catalog and ID."""
        for _ in range(10):
            if address.startswith(str(self.app.base_url)) or address.startswith("/"):
                answer = self.app.get(address.removeprefix(str(self.app.base_url)))
            else:
                answer = self.id.keep(self.id.client.get(address))
            if answer.status_code not in (301, 302, 303, 307):
                return answer
            address = answer.headers["location"]
        raise ProvFel("För många omdirigeringar.")

    def follow(self, answer: httpx.Response) -> httpx.Response:
        if answer.status_code in (302, 303):
            return self.open(answer.headers["location"])
        return answer

    def session(self) -> dict[str, object]:
        data: dict[str, object] = self.app.get(self.session_path).json()
        return data


def run_catalog(base: str, mails: Path, catalog: str) -> None:
    address = f"prov-{secrets.token_hex(4)}@example.com"
    browser = Browser(base, catalog)
    check(browser.session()["login"] == "id", "Catalog loggar inte in med ID.")

    # Från Catalogs inloggning, genom ID med en kod till e-posten, och tillbaka in i Catalog.
    page = browser.open("/api/catalog/1/id/login?next=%2Fplatser&lang=sv")
    check(page.status_code == 200 and "Skicka en kod" in page.text, "ID:s sida kom inte.")
    create = browser.id.post(page.text, {"create": "1"}).text
    seen = mail_count(mails)
    sent = browser.id.post(
        create, {"creating": "1", "name": "Provare Tre", "email": address, "send": "1"}
    )
    code, seen = code_from(mails, address, seen)
    offer = browser.id.post(sent.text, {"code": code})
    check(OFFER in offer.text, "ID frågade inte om en passkey.")
    back = browser.id.post(offer.text, {"passkey": "no"})
    check(back.status_code == 302, f"ID skickade inte tillbaka: {back.status_code}.")
    check(back.headers["location"].startswith(catalog.rstrip("/")), "Inte tillbaka till Catalog.")
    landed = browser.app.get(back.headers["location"].removeprefix(catalog.rstrip("/")))
    check(
        landed.headers.get("location") == "/platser", "Catalog gick inte till sidan man kom från."
    )
    account = browser.session()["account"]
    check(isinstance(account, dict) and account.get("name") == "Provare Tre", "Inte inloggad.")
    assert isinstance(account, dict)
    check(browser.app.get("/api/catalog/1/vehicles").status_code == 200, "Ingen vagnpark.")
    print("In i Catalog med en kod till e-posten: ok")

    # Ut ur Catalog, och in igen utan kod: inloggad i ID sedan förut (KONTO-01).
    out = browser.app.delete("/api/catalog/1/session").json()
    check(browser.session()["account"] is None, "Fortfarande inloggad i Catalog.")
    seen = mail_count(mails)
    again = browser.open("/api/catalog/1/id/login?next=%2Ffordon")
    check(again.status_code == 200, f"Tillbaka in svarade {again.status_code}.")
    same = browser.session()["account"]
    check(isinstance(same, dict) and same.get("id") == account["id"], "Inte samma konto.")
    check(mail_count(mails) == seen, "En ny kod skickades fast man redan var inloggad i ID.")
    print("In igen utan ny kod, samma konto: ok")

    # Ut ur både Catalog och ID.
    out = browser.app.delete("/api/catalog/1/session").json()
    logout = out.get("logout_url")
    check(isinstance(logout, str), "Utloggningen sa inte var ID loggar ut.")
    assert isinstance(logout, str)
    home = browser.open(logout)
    check(home.status_code == 200, f"Utloggningen i ID svarade {home.status_code}.")
    check(browser.session()["account"] is None, "Fortfarande inloggad i Catalog.")
    page = browser.open("/api/catalog/1/id/login?next=%2Ffordon")
    check("Skicka en kod" in page.text, "Fortfarande inloggad i ID efter utloggningen.")
    print("Ut ur Catalog och ID: ok")


def run_hub(base: str, mails: Path, hub: str) -> None:
    """Logga in med TrainMeet ID i Hubben (#78), as a browser: through ID with a code to the
    e-mail and back into the hub, which knows the name but not the address; then out of both."""
    address = f"prov-{secrets.token_hex(4)}@example.com"
    browser = Browser(base, hub, session="/api/hub")
    check(browser.session()["id_login"] is True, "Hubben har ingen inloggning med ID.")
    page = browser.open("/api/hub/id/login?next=%2Fdrift&lang=sv")
    check(page.status_code == 200 and "Skicka en kod" in page.text, "ID:s sida kom inte.")
    create = browser.id.post(page.text, {"create": "1"}).text
    seen = mail_count(mails)
    sent = browser.id.post(
        create, {"creating": "1", "name": "Provare Fyra", "email": address, "send": "1"}
    )
    code, _ = code_from(mails, address, seen)
    offer = browser.id.post(sent.text, {"code": code})
    check(OFFER in offer.text, "ID frågade inte om en passkey.")
    back = browser.id.post(offer.text, {"passkey": "no"})
    check(back.status_code == 302, f"ID skickade inte tillbaka: {back.status_code}.")
    check(back.headers["location"].startswith(hub.rstrip("/")), "Inte tillbaka till Hubben.")
    landed = browser.app.get(back.headers["location"].removeprefix(hub.rstrip("/")))
    check(landed.headers.get("location") == "/drift", "Hubben gick inte till sidan man kom från.")
    seen_hub = browser.session()
    check(seen_hub["logged_in"] is True, "Inte inloggad i Hubben.")
    check(seen_hub["person"] == "Provare Fyra", "Hubben visar inte namnet.")
    check(seen_hub["admin"] is False, "Inloggad med ID blev hubbens administratör.")
    check(address not in json.dumps(seen_hub), "Hubben visar adressen.")
    print("In i Hubben med en kod till e-posten: ok")

    out = browser.app.post("/api/hub/logout").json()
    logout = out.get("logout_url")
    check(isinstance(logout, str), "Utloggningen sa inte var ID loggar ut.")
    assert isinstance(logout, str)
    browser.open(logout)
    check(browser.session()["logged_in"] is False, "Fortfarande inloggad i Hubben.")
    page = browser.open("/api/hub/id/login?next=%2F")
    check("Skicka en kod" in page.text, "Fortfarande inloggad i ID efter utloggningen.")
    print("Ut ur Hubben och ID: ok")


def run_hub_roles(base: str, mails: Path, hub: str, id_app: str) -> None:
    """The hub's meet made from a meet in ID (ID10, PLAN-19, #78): the club's admin makes a meet
    in ID's web app, logs in to the hub with the same ID session, and makes the hub's meet from
    it. The hub asks ID's API with a token of its own, as the client hub."""
    kim = Browser(base, id_app, "/api/id/1/session")
    address = f"prov-{secrets.token_hex(4)}@example.com"
    log_in_to_app(kim, mails, address, "Provare Arrangör", "/api/id/1/login?next=%2Fklubbar")
    club = kim.app.post("/api/id/1/clubs", json={"name": "Hubbklubben"}).json()["id"]
    autumn = {"name": "Hubbträffen", "starts_on": "2026-11-20", "ends_on": "2026-11-22"}
    made = kim.app.post(f"/api/id/1/clubs/{club}/meets", json=autumn)
    check(made.status_code == 201, f"Träffen i ID svarade {made.status_code}.")
    id_meet = made.json()["id"]
    # Får publicera and Läsare (PLAN-19, PLAN-24, H16): ID's database takes both roles.
    kim_id = kim.app.get("/api/id/1/session").json()["account"]["id"]
    for role in ("publisher", "reader"):
        given = kim.app.post(
            f"/api/id/1/meets/{id_meet}/grants", json={"person": kim_id, "role": role}
        )
        check(given.status_code == 200, f"Rollen {role} i ID svarade {given.status_code}.")
    held = {
        g["role"]
        for g in kim.app.get(f"/api/id/1/meets/{id_meet}").json()["grants"]
        if g["person"]["id"] == kim_id
    }
    check(held == {"organizer", "publisher", "reader"}, f"Rollerna i ID: {sorted(held)}")

    # In i Hubben med samma inloggning i ID: ingen ny kod.
    in_hub = Browser(base, hub, "/api/hub")
    in_hub.id = kim.id
    seen = mail_count(mails)
    in_hub.open("/api/hub/id/login?next=%2Fplanering")
    check(in_hub.session()["person"] == "Provare Arrangör", "Inte inloggad i Hubben.")
    check(mail_count(mails) == seen, "En ny kod skickades fast man redan var inloggad i ID.")
    choices = in_hub.app.get("/api/planering/1/id-meets")
    check(choices.status_code == 200, f"Hubben fick inget svar från ID: {choices.status_code}.")
    check(
        [(c["name"], c["hub_meet"]) for c in choices.json()] == [("Hubbträffen", None)],
        f"Hubben ser inte träffen i ID: {choices.json()}",
    )
    created = in_hub.app.post(
        "/api/planering/1/meets", json={"name": "Hubbträffen", "id_meet": id_meet}
    )
    check(created.status_code == 201, f"Träffen i hubben svarade {created.status_code}.")
    check(created.json()["meet"]["id_meet"] == id_meet, "Hubbens träff är inte kopplad till ID.")
    listed = in_hub.app.get("/api/planering/1/meets").json()
    check(
        [(m["meet"]["name"], m["may_plan"], m["may_publish"], m["may_withdraw"]) for m in listed]
        == [("Hubbträffen", True, True, True)],
        f"Hubben säger inte att klubbens administratör planerar och publicerar: {listed}",
    )
    print("Hubbens träff ur träffen i ID, och arrangören planerar den: ok")
    print("Får publicera och Läsare i ID, och rätten att publicera i hubben: ok")


def run_tokens(base: str, mails: Path, secret: str, id_app: str) -> None:
    """TrainMeet tokens i ID (#79, TOKEN-08): the person sees the month's free quota, and an app
    reserves, draws and asks again with the same key, with its own token from Keycloak."""
    person = Browser(base, id_app, "/api/id/1/session")
    address = f"prov-{secrets.token_hex(4)}@example.com"
    log_in_to_app(person, mails, address, "Provare Sex", "/api/id/1/login?next=%2Ftokens")
    who = person.app.get("/api/id/1/session").json()["account"]["id"]
    seen = person.app.get("/api/id/1/tokens").json()
    check(
        [(b["title"], b["available"]) for b in seen] == [("Provare Sex", 100)],
        f"Saldot i ID: {seen}",
    )
    token = httpx.post(
        f"{base.rstrip('/')}/realms/trainmeet/protocol/openid-connect/token",
        data={"grant_type": "client_credentials"},
        auth=("catalog", secret),
        timeout=20,
    )
    check(token.status_code == 200, f"Appens token från ID svarade {token.status_code}.")
    as_app = httpx.Client(
        base_url=id_app.rstrip("/") + "/api/id/1/apps",
        headers={"Authorization": "Bearer " + token.json()["access_token"]},
        timeout=20,
    )
    asked = {
        "person": who,
        "owner": {"kind": "person", "id": who},
        "amount": 24,
        "key": f"prov-{secrets.token_hex(4)}",
        "what": "2 bilder i provet",
    }
    held = as_app.post("/tokens/reservations", json=asked)
    check(held.status_code == 201, f"Reservera svarade {held.status_code}: {held.text}")
    reservation = held.json()["id"]
    again = as_app.post("/tokens/reservations", json=asked)
    check(again.json().get("id") == reservation, f"Samma nyckel igen gav {again.text}")
    drawn = as_app.post(f"/tokens/reservations/{reservation}/draw", json={"amount": 12})
    check(drawn.status_code == 200, f"Dra svarade {drawn.status_code}: {drawn.text}")
    balance = as_app.get("/tokens", params={"person": who, "owner": f"person:{who}"}).json()
    check(balance.get("available") == 88, f"Saldot efter dragningen: {balance}")
    back = as_app.post(f"/tokens/reservations/{reservation}/return")
    check(back.status_code == 409, f"En dragen reservation lämnades tillbaka: {back.status_code}")
    print("Tokens i ID: saldot, reservera, dra och samma nyckel igen: ok")
    # Mätaren (TOKEN-28) is off without its key in the vault, and says so; nothing is drawn.
    page = {**asked, "amount": 12, "key": f"prov-{secrets.token_hex(4)}"}
    held = as_app.post("/tokens/reservations", json=page).json()["id"]
    picture = base64.b64encode(b"\x89PNG").decode()
    off = as_app.post(
        "/meter",
        json={
            "reservation": held,
            "prompt": "Skriv av.",
            "images": [{"media_type": "image/png", "data": picture}],
        },
    )
    check(off.status_code == 503, f"Mätaren utan nyckel svarade {off.status_code}: {off.text}")
    check(as_app.post(f"/tokens/reservations/{held}/return").status_code == 200, "Tillbaka.")
    print("Mätaren utan nyckel säger att TrainMeets AI inte är inkopplad: ok")


def run_tkl(base: str, mails: Path, tkl: str) -> None:
    """TKL med TrainMeet ID (TKL18, SYNK-30, #78): TKL logs in as the public client tkl with PKCE,
    and saves the station package in the hub, which takes the owner from TKL's token from ID."""
    browser = Browser(base, tkl, session="/api/tkl/1/state")
    station = {"name": "Provstation", "station_id": "prov", "pin": "4711"}
    check(browser.app.post("/api/tkl/1/setup", json=station).status_code == 201, "Ingen TKL.")
    check(browser.app.post("/api/tkl/1/studio/version").status_code == 200, "Ingen utsida.")
    page = browser.open("/api/tkl/1/id/login")
    check(page.status_code == 200 and "Skicka en kod" in page.text, "ID:s sida kom inte.")
    address = f"prov-{secrets.token_hex(4)}@example.com"
    create = browser.id.post(page.text, {"create": "1"}).text
    seen = mail_count(mails)
    sent = browser.id.post(
        create, {"creating": "1", "name": "Provare Fem", "email": address, "send": "1"}
    )
    code, _ = code_from(mails, address, seen)
    offer = browser.id.post(sent.text, {"code": code})
    back = browser.id.post(offer.text, {"passkey": "no"})
    check(back.status_code == 302, f"ID skickade inte tillbaka: {back.status_code}.")
    check(back.headers["location"].startswith(tkl.rstrip("/")), "Inte tillbaka till TKL.")
    landed = browser.app.get(back.headers["location"].removeprefix(tkl.rstrip("/")))
    check(landed.headers.get("location") == "/", "TKL loggade inte in med ID.")
    state = browser.app.get("/api/tkl/1/id").json()
    check(state.get("person") == "Provare Fem", f"TKL vet inte vem som loggat in: {state}")
    check(address not in json.dumps(state), "TKL visar adressen.")
    saved = browser.app.post("/api/tkl/1/id/save", json={})
    check(saved.status_code == 200, f"Spara i molnet svarade {saved.status_code}: {saved.text}")
    check(saved.json().get("version") == 1, f"Stationen sparades inte i hubben: {saved.json()}")
    again = browser.app.post("/api/tkl/1/id/save", json={})
    check(again.json().get("version") == 2, "En andra version sparades inte ovanpå den första.")
    print("TKL med ID: inloggad som publik klient, stationen sparad i hubben: ok")


def run_tkl_moln(base: str, mails: Path, tkl: str) -> None:
    """TKL i molnet (#88, TKL5, TKLMOLN-01, TKLMOLN-02): the station belongs to the account in
    ID. Log in with a code to the e-mail, make a station and save it in Synk, change it and save
    again, and in a new browser open it from Dina stationer, logged in to ID since before."""
    browser = Browser(base, tkl, session="/api/tkl/1/state")
    first = browser.session()
    check(first.get("login") is True and first.get("account") is None, f"Inte inloggning: {first}")
    no_pin = {"name": "Provstation", "station_id": "prov", "pin": "4711"}
    check(browser.app.post("/api/tkl/1/setup", json=no_pin).status_code == 409, "Första start.")
    page = browser.open("/api/tkl/1/id/login")
    check(page.status_code == 200 and "Skicka en kod" in page.text, "ID:s sida kom inte.")
    address = f"prov-{secrets.token_hex(4)}@example.com"
    create = browser.id.post(page.text, {"create": "1"}).text
    seen = mail_count(mails)
    sent = browser.id.post(
        create, {"creating": "1", "name": "Provare Sex", "email": address, "send": "1"}
    )
    code, _ = code_from(mails, address, seen)
    offer = browser.id.post(sent.text, {"code": code})
    back = browser.id.post(offer.text, {"passkey": "no"})
    check(back.status_code == 302, f"ID skickade inte tillbaka: {back.status_code}.")
    check(back.headers["location"].startswith(tkl.rstrip("/")), "Inte tillbaka till TKL.")
    landed = browser.app.get(back.headers["location"].removeprefix(tkl.rstrip("/")))
    check(landed.headers.get("location") == "/", "TKL loggade inte in med ID.")
    account = browser.session().get("account")
    check(isinstance(account, dict) and account.get("person") == "Provare Sex", f"{account}")
    check(address not in json.dumps(browser.session()), "TKL visar adressen.")
    station = f"prov-{secrets.token_hex(3)}"
    made = browser.app.post(
        "/api/tkl/1/konto/stationer", json={"name": "Provstation", "station_id": station}
    )
    check(made.status_code == 201, f"Ny station svarade {made.status_code}: {made.text}")
    check(made.json()["account"]["base"] == 1, f"Inte version 1 i molnet: {made.json()}")
    draft = browser.app.get("/api/tkl/1/studio").json()["draft"]
    draft["tracks"].append({"id": "3", "label": "Spår 3"})
    check(browser.app.put("/api/tkl/1/studio", json=draft).status_code == 200, "Ingen ändring.")
    saved = browser.app.post("/api/tkl/1/id/save", json={})
    check(saved.json().get("version") == 2, f"Spara i molnet svarade {saved.text}")
    print("TKL i molnet: inloggad med ID, stationen skapad och sparad i Synk: ok")
    # A new browser, logged in to ID since before: no new code, the station from the cloud.
    browser.app = httpx.Client(base_url=tkl.rstrip("/"), follow_redirects=False, timeout=20)
    seen = mail_count(mails)
    browser.open("/api/tkl/1/id/login")
    again = browser.session().get("account")
    check(isinstance(again, dict) and again.get("person") == "Provare Sex", f"{again}")
    check(mail_count(mails) == seen, "En ny kod skickades fast man redan var inloggad i ID.")
    listed = browser.app.get("/api/tkl/1/konto/stationer").json()
    mine = [s for s in listed.get("stations", []) if s["station_id"] == station]
    check(len(mine) == 1 and mine[0]["version"] == 2, f"Dina stationer: {listed}")
    opened = browser.app.post(f"/api/tkl/1/konto/stationer/{station}/oppna")
    check(opened.status_code == 200, f"Öppna svarade {opened.status_code}: {opened.text}")
    tracks = browser.app.get("/api/tkl/1/studio").json()["draft"]["tracks"]
    check([t["label"] for t in tracks][-1] == "Spår 3", f"Inte den sparade versionen: {tracks}")
    print("TKL i molnet: stationen öppnad ur Dina stationer i en ny webbläsare: ok")


def log_in_to_app(browser: Browser, mails: Path, address: str, name: str, start: str) -> None:
    """A new account through the app's login, with the code, and back into the app."""
    page = browser.open(start)
    check(page.status_code == 200 and "Skicka en kod" in page.text, "ID:s sida kom inte.")
    create = browser.id.post(page.text, {"create": "1"}).text
    seen = mail_count(mails)
    sent = browser.id.post(create, {"creating": "1", "name": name, "email": address, "send": "1"})
    code, _ = code_from(mails, address, seen)
    offer = browser.id.post(sent.text, {"code": code})
    check(OFFER in offer.text, "ID frågade inte om en passkey.")
    back = browser.id.post(offer.text, {"passkey": "no"})
    check(back.status_code == 302, f"ID skickade inte tillbaka: {back.status_code}.")
    landed = browser.open(back.headers["location"])
    check(landed.status_code == 200, f"Appen svarade {landed.status_code} efter inloggningen.")


def run_id_api(base: str, mails: Path, id_app: str) -> None:
    """ID's own web app and API (#67): a club, an invitation by mail, and a yes."""
    kim = Browser(base, id_app, "/api/id/1/session")
    check(kim.session()["account"] is None, "Inloggad i ID:s webbapp utan att ha loggat in.")
    kim_address = f"prov-{secrets.token_hex(4)}@example.com"
    log_in_to_app(kim, mails, kim_address, "Provare Klubb", "/api/id/1/login?next=%2Fklubbar")
    account = kim.session()["account"]
    check(
        isinstance(account, dict) and account.get("email") == kim_address,
        "ID:s webbapp vet inte vem som loggat in.",
    )
    made = kim.app.post("/api/id/1/clubs", json={"name": "Provklubben"})
    check(made.status_code == 201 and made.json()["role"] == "admin", "Klubben skapades inte.")
    club = made.json()["id"]
    sara_address = f"prov-{secrets.token_hex(4)}@example.com"
    seen = mail_count(mails)
    invited = kim.app.post(f"/api/id/1/clubs/{club}/invitations", json={"email": sara_address})
    check(
        invited.status_code == 201, f"Inbjudan svarade {invited.status_code}: {invited.text[:200]}"
    )
    for _ in range(50):
        text = mails.read_text(encoding="utf-8") if mails.exists() else ""
        parts = [p for p in text.split("----\n") if p.strip()][seen:]
        if any(sara_address in p.splitlines()[0] and "bjuder in dig" in p for p in parts):
            break
        time.sleep(0.2)
    else:
        raise ProvFel("Inget mejl med inbjudan.")
    print("ID:s webbapp: inloggad, klubben skapad och inbjudan skickad: ok")

    sara = Browser(base, id_app, "/api/id/1/session")
    log_in_to_app(sara, mails, sara_address, "Provare Medlem", "/api/id/1/login")
    waiting = sara.app.get("/api/id/1/invitations").json()
    check([w["title"] for w in waiting] == ["Provklubben"], "Inbjudan syns inte för mottagaren.")
    yes = sara.app.post(f"/api/id/1/invitations/{waiting[0]['id']}/answer", json={"accept": True})
    check(yes.status_code == 200, f"Svaret gick inte: {yes.status_code}")
    members = kim.app.get(f"/api/id/1/clubs/{club}").json()["members"]
    check(
        [(m["person"]["name"], m["role"]) for m in members]
        == [("Provare Klubb", "admin"), ("Provare Medlem", "member")],
        "Medlemmarna stämmer inte.",
    )
    print("ID:s webbapp: inbjudan besvarad, medlem i klubben: ok")

    # Träffarna (ID10): administratören lägger till en träff och delar ut en roll till Sara.
    autumn = {"name": "Provträffen", "starts_on": "2026-11-13", "ends_on": "2026-11-15"}
    meet = kim.app.post(f"/api/id/1/clubs/{club}/meets", json=autumn)
    check(meet.status_code == 201, f"Träffen svarade {meet.status_code}: {meet.text[:200]}")
    sara_id = str(sara.session()["account"]["id"])  # type: ignore[index]
    given = kim.app.post(
        f"/api/id/1/meets/{meet.json()['id']}/grants",
        json={"person": sara_id, "role": "dispatcher"},
    )
    check(given.status_code == 200, f"Rollen svarade {given.status_code}: {given.text[:200]}")
    mine = sara.app.get("/api/id/1/meets").json()
    check(
        [(m["name"], m["roles"]) for m in mine] == [("Provträffen", ["dispatcher"])],
        f"Sara ser inte sin roll på träffen: {mine}",
    )
    print("ID:s webbapp: träffen och rollen Trafikledare: ok")

    # Hjälp och fel (KONTO-06): ett mejl till supportadressen, med svar till personen.
    seen = mail_count(mails)
    report = {"kind": "fault", "text": "Provet rapporterar ett fel.", "app": "catalog"}
    helped = kim.app.post("/api/id/1/help", json={**report, "page": "/fordon", "version": "prov"})
    check(helped.status_code == 200, f"Hjälp och fel svarade {helped.status_code}: {helped.text}")
    for _ in range(50):
        text = mails.read_text(encoding="utf-8") if mails.exists() else ""
        parts = [p for p in text.split("----\n") if p.strip()][seen:]
        if any("[TrainMeet Catalog] Fel från Provare Klubb" in p for p in parts):
            break
        time.sleep(0.2)
    else:
        raise ProvFel("Inget mejl till supporten.")
    print("ID:s webbapp: Hjälp och fel som mejl till supporten: ok")


def run_sharing(base: str, mails: Path, catalog: str, id_app: str) -> None:
    """#49: Kim shares the fleet in ID, Sara sees it in Catalog, and it stops at once (CAT-48)."""
    kim, sara = Browser(base, catalog), Browser(base, catalog)
    kim_address = f"prov-{secrets.token_hex(4)}@example.com"
    sara_address = f"prov-{secrets.token_hex(4)}@example.com"
    log_in_to_app(kim, mails, kim_address, "Provare Ägare", "/api/catalog/1/id/login")
    log_in_to_app(sara, mails, sara_address, "Provare Lånare", "/api/catalog/1/id/login")
    kim_account = kim.session()["account"]
    assert isinstance(kim_account, dict)
    owner = str(kim_account["id"])
    car = {"status": "ready", "kind": "freight_wagon", "litt": "Hbis", "number": "1"}
    made = kim.app.post("/api/catalog/1/vehicles", json=car)
    check(made.status_code == 201, f"Fordonet skapades inte: {made.status_code}")
    in_kims = f"/api/catalog/1/vehicles?fleet={owner}"
    check(sara.app.get(in_kims).status_code == 404, "Någon annans vagnpark syntes utan delning.")

    # Kim shares in ID; the login to ID's web app goes without a code (KONTO-01).
    kim_id, sara_id = (Browser(base, id_app, "/api/id/1/session") for _ in range(2))
    for browser, catalog_browser in ((kim_id, kim), (sara_id, sara)):
        browser.id.client.cookies = catalog_browser.id.client.cookies
        browser.open("/api/id/1/login")
        check(browser.session()["account"] is not None, "Inte inloggad i ID:s webbapp.")
    shared = kim_id.app.post(
        f"/api/id/1/fleets/{owner}/invitations", json={"email": sara_address, "role": "viewer"}
    )
    check(shared.status_code == 201, f"Delningen svarade {shared.status_code}: {shared.text[:200]}")
    waiting = sara_id.app.get("/api/id/1/invitations").json()
    check(len(waiting) == 1, "Inbjudan till vagnparken syns inte.")
    sara_id.app.post(f"/api/id/1/invitations/{waiting[0]['id']}/answer", json={"accept": True})

    fleets = sara.app.get("/api/catalog/1/fleets").json()
    check(
        [(f["owner"], f["right"]) for f in fleets][1:] == [(owner, "view")],
        f"Catalog visar inte den delade vagnparken: {fleets}",
    )
    seen = sara.app.get(in_kims)
    check(seen.status_code == 200 and seen.json()["total"] == 1, "Den delade vagnparken syns inte.")
    vehicle = seen.json()["vehicles"][0]
    change = {**car, "number": "2", "version": vehicle["version"]}
    refused = sara.app.put(f"/api/catalog/1/vehicles/{vehicle['id']}?fleet={owner}", json=change)
    check(refused.status_code == 403, "Att titta gav rätt att ändra.")
    print("Delad vagnpark i Catalog efter ja i ID, bara att titta: ok")

    grant = kim_id.app.get(f"/api/id/1/fleets/{owner}").json()["grants"][0]["id"]
    check(
        kim_id.app.delete(f"/api/id/1/grants/{grant}").status_code == 200,
        "Gick inte att sluta dela.",
    )
    check(sara.app.get(in_kims).status_code == 404, "Delningen gällde efter att den tagits bort.")
    print("Sluta dela gäller direkt: ok")


def run_club_fleet(base: str, mails: Path, catalog: str, id_app: str) -> None:
    """#49, CAT-51, C39: a club's fleet in Catalog. The administrator does the owner's things,
    a QR label too, and a member only looks."""
    kim, sara = Browser(base, catalog), Browser(base, catalog)
    sara_address = f"prov-{secrets.token_hex(4)}@example.com"
    log_in_to_app(
        kim,
        mails,
        f"prov-{secrets.token_hex(4)}@example.com",
        "Provare Admin",
        "/api/catalog/1/id/login",
    )
    log_in_to_app(sara, mails, sara_address, "Provare Medlem", "/api/catalog/1/id/login")
    kim_id, sara_id = (Browser(base, id_app, "/api/id/1/session") for _ in range(2))
    for browser, catalog_browser in ((kim_id, kim), (sara_id, sara)):
        browser.id.client.cookies = catalog_browser.id.client.cookies
        browser.open("/api/id/1/login")
    club = kim_id.app.post("/api/id/1/clubs", json={"name": "Provklubbens bana"}).json()["id"]
    kim_id.app.post(f"/api/id/1/clubs/{club}/invitations", json={"email": sara_address})
    waiting = sara_id.app.get("/api/id/1/invitations").json()
    sara_id.app.post(f"/api/id/1/invitations/{waiting[0]['id']}/answer", json={"accept": True})

    rights = {f["owner"]: f["right"] for f in kim.app.get("/api/catalog/1/fleets").json()}
    check(rights.get(club) == "owner", f"Administratören har inte ägarens rätt: {rights}")
    in_club = f"fleet={club}"
    box = kim.app.post(f"/api/catalog/1/places?{in_club}", json={"name": "Klubblådan"})
    check(box.status_code == 201, f"Platsen i klubbens vagnpark svarade {box.status_code}.")
    car = {"status": "ready", "kind": "freight_wagon", "litt": "Hbis", "number": "7"}
    made = kim.app.post(f"/api/catalog/1/vehicles?{in_club}", json=car)
    check(made.status_code == 201, f"Fordonet i klubbens vagnpark svarade {made.status_code}.")
    label = kim.app.post(
        f"/api/catalog/1/vehicles/{made.json()['id']}/tags/qr?{in_club}", json={"replace": None}
    )
    check(label.status_code == 200 and label.json()["tags"], "Ingen QR-etikett i klubben.")
    uid = label.json()["tags"][0]["uid"]
    found = kim.app.get(f"/api/catalog/1/tags/{uid}").json()
    check(
        (found.get("outcome"), found.get("owner")) == ("fleet", club),
        f"Taggen öppnar inte kortet i klubbens vagnpark: {found}",
    )
    check(kim.app.get("/api/catalog/1/vehicles").json()["total"] == 0, "Fordonet hamnade hos Kim.")
    print("Klubbens vagnpark: administratören med plats, fordon och QR-etikett: ok")

    rights = {f["owner"]: f["right"] for f in sara.app.get("/api/catalog/1/fleets").json()}
    check(rights.get(club) == "view", f"Medlemmen ser inte klubbens vagnpark: {rights}")
    seen = sara.app.get(f"/api/catalog/1/vehicles?{in_club}").json()["vehicles"]
    check(
        [(v["tagged"], v["tags"]) for v in seen] == [(True, [])],
        "Medlemmen ser fel om taggen.",
    )
    refused = sara.app.post(f"/api/catalog/1/vehicles?{in_club}", json=car)
    check(refused.status_code == 403, "En medlem kunde lägga till i klubbens vagnpark.")
    print("Klubbens vagnpark: medlemmen tittar: ok")


def run_removal(base: str, mails: Path, catalog: str, id_app: str) -> None:
    """KONTO-31, CAT-193, ID13: the file first, then the account goes in Catalog, Keycloak and
    ID, with the club the person was alone in. The same address later gets a new account."""
    address = f"prov-{secrets.token_hex(4)}@example.com"
    in_catalog = Browser(base, catalog)
    log_in_to_app(in_catalog, mails, address, "Provare Bort", "/api/catalog/1/id/login")
    car = {"status": "ready", "kind": "freight_wagon", "litt": "Gbs", "number": "9"}
    check(
        in_catalog.app.post("/api/catalog/1/vehicles", json=car).status_code == 201, "Inget fordon."
    )
    in_id = Browser(base, id_app, "/api/id/1/session")
    in_id.id.client.cookies = in_catalog.id.client.cookies
    in_id.open("/api/id/1/login")
    account = in_id.session()["account"]
    check(isinstance(account, dict), "Inte inloggad i ID:s webbapp.")
    assert isinstance(account, dict)
    in_id.app.post("/api/id/1/clubs", json={"name": "Ensam klubb"})

    file = in_id.app.get("/api/id/1/account/export")
    check(file.status_code == 200, f"Filen svarade {file.status_code}: {file.text[:200]}")
    body = file.json()
    check(
        [v["litt"] for v in body["catalog"]["vehicles"]] == ["Gbs"]
        and [c["name"] for c in body["clubs"]] == ["Ensam klubb"],
        "Filen saknar Catalogs fordon eller klubben.",
    )
    print("Ta bort kontot: filen med ID:s och Catalogs uppgifter: ok")

    plan = in_id.app.get("/api/id/1/account/removal").json()
    check([c["name"] for c in plan["clubs_removed"]] == ["Ensam klubb"], f"Planen: {plan}")
    gone = in_id.app.post("/api/id/1/account/remove", json={"confirm": True})
    check(gone.status_code == 200, f"Borttagningen svarade {gone.status_code}: {gone.text[:200]}")
    check(in_id.session()["account"] is None, "Fortfarande inloggad i ID:s webbapp.")
    check(in_catalog.session()["account"] is None, "Fortfarande inloggad i Catalog.")
    again = Browser(base, catalog)
    log_in_to_app(again, mails, address, "Provare Igen", "/api/catalog/1/id/login")
    new = again.session()["account"]
    check(isinstance(new, dict) and new.get("id") != account["id"], "Samma konto finns kvar.")
    check(again.app.get("/api/catalog/1/vehicles").json()["total"] == 0, "Fordonet finns kvar.")
    print("Ta bort kontot: borta i Catalog, Keycloak och ID, och adressen får ett nytt konto: ok")


def main(argv: list[str]) -> int:
    through_catalog = "--catalog" in argv
    id_app = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--id-app=")), None)
    hub = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--hub=")), None)
    tkl = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--tkl=")), None)
    moln = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--tkl-moln=")), None)
    argv = [
        arg
        for arg in argv
        if arg != "--catalog"
        and not arg.startswith(("--id-app=", "--hub=", "--tkl=", "--tkl-moln="))
    ]
    if len(argv) != 5:
        print(__doc__)
        return 2
    try:
        run(argv[1], Path(argv[2]), argv[3], argv[4])
        if through_catalog:
            run_catalog(argv[1], Path(argv[2]), argv[4])
        if id_app:
            run_id_api(argv[1], Path(argv[2]), id_app)
            run_tokens(argv[1], Path(argv[2]), argv[3], id_app)
        if id_app and through_catalog:
            run_sharing(argv[1], Path(argv[2]), argv[4], id_app)
            run_club_fleet(argv[1], Path(argv[2]), argv[4], id_app)
            run_removal(argv[1], Path(argv[2]), argv[4], id_app)
        if hub:
            run_hub(argv[1], Path(argv[2]), hub)
        if hub and id_app:
            run_hub_roles(argv[1], Path(argv[2]), hub, id_app)
        if tkl:
            run_tkl(argv[1], Path(argv[2]), tkl)
        if moln:
            run_tkl_moln(argv[1], Path(argv[2]), moln)
    except ProvFel as fel:
        print(f"FEL: {fel}", file=sys.stderr)
        return 1
    print("Inloggningen med kod till e-posten fungerar.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
