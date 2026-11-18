"""Köp av tokens (#79, TOKEN-02, TOKEN-11, TOKEN-27): paketen betalas med kort i Stripe Checkout.

The person picks a package in ID's web app and pays on Stripe's own page; Stripe sends the
receipt by e-mail. The bought tokens come when Stripe says the payment is done, through the
webhook, which is signed by Stripe and checked here. A purchase is credited once, however many
times Stripe tells it. A club's balance is bought for by the club's admin.

Buying is open only in Stripe's test mode until the question MOMS is decided (#92): a key that
is not a test key is not used, and the shop says it is closed.

Settings, from the environment:

ID_STRIPE_KEY_FILE   A file in ID's vault with Stripe's secret key on the first line (sk_test_…)
                     and the webhook's signing secret on the second (whsec_…). Without the file,
                     or with a key that is not a test key, the shop is closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx

from contracts.id import ProblemCode
from contracts.tokens import (
    PACKAGES,
    TokenCheckout,
    TokenOwnerKind,
    TokenPurchase,
    TokenShop,
)
from id.db import Database
from id.roles import Asker, Refused
from id.tokens import Tokens

LOGGER = logging.getLogger("id.shop")

STRIPE_API: Final = "https://api.stripe.com/v1"
TOLERANCE: Final = 300
"""How old a signed event from Stripe may be, in seconds, as Stripe's own libraries allow."""
PAID_EVENTS: Final = ("checkout.session.completed", "checkout.session.async_payment_succeeded")


@dataclass(frozen=True)
class ShopSettings:
    key_file: Path


def settings_from(env: Mapping[str, str] | None = None) -> ShopSettings | None:
    source = os.environ if env is None else env
    key_file = source.get("ID_STRIPE_KEY_FILE", "").strip()
    if not key_file or not Path(key_file).is_file():
        return None
    return ShopSettings(key_file=Path(key_file))


def signed(body: bytes, header: str | None, secret: str, now: float) -> bool:
    """Stripe's signature: t=<time>,v1=<HMAC-SHA256 of "<time>.<body>"> with the endpoint's
    secret, not older than five minutes."""
    if not header:
        return False
    pairs = [part.strip().split("=", 1) for part in header.split(",") if "=" in part]
    stamp = next((value for key, value in pairs if key == "t"), "")
    given = [value for key, value in pairs if key == "v1"]
    try:
        when = int(stamp)
    except ValueError:
        return False
    if abs(now - when) > TOLERANCE:
        return False
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, value) for value in given)


