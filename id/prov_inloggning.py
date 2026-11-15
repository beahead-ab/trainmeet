"""Provar inloggningen i TrainMeet ID från början till slut, som en webbläsare och Catalog gör.

    python -m id.prov_inloggning <ID> <mejlfil> <klienthemlighet> <Catalog> [--catalog]
        [--id-app=<ID:s webbapp>]

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
administratören gör ägarens saker, medlemmen tittar (CAT-51, C39).

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


def main(argv: list[str]) -> int:
    through_catalog = "--catalog" in argv
    id_app = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--id-app=")), None)
    argv = [arg for arg in argv if arg != "--catalog" and not arg.startswith("--id-app=")]
    if len(argv) != 5:
        print(__doc__)
        return 2
    try:
        run(argv[1], Path(argv[2]), argv[3], argv[4])
        if through_catalog:
            run_catalog(argv[1], Path(argv[2]), argv[4])
        if id_app:
            run_id_api(argv[1], Path(argv[2]), id_app)
        if id_app and through_catalog:
            run_sharing(argv[1], Path(argv[2]), argv[4], id_app)
            run_club_fleet(argv[1], Path(argv[2]), argv[4], id_app)
    except ProvFel as fel:
        print(f"FEL: {fel}", file=sys.stderr)
        return 1
    print("Inloggningen med kod till e-posten fungerar.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
