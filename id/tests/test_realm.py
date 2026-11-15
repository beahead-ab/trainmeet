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
    # Every "tm..." string in the code is a text's key, except the page's own attribute.
    used |= set(re.findall(r'"(tm[A-Z]\w+)"', JAVA.read_text(encoding="utf-8"))) - {"tmPage"}
    assert used, "No texts found"
    assert used <= known, sorted(used - known)


def test_the_pages_the_code_shows_exist() -> None:
    pages = set(re.findall(r'"(tm-\w+\.ftl)"', JAVA.read_text(encoding="utf-8")))
    assert pages == {"tm-email.ftl", "tm-create.ftl", "tm-code.ftl", "tm-name.ftl"}
    for page in pages:
        assert (THEME / page).is_file(), page