class Shop:
    def __init__(
        self,
        db: Database,
        tokens: Tokens,
        settings: ShopSettings | None,
        http: httpx.Client,
        public_url: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.tokens = tokens
        self.settings = settings
        self.http = http
        self.public_url = public_url.rstrip("/")
        self.clock = clock

    def _keys(self) -> tuple[str, str] | None:
        """Stripe's test key and the webhook's secret, or None while the shop is closed."""
        if self.settings is None:
            return None
        try:
            secret, webhook = self.settings.key_file.read_text(encoding="utf-8").split()[:2]
        except (OSError, ValueError):
            return None
        if not secret.startswith(("sk_test_", "rk_test_")):
            LOGGER.warning("Bara Stripes testläge används tills frågan MOMS är avgjord.")
            return None
        return secret, webhook

    def shop(self) -> TokenShop:
        return TokenShop(mode="test" if self._keys() else "off", packages=list(PACKAGES))

    def start(self, asker: Asker, purchase: TokenPurchase) -> TokenCheckout:
        """A purchase that waits for Stripe, and Stripe's page to pay on."""
        keys = self._keys()
        if keys is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "Köpen är inte öppna än.")
        package = next(p for p in PACKAGES if p.tokens == purchase.tokens)
        bought = uuid.uuid4()
        with self.db.transaction() as conn:
            if purchase.owner.kind == TokenOwnerKind.PERSON:
                if purchase.owner.id != asker.id:
                    raise Refused(403, ProblemCode.FORBIDDEN, "Du köper till ditt eget saldo.")
                what = f"{package.tokens} TrainMeet tokens"
            else:
                admin = conn.execute(
                    "SELECT c.name FROM role_grant g JOIN club c ON c.id::text = g.resource_id "
                    "WHERE g.resource_kind = 'club' AND g.resource_id = %s AND g.person_id = %s "
                    "AND g.role = 'admin'",
                    (str(purchase.owner.id), asker.id),
                ).fetchone()
                if admin is None:
                    raise Refused(
                        403,
                        ProblemCode.FORBIDDEN,
                        "Bara klubbens administratör köper till klubbens saldo.",
                    )
                what = f"{package.tokens} TrainMeet tokens till {admin['name']}"[:120]
            account = self.tokens.account_id(conn, purchase.owner)
            conn.execute(
                "INSERT INTO token_purchase (id, account_id, person_id, tokens, price_sek, mode) "
                "VALUES (%s, %s, %s, %s, %s, 'test')",
                (bought, account, asker.id, package.tokens, package.price_sek),
            )
        form = {
            "mode": "payment",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "sek",
            "line_items[0][price_data][unit_amount]": str(package.price_sek * 100),
            "line_items[0][price_data][product_data][name]": what,
            "success_url": f"{self.public_url}/tokens?kop=klart",
            "cancel_url": f"{self.public_url}/tokens?kop=avbrutet",
            "client_reference_id": str(bought),
            "metadata[purchase]": str(bought),
            "customer_email": asker.email,
            "payment_intent_data[receipt_email]": asker.email,
            "locale": "sv",
        }
        try:
            answer = self.http.post(
                f"{STRIPE_API}/checkout/sessions",
                data=form,
                headers={"Authorization": f"Bearer {keys[0]}", "Idempotency-Key": str(bought)},
                timeout=20.0,
            )
        except httpx.HTTPError as error:
            LOGGER.warning("Stripe svarar inte: %s", type(error).__name__)
            raise Refused(
                502, ProblemCode.UNAVAILABLE, "Betalningen gick inte att starta. Försök igen."
            ) from error
        if answer.status_code != 200:
            LOGGER.warning("Stripe svarade %s.", answer.status_code)
            raise Refused(
                502, ProblemCode.UNAVAILABLE, "Betalningen gick inte att starta. Försök igen."
            )
        session = answer.json()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE token_purchase SET stripe_session = %s WHERE id = %s",
                (str(session["id"]), bought),
            )
        return TokenCheckout(url=str(session["url"]))

    def webhook(self, body: bytes, signature: str | None) -> None:
        """Stripe says a payment is done: the tokens come, once."""
        keys = self._keys()
        if keys is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "Köpen är inte öppna än.")
        if not signed(body, signature, keys[1], self.clock()):
            raise Refused(400, ProblemCode.INVALID, "Signaturen stämmer inte.")
        try:
            event = json.loads(body)
            kind = str(event["type"])
            found = event["data"]["object"]
        except (ValueError, KeyError, TypeError) as error:
            raise Refused(400, ProblemCode.INVALID, "Händelsen gick inte att läsa.") from error
        if kind not in PAID_EVENTS or found.get("payment_status") != "paid":
            return
        try:
            purchase = UUID(str(found.get("client_reference_id")))
        except ValueError:
            LOGGER.warning("En betalning utan köp från ID.")
            return
        self._paid(purchase, str(found.get("id")))

    def _paid(self, purchase: UUID, session: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM token_purchase WHERE id = %s FOR UPDATE", (purchase,)
            ).fetchone()
            if row is None or row["stripe_session"] != session:
                LOGGER.warning("En betalning som inte hör till ett köp i ID.")
                return
            if row["state"] == "paid":
                return
            conn.execute(
                "UPDATE token_purchase SET state = 'paid', paid_at = now() WHERE id = %s",
                (purchase,),
            )
            conn.execute(
                "UPDATE token_account SET bought = bought + %s WHERE id = %s",
                (row["tokens"], row["account_id"]),
            )
