"""TrainMeet ID's realm and login pages agree with each other, and hold no secret (#66).

The realm is read by Keycloak the first time it starts (id/Dockerfile). The login itself is
tried against a running Keycloak by id/prov_inloggning.py in the check "ID:s bild".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REALM = ROOT / "realm" / "trainmeet.json"
EXTENSION = ROOT / "email-code" / "src" / "main"
THEME = EXTENSION / "resources" / "theme" / "trainmeet" / "login"
JAVA = EXTENSION / "java" / "app" / "trainmeet" / "id" / "EmailCodeAuthenticator.java"
UPDATES = JAVA.with_name("RealmUpdates.java")


def realm() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REALM.read_text(encoding="utf-8"))
    return data


def messages(language: str) -> dict[str, str]:
    found: dict[str, str] = {}
    path = THEME / "messages" / f"messages_{language}.properties"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            found[key.strip()] = value.strip()
    return found


def test_the_login_is_the_code_to_the_email_and_nothing_else() -> None:
    data = realm()
    flow = next(f for f in data["authenticationFlows"] if f["alias"] == data["browserFlow"])
    steps = [(e["authenticator"], e["requirement"]) for e in flow["authenticationExecutions"]]
    assert steps == [("auth-cookie", "ALTERNATIVE"), ("trainmeet-email-code", "ALTERNATIVE")]
    assert data["registrationAllowed"] is False  # accounts are made by the code, not a form
    assert data["resetPasswordAllowed"] is False  # there are no passwords (KONTO-33)
    assert data["loginTheme"] == "trainmeet"
    assert (data["defaultLocale"], data["supportedLocales"]) == ("sv", ["sv", "en"])


def test_the_realm_holds_no_secret() -> None:
    data = realm()
    assert data["smtpServer"]["password"] == "${vault.smtp-password}"
    for client in data["clients"]:
        assert client["secret"].startswith("${") and client["secret"].endswith("}")
    text = REALM.read_text(encoding="utf-8")
    assert not re.search(r"@(?!trainmeet\.)[a-z0-9-]+\.[a-z]{2,}", text), "An address in the realm"


def test_catalog_logs_in_with_the_code_flow_and_pkce() -> None:
    catalog = next(c for c in realm()["clients"] if c["clientId"] == "catalog")
    assert catalog["publicClient"] is False
    assert catalog["standardFlowEnabled"] is True
    assert catalog["directAccessGrantsEnabled"] is False
    assert catalog["implicitFlowEnabled"] is False
    assert catalog["attributes"]["pkce.code.challenge.method"] == "S256"
    assert catalog["redirectUris"] == ["${ID_CATALOG_URL}/api/catalog/1/id/callback"]
    assert {"profile", "email"} <= set(catalog["defaultClientScopes"])


def test_the_theme_is_registered_with_keycloak() -> None:
    declared = json.loads(
        (EXTENSION / "resources" / "META-INF" / "keycloak-themes.json").read_text()
    )
    assert declared == {"themes": [{"name": "trainmeet", "types": ["login"]}]}
    factories = EXTENSION / "resources" / "META-INF" / "services"
    registered = (factories / "org.keycloak.authentication.AuthenticatorFactory").read_text()
    assert registered.strip() == "app.trainmeet.id.EmailCodeAuthenticatorFactory"


def test_every_text_is_in_swedish_and_english() -> None:
    swedish, english = messages("sv"), messages("en")
    assert set(swedish) == set(english)
    assert all(swedish.values()) and all(english.values())


def test_every_text_the_pages_and_the_code_use_exists() -> None:
    known = set(messages("sv"))
    used: set[str] = set()
    for page in THEME.glob("*.ftl"):
        used |= set(re.findall(r'msg\(\s*["\'](tm\w+)["\']', page.read_text(encoding="utf-8")))
    # Every "tm..." string in the code is a text's key, except the page's attribute and the
    # person's attribute that says when they were asked about a passkey.
    names = set(re.findall(r'"(tm[A-Z]\w+)"', JAVA.read_text(encoding="utf-8")))
    used |= names - {"tmPage", "tmPasskeyAsked"}
    assert used, "No texts found"
    assert used <= known, sorted(used - known)


def test_the_pages_the_code_shows_exist() -> None:
    pages = set(re.findall(r'"(tm-\w+\.ftl)"', JAVA.read_text(encoding="utf-8")))
    assert pages == {
        "tm-email.ftl",
        "tm-create.ftl",
        "tm-code.ftl",
        "tm-name.ftl",
        "tm-passkey.ftl",
    }
    # Keycloak's own pages for a passkey, in TrainMeet ID's look.
    for page in pages | {"webauthn-register.ftl", "webauthn-error.ftl"}:
        assert (THEME / page).is_file(), page


def test_passkey_is_the_option_beside_the_code() -> None:
    """KONTO-33, ID5: a passkey found without the address, and verified by the person."""
    data = realm()
    assert data["webAuthnPolicyPasswordlessPasskeysEnabled"] is True
    assert data["webAuthnPolicyPasswordlessResidentKey"] == "required"  # lower case, as WebAuthn
    assert data["webAuthnPolicyPasswordlessUserVerificationRequirement"] == "required"
    assert data["webAuthnPolicyPasswordlessRpEntityName"] == "TrainMeet"
    actions = {a["alias"]: a for a in data["requiredActions"]}
    register = actions["webauthn-register-passwordless"]
    assert register["enabled"] is True and register["defaultAction"] is False
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "KC_FEATURES=passkeys" in dockerfile


def test_an_existing_realm_is_updated_to_the_same_as_the_file() -> None:
    """Keycloak reads the file only for a new realm, so RealmUpdates brings an existing one to
    the same settings. The file says which update it already has."""
    updates = UPDATES.read_text(encoding="utf-8")
    latest = re.search(r"static final int LATEST = (\d+);", updates)
    assert latest is not None
    assert realm()["attributes"]["trainmeetVersion"] == latest.group(1)
    data = realm()
    # Update 2, passkeys: the same values as the file.
    assert f'setRpEntityName("{data["webAuthnPolicyPasswordlessRpEntityName"]}")' in updates
    assert f'setResidentKey("{data["webAuthnPolicyPasswordlessResidentKey"]}")' in updates
    assert (
        f'setUserVerificationRequirement("{data["webAuthnPolicyPasswordlessUserVerificationRequirement"]}")'
        in updates
    )
    assert "setPasskeysEnabled(true)" in updates
    assert 'PASSKEY_ACTION = "webauthn-register-passwordless"' in updates


def test_ids_own_web_app_logs_in_like_catalog_in_the_file_and_the_update() -> None:
    """#67: the client "id", the same in the realm file and in update 3."""
    client = next(c for c in realm()["clients"] if c["clientId"] == "id")
    assert client["publicClient"] is False and client["secret"] == "${ID_APP_SECRET}"
    assert client["standardFlowEnabled"] is True
    assert client["directAccessGrantsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["redirectUris"] == ["${ID_PUBLIC_URL}/api/id/1/login/callback"]
    updates = UPDATES.read_text(encoding="utf-8")
    assert 'address + "/api/id/1/login/callback"' in updates
    assert 'setAttribute("pkce.code.challenge.method", "S256")' in updates
    scopes = re.search(r"SCOPES = List.of\(([^)]*)\)", updates)
    assert scopes is not None
    assert re.findall(r'"([a-z-]+)"', scopes.group(1)) == client["defaultClientScopes"]
