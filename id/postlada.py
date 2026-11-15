"""En låtsad mejlserver för provet av inloggningen: varje mejl skrivs till en fil, inget skickas.

    uvx --from aiosmtpd python id/postlada.py <fil> [port]

Med POSTLADA_ANVANDARE och POSTLADA_LOSENORD i miljön kräver den inloggning, som Scaleways
mejlserver, så att provet visar att ID läser lösenordet ur sitt valv. Används av kontrollen
"ID:s bild" och lokalt, tillsammans med id/prov_inloggning.py.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default
from typing import Any


class Postlada:
    def __init__(self, out: str) -> None:
        self.out = out

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        message = message_from_bytes(envelope.content, policy=default)
        assert isinstance(message, EmailMessage)
        body = message.get_body(preferencelist=("plain",))
        text = body.get_content() if body is not None else ""
        with open(self.out, "a", encoding="utf-8") as file:
            file.write(f"TO {envelope.rcpt_tos}\nSUBJECT {message['subject']}\n{text}\n----\n")
        return "250 OK"


def inloggning(user: str, password: str) -> Any:
    from aiosmtpd.smtp import AuthResult, LoginPassword  # type: ignore[import-not-found]

    def check(server: Any, session: Any, envelope: Any, mechanism: str, data: Any) -> Any:
        ok = (
            isinstance(data, LoginPassword)
            and secrets.compare_digest(data.login, user.encode())
            and secrets.compare_digest(data.password, password.encode())
        )
        return AuthResult(success=ok)

    return check


async def main(out: str, port: int) -> None:
    from aiosmtpd.controller import Controller  # type: ignore[import-not-found]

    user, password = os.environ.get("POSTLADA_ANVANDARE"), os.environ.get("POSTLADA_LOSENORD")
    login: dict[str, Any] = {}
    if user and password:
        login = {
            "authenticator": inloggning(user, password),
            "auth_required": True,
            "auth_require_tls": False,
        }
    Controller(Postlada(out), hostname="127.0.0.1", port=port, **login).start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2525))
