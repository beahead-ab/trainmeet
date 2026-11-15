"""Hjälp och fel (KONTO-06, ID9, ID12): a question or a fault, as a mail to Beahead's support.

Every app's account menu leads to ID's help page with the app, the page and the version. ID sends
the mail, with the person's verified address to answer to. The support address is a setting
(ID_SUPPORT_ADDRESS), never in the code. A person sends at most a few an hour.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from contracts.common import AppKey
from contracts.id import Account, HelpKind, HelpRequest, HelpSent, ProblemCode
from id.roles import Refused

APP_NAMES = {
    AppKey.HUB: "TrainMeet Hub",
    AppKey.TKL: "TrainMeet TKL",
    AppKey.CAD: "TrainMeet CAD",
    AppKey.CATALOG: "TrainMeet Catalog",
    AppKey.DRIVER: "Lokföraren",
    AppKey.ID: "TrainMeet ID",
}
PER_HOUR = 5


class HelpMailer(Protocol):
    def help(self, to: str, reply_to: str, subject: str, body: str) -> None: ...


def help_text(account: Account, request: HelpRequest, at: datetime) -> tuple[str, str]:
    """The mail to support. The person's own text only goes in the body, never in a header."""
    app = APP_NAMES[request.app]
    what = "Fel" if request.kind == HelpKind.FAULT else "Hjälp"
    subject = f"[{app}] {what} från {account.name}"
    body = (
        f"{what} från {account.name} <{account.email}>, verifierad i TrainMeet ID.\n"
        "Svara på det här mejlet för att svara personen.\n\n"
        f"Appen: {app}\n"
        f"Sidan: {request.page or 'okänd'}\n"
        f"Versionen: {request.version or 'okänd'}\n"
        f"Tid: {at.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
        f"{request.text}\n"
    )
    return subject, body


class HelpDesk:
    def __init__(
        self,
        mailer: HelpMailer,
        support: str | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mailer = mailer
        self.support = support
        self.clock = clock
        self.sent: dict[UUID, deque[float]] = defaultdict(deque)

    def send(self, account: Account, request: HelpRequest) -> HelpSent:
        if self.support is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "Hjälp och fel går inte att skicka här.")
        now = self.clock()
        recent = self.sent[account.id]
        while recent and now - recent[0] > 3600:
            recent.popleft()
        if len(recent) >= PER_HOUR:
            raise Refused(
                429, ProblemCode.TOO_MANY, "Du har skickat flera nyss. Försök igen om en stund."
            )
        subject, body = help_text(account, request, datetime.now(UTC))
        self.mailer.help(self.support, account.email, subject, body)
        recent.append(now)
        return HelpSent()
