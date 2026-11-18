"""Köp av tokens (#79, TOKEN-02, TOKEN-11): Stripe Checkout i testläge, och webhooken.

A pretend Stripe answers the Checkout session; the webhook's events are signed here with the
test's own secret, as Stripe signs them. No real payment is made.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.tokens import TokenCheckout, TokenShop
from id.app import create_app
from id.settings import Settings
from id.shop import ShopSettings, signed
from id.tests.test_api import (
    INTERNAL,
    ISSUER,
    PUBLIC,
    SECRET,
    Who,
    World,
    club_with,
    log_in,
)

WEBHOOK_SECRET = "whsec_prov"


@dataclass
class PretendStripe:
    sessions: list[dict[str, str]] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/checkout/sessions"
        self.keys.append(request.headers["authorization"])
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.sessions.append(form)
        number = len(self.sessions)
        return httpx.Response(
            200,
            json={"id": f"cs_test_{number}", "url": f"https://checkout.stripe.com/c/pay/{number}"},
        )


@dataclass
class Shopping:
    world: World
    stripe: PretendStripe
    app: Any

    def as_(self, who: Who) -> TestClient:
        client = TestClient(self.app, base_url=PUBLIC, follow_redirects=False)
        client.cookies = who.client.cookies
        return client

    def event(self, purchase: str, session: str, paid: bool = True) -> httpx.Response:
        body = json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": session,
                        "client_reference_id": purchase,
                        "payment_status": "paid" if paid else "unpaid",
                    }
                },
            }
        ).encode()
        stamp = str(int(time.time()))
        mac = hmac.new(WEBHOOK_SECRET.encode(), f"{stamp}.".encode() + body, hashlib.sha256)
        client = TestClient(self.app, base_url=PUBLIC)
        answer: httpx.Response = client.post(
            "/api/id/1/stripe/webhook",
            content=body,
            headers={"Stripe-Signature": f"t={stamp},v1={mac.hexdigest()}"},
        )
        return answer


def shop_app(world: World, tmp_path: Path, key: str) -> tuple[Any, PretendStripe]:
    stripe = PretendStripe()
    keys = tmp_path / "trainmeet_stripe-key"
    keys.write_text(f"{key}\n{WEBHOOK_SECRET}\n")
    settings = Settings(
        database_url=world.url,
        issuer=ISSUER,
        internal=INTERNAL,
        client="id",
        secret=SECRET,
        public_url=PUBLIC,
        apps=("catalog", "hub"),
        web_dir=tmp_path,
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.stripe.com":
            return stripe.handle(request)
        return world.keycloak.handle(request)

    app = create_app(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handle)),
        mailer=world.mail,
        shop_settings=ShopSettings(key_file=keys),
    )
    return app, stripe


@pytest.fixture
def shopping(world: World, tmp_path: Path) -> Iterator[Shopping]:
    app, stripe = shop_app(world, tmp_path, "sk_test_prov")
    with TestClient(app):
        yield Shopping(world, stripe, app)


def purchase_of(shopping: Shopping, number: int = -1) -> str:
    return shopping.stripe.sessions[number]["client_reference_id"]


def test_a_package_is_paid_with_stripe_and_the_tokens_come_once(shopping: Shopping) -> None:
    """TOKEN-02, TOKEN-11: the packages, Stripe's page to pay on, and the tokens when Stripe
    says the payment is done, once however many times Stripe says it."""
    kim = log_in(shopping.world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get("/api/id/1/session").json()["account"]["id"]
    me = shopping.as_(kim)
    shop = TokenShop.model_validate(me.get("/api/id/1/tokens/shop").json())
    assert shop.mode == "test"
    assert [(p.tokens, p.price_sek) for p in shop.packages] == [(500, 49), (1500, 129), (5000, 399)]

    bought = me.post(
        "/api/id/1/tokens/purchases",
        json={"owner": {"kind": "person", "id": kim.id}, "tokens": 1500},
    )
    assert bought.status_code == 200, bought.text
    checkout = TokenCheckout.model_validate(bought.json())
    assert checkout.url == "https://checkout.stripe.com/c/pay/1"
    form = shopping.stripe.sessions[0]
    assert (form["mode"], form["line_items[0][price_data][currency]"]) == ("payment", "sek")
    assert form["line_items[0][price_data][unit_amount]"] == "12900"
    assert form["line_items[0][price_data][product_data][name]"] == "1500 TrainMeet tokens"
    assert form["payment_intent_data[receipt_email]"] == "kim@example.com"
    assert form["success_url"] == PUBLIC + "/tokens?kop=klart"
    assert shopping.stripe.keys == ["Bearer sk_test_prov"]

    def balance() -> int:
        found: int = me.get("/api/id/1/tokens").json()[0]["bought"]
        return found

    assert balance() == 0, "nothing before Stripe says it is paid"
    assert shopping.event(purchase_of(shopping), "cs_test_1", paid=False).status_code == 200
    assert balance() == 0
    assert shopping.event(purchase_of(shopping), "cs_test_1").status_code == 200
    assert balance() == 1500
    assert shopping.event(purchase_of(shopping), "cs_test_1").status_code == 200
    assert balance() == 1500, "once"
    # The free quota is used first, then the bought tokens (TK2).
    assert me.get("/api/id/1/tokens").json()[0]["available"] == 1600


def test_only_stripe_signs_a_payment(shopping: Shopping) -> None:
    kim = log_in(shopping.world, "Kim Ek", "kim@example.com")
    kim.id = kim.client.get("/api/id/1/session").json()["account"]["id"]
    shopping.as_(kim).post(
        "/api/id/1/tokens/purchases",
        json={"owner": {"kind": "person", "id": kim.id}, "tokens": 500},
    )
    body = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}}).encode()
    client = TestClient(shopping.app, base_url=PUBLIC)
    forged = client.post(
        "/api/id/1/stripe/webhook", content=body, headers={"Stripe-Signature": "t=1,v1=00"}
    )
    assert forged.status_code == 400
    assert client.post("/api/id/1/stripe/webhook", content=body).status_code == 400
    # A paid session that is not the purchase's own credits nothing.
    assert shopping.event(purchase_of(shopping), "cs_test_annan").status_code == 200
    assert shopping.as_(kim).get("/api/id/1/tokens").json()[0]["bought"] == 0


def test_the_signature_is_stripes_and_not_too_old() -> None:
    body = b'{"type":"x"}'
    now = 1_800_000_000
    mac = hmac.new(b"whsec_s", f"{now}.".encode() + body, hashlib.sha256).hexdigest()
    assert signed(body, f"t={now},v1=00,v1={mac}", "whsec_s", now + 10)
    assert not signed(body, f"t={now},v1={mac}", "whsec_s", now + 301), "too old"
    assert not signed(body, f"t={now},v1={mac}", "whsec_annan", now)
    assert not signed(body + b" ", f"t={now},v1={mac}", "whsec_s", now)
    assert not signed(body, None, "whsec_s", now)


def test_the_clubs_admin_buys_for_the_club(shopping: Shopping) -> None:
    kim, club, people = club_with(shopping.world, ("Sara Holm", "sara@example.com"))
    asked = {"owner": {"kind": "club", "id": club}, "tokens": 5000}
    refused = shopping.as_(people["Sara Holm"]).post("/api/id/1/tokens/purchases", json=asked)
    assert refused.status_code == 403
    assert refused.json()["message"] == "Bara klubbens administratör köper till klubbens saldo."
    sara = people["Sara Holm"]
    mine = {"owner": {"kind": "person", "id": kim.id}, "tokens": 500}
    assert shopping.as_(sara).post("/api/id/1/tokens/purchases", json=mine).status_code == 403
    assert shopping.as_(kim).post("/api/id/1/tokens/purchases", json=asked).status_code == 200
    assert shopping.stripe.sessions[-1]["line_items[0][price_data][product_data][name]"] == (
        "5000 TrainMeet tokens till Västby MJK"
    )
    shopping.event(purchase_of(shopping), f"cs_test_{len(shopping.stripe.sessions)}")
    clubs = shopping.as_(kim).get("/api/id/1/tokens").json()
    assert [(b["title"], b["bought"]) for b in clubs] == [("Kim Ek", 0), ("Västby MJK", 5000)]


def test_buying_stays_closed_without_a_test_key(world: World, tmp_path: Path) -> None:
    """MOMS (#92): only Stripe's test mode until the question is decided."""
    kim = log_in(world, "Kim Ek", "kim@example.com")
    assert TokenShop.model_validate(kim.client.get("/api/id/1/tokens/shop").json()).mode == "off"
    app, stripe = shop_app(world, tmp_path, "sk_live_riktig")
    with TestClient(app):
        live = TestClient(app, base_url=PUBLIC)
        live.cookies = kim.client.cookies
        assert live.get("/api/id/1/tokens/shop").json()["mode"] == "off"
        kim_id = kim.client.get("/api/id/1/session").json()["account"]["id"]
        closed = live.post(
            "/api/id/1/tokens/purchases",
            json={"owner": {"kind": "person", "id": kim_id}, "tokens": 500},
        )
        assert (closed.status_code, closed.json()["message"]) == (503, "Köpen är inte öppna än.")
        assert stripe.sessions == []
